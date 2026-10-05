"""Master-key providers: ``wrap``/``unwrap`` a tenant KEK under the environment's master (file or Vault Transit)."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from typing import Any, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .exceptions import DecryptError, MasterKeyError, MasterKeyPermissionError

logger = logging.getLogger(__name__)

MASTER_KEY_SIZE_BYTES: int = 32
GCM_IV_SIZE_BYTES: int = 12
GCM_TAG_SIZE_BYTES: int = 16

# Version-tagged AAD for KEK-wrapping: a format change fails closed instead of decrypting against the old one.
MASTER_WRAP_AAD: bytes = b"mdx-master-kek-v1"

# master_key_id markers, stored in EnvelopeBlob so re-wrap migrations know the master.
FILE_MASTER_KEY_ID: str = "file-v1"
VAULT_MASTER_KEY_ID_PREFIX: str = "vault:"


def _reveal(token: object) -> str:
    """Unwrap ``Secret[str]`` (whose ``.value()`` is a method) or pass a str."""
    accessor = getattr(token, "value", None)
    value = accessor() if callable(accessor) else token
    return value if isinstance(value, str) else ""


class MasterKeyProvider(Protocol):
    """Wrap / unwrap a tenant KEK under the master key; coroutine-safe, never exposes master-key bytes."""

    async def wrap(self, kek_plaintext: bytes) -> tuple[str, bytes]:
        """Wrap a 32-byte tenant KEK → ``(master_key_id, iv || ciphertext || tag)``."""
        ...

    async def unwrap(self, master_key_id: str, wrapped_kek: bytes) -> bytes:
        """Unwrap to the plaintext tenant KEK (caller zeroes it); :class:`DecryptError` on tag mismatch."""
        ...


class FileMasterKeyProvider:
    """Master key from a 0400-mode file (``MDX_MASTER_KEY_PATH``); :meth:`startup_self_check` refuses a bad mode or length."""

    def __init__(self, *, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._aead: AESGCM | None = None  # lazily loaded; cleared on rotate

    @property
    def master_key_id(self) -> str:
        return FILE_MASTER_KEY_ID

    def handles(self, master_key_id: str) -> bool:
        return master_key_id == FILE_MASTER_KEY_ID

    async def startup_self_check(self) -> None:
        """Verify the master key file's existence, mode and length; raises a :class:`MasterKeyError` subclass."""
        if not self._path.exists():
            raise MasterKeyError(
                f"master key file not found at {self._path!s}. "
                "See docs/runbooks/asr-worker.md § master-key-missing."
            )
        try:
            st = self._path.stat()
        except OSError as exc:
            raise MasterKeyError(
                f"master key file at {self._path!s} cannot be stat()'d: {type(exc).__name__}"
            ) from exc

        # Permission bits must be a subset of 0400.
        mode_bits = stat.S_IMODE(st.st_mode)
        if mode_bits & ~0o400:
            raise MasterKeyPermissionError(
                f"master key file at {self._path!s} has mode {oct(mode_bits)}; "
                "must be 0400 (read-only by owner). See "
                "docs/runbooks/asr-worker.md § master-key-permissions."
            )

        if st.st_size != MASTER_KEY_SIZE_BYTES:
            raise MasterKeyError(
                f"master key file at {self._path!s} is {st.st_size} bytes; "
                f"expected exactly {MASTER_KEY_SIZE_BYTES} bytes for AES-256."
            )

        # The AESGCM instance owns the key bytes; the raw key is not kept.
        with self._path.open("rb") as f:
            raw = f.read(MASTER_KEY_SIZE_BYTES)
        try:
            self._aead = AESGCM(raw)
        finally:
            # Best-effort zero.
            raw = b"\x00" * MASTER_KEY_SIZE_BYTES

        logger.info(
            "master_key.loaded",
            extra={
                "master_key_id": self.master_key_id,
                "path": str(self._path),
                "mode": oct(mode_bits),
            },
        )

    def _aead_or_raise(self) -> AESGCM:
        if self._aead is None:
            raise MasterKeyError("master key not loaded. Call startup_self_check() before use.")
        return self._aead

    async def wrap(self, kek_plaintext: bytes) -> tuple[str, bytes]:
        if len(kek_plaintext) != 32:
            raise MasterKeyError(f"tenant KEK must be 32 bytes, got {len(kek_plaintext)}")
        iv = os.urandom(GCM_IV_SIZE_BYTES)
        ct = self._aead_or_raise().encrypt(iv, kek_plaintext, MASTER_WRAP_AAD)
        # AESGCM returns ciphertext || tag; on-disk format is iv || ct || tag.
        return FILE_MASTER_KEY_ID, iv + ct

    async def unwrap(self, master_key_id: str, wrapped_kek: bytes) -> bytes:
        if master_key_id != FILE_MASTER_KEY_ID:
            raise MasterKeyError(
                f"master_key_id {master_key_id!r} is not handled by "
                "FileMasterKeyProvider. Wire build_master_key_provider / "
                "CompositeMasterKeyProvider for mixed-master reads (ADR-0011)."
            )
        if len(wrapped_kek) < GCM_IV_SIZE_BYTES + GCM_TAG_SIZE_BYTES:
            raise DecryptError("wrapped KEK is too short to be valid")
        iv, ct = wrapped_kek[:GCM_IV_SIZE_BYTES], wrapped_kek[GCM_IV_SIZE_BYTES:]
        try:
            return self._aead_or_raise().decrypt(iv, ct, MASTER_WRAP_AAD)
        except InvalidTag as exc:
            raise DecryptError(
                "master-key unwrap failed: GCM tag mismatch. The wrapped KEK "
                "may have been tampered with, or the master key has rotated."
            ) from exc


class KmsMasterKeyProvider:
    """Vault-Transit-backed master key (ADR-0011): the master KEK never leaves the KMS.

    ``master_key_id`` is ``vault:{mount}:{key_name}``; the ciphertext carries the key version, so Transit
    rotation needs no id change. Fail-closed: :meth:`startup_self_check` does a live round-trip.
    """

    def __init__(
        self,
        *,
        addr: str,
        token: object,
        key_name: str,
        mount: str = "transit",
        timeout_seconds: float = 5.0,
        http_client: Any | None = None,
    ) -> None:
        import httpx

        self._addr = addr.rstrip("/")
        # Secret[str] or str; held privately, never exposed.
        self._token: str = _reveal(token)
        if not self._token:
            raise MasterKeyError("Vault token is empty; refusing to construct provider")
        self._mount = mount.strip("/")
        self._key_name = key_name
        self._owns_client = http_client is None
        self._client: httpx.AsyncClient = http_client or httpx.AsyncClient(timeout=timeout_seconds)
        self._checked = False

    @property
    def master_key_id(self) -> str:
        return f"{VAULT_MASTER_KEY_ID_PREFIX}{self._mount}:{self._key_name}"

    def handles(self, master_key_id: str) -> bool:
        return master_key_id == self.master_key_id

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _url(self, op: str) -> str:
        return f"{self._addr}/v1/{self._mount}/{op}/{self._key_name}"

    async def _post(self, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        import httpx

        try:
            resp = await self._client.post(
                self._url(op),
                json=payload,
                headers={"X-Vault-Token": self._token},
            )
        except httpx.HTTPError as exc:
            raise MasterKeyError(
                f"Vault Transit unreachable at {self._addr} ({type(exc).__name__}). "
                "See docs/runbooks/kms.md § vault-unreachable."
            ) from exc
        if resp.status_code != 200:
            raise MasterKeyError(
                f"Vault Transit {op} returned {resp.status_code}: "
                f"{resp.text[:200]}. See docs/runbooks/kms.md."
            )
        data = resp.json().get("data")
        if not isinstance(data, dict):
            raise MasterKeyError(f"Vault Transit {op} returned no data object")
        return data

    async def startup_self_check(self) -> None:
        """Live encrypt/decrypt round-trip; raises MasterKeyError so the service refuses to start."""
        import base64

        probe = os.urandom(16)
        data = await self._post("encrypt", {"plaintext": base64.b64encode(probe).decode("ascii")})
        ct = data.get("ciphertext")
        if not isinstance(ct, str):
            raise MasterKeyError("Vault Transit self-check: encrypt returned no ciphertext")
        back = await self._post("decrypt", {"ciphertext": ct})
        pt_b64 = back.get("plaintext")
        if not isinstance(pt_b64, str) or base64.b64decode(pt_b64) != probe:
            raise MasterKeyError(
                "Vault Transit self-check: decrypt round-trip mismatch. "
                "The transit key may be derived/convergent — use a plain "
                "aes256-gcm96 key. See docs/runbooks/kms.md."
            )
        self._checked = True
        logger.info(
            "master_key.kms_ready",
            extra={"master_key_id": self.master_key_id, "vault_addr": self._addr},
        )

    async def wrap(self, kek_plaintext: bytes) -> tuple[str, bytes]:
        import base64

        if len(kek_plaintext) != MASTER_KEY_SIZE_BYTES:
            raise MasterKeyError(
                f"tenant KEK must be {MASTER_KEY_SIZE_BYTES} bytes, got {len(kek_plaintext)}"
            )
        data = await self._post(
            "encrypt",
            {"plaintext": base64.b64encode(kek_plaintext).decode("ascii")},
        )
        ct = data.get("ciphertext")
        if not isinstance(ct, str) or not ct.startswith("vault:"):
            raise MasterKeyError("Vault Transit encrypt returned malformed ciphertext")
        # UTF-8 bytes of Vault's versioned ciphertext string.
        return self.master_key_id, ct.encode("utf-8")

    async def unwrap(self, master_key_id: str, wrapped_kek: bytes) -> bytes:
        import base64

        if not self.handles(master_key_id):
            raise MasterKeyError(
                f"master_key_id {master_key_id!r} is not handled by this "
                f"KmsMasterKeyProvider ({self.master_key_id}). Wire a "
                "CompositeMasterKeyProvider for mixed-master reads (ADR-0011)."
            )
        try:
            ct = wrapped_kek.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DecryptError("wrapped KEK is not a Vault ciphertext string") from exc
        data = await self._post("decrypt", {"ciphertext": ct})
        pt_b64 = data.get("plaintext")
        if not isinstance(pt_b64, str):
            raise DecryptError("Vault Transit decrypt returned no plaintext")
        plaintext = base64.b64decode(pt_b64)
        if len(plaintext) != MASTER_KEY_SIZE_BYTES:
            raise DecryptError(
                f"Vault-unwrapped KEK is {len(plaintext)} bytes; expected "
                f"{MASTER_KEY_SIZE_BYTES}. The wrapped row is corrupt."
            )
        return plaintext


class CompositeMasterKeyProvider:
    """Route ``unwrap`` by ``master_key_id``, ``wrap`` under the primary: the KMS migration window (ADR-0011)."""

    def __init__(self, *, primary: Any, fallbacks: tuple[Any, ...] = ()) -> None:
        self._primary = primary
        self._members: tuple[Any, ...] = (primary, *fallbacks)

    @property
    def master_key_id(self) -> str:
        mid: str = self._primary.master_key_id
        return mid

    @property
    def members(self) -> tuple[Any, ...]:
        return self._members

    def _handles(self, member: Any, master_key_id: str) -> bool:
        handles = getattr(member, "handles", None)
        if callable(handles):
            return bool(handles(master_key_id))
        return bool(getattr(member, "master_key_id", None) == master_key_id)

    async def startup_self_check(self) -> None:
        """Fail-closed on the PRIMARY; a failing fallback is logged and tolerated (its reads fail audibly at unwrap)."""
        check = getattr(self._primary, "startup_self_check", None)
        if callable(check):
            await check()
        for member in self._members[1:]:
            mcheck = getattr(member, "startup_self_check", None)
            if not callable(mcheck):
                continue
            try:
                await mcheck()
            except MasterKeyError as exc:
                logger.warning(
                    "master_key.fallback_unavailable",
                    extra={
                        "master_key_id": getattr(member, "master_key_id", "?"),
                        "error": str(exc),
                    },
                )

    async def wrap(self, kek_plaintext: bytes) -> tuple[str, bytes]:
        result: tuple[str, bytes] = await self._primary.wrap(kek_plaintext)
        return result

    async def unwrap(self, master_key_id: str, wrapped_kek: bytes) -> bytes:
        for member in self._members:
            if self._handles(member, master_key_id):
                plaintext: bytes = await member.unwrap(master_key_id, wrapped_kek)
                return plaintext
        raise MasterKeyError(
            f"no configured master-key provider handles {master_key_id!r}. "
            "If this row predates the KMS migration, re-add the file "
            "provider (MDX_MASTER_KEY_PATH) as a fallback and finish the "
            "re-wrap (scripts/kms/rewrap-tenant-keks.py, ADR-0011)."
        )

    async def aclose(self) -> None:
        for member in self._members:
            close = getattr(member, "aclose", None)
            if callable(close):
                await close()


def build_master_key_provider(
    *,
    provider: str,
    file_path: str | os.PathLike[str] | None = None,
    vault_addr: str | None = None,
    vault_token: object | None = None,
    vault_transit_key: str = "mdx-master",
    vault_transit_mount: str = "transit",
) -> Any:
    """``file`` → :class:`FileMasterKeyProvider`; ``vault`` → KMS primary with the file provider as read-only
    fallback iff the key file exists. The result exposes ``startup_self_check``."""
    provider = provider.strip().lower()
    if provider == "file":
        if not file_path:
            raise MasterKeyError("MDX_MASTER_KEY_PROVIDER=file requires MDX_MASTER_KEY_PATH")
        return FileMasterKeyProvider(path=file_path)
    if provider == "vault":
        if not vault_addr:
            raise MasterKeyError("MDX_MASTER_KEY_PROVIDER=vault requires MDX_VAULT_ADDR")
        kms = KmsMasterKeyProvider(
            addr=vault_addr,
            token=vault_token,
            key_name=vault_transit_key,
            mount=vault_transit_mount,
        )
        fallbacks: tuple[Any, ...] = ()
        if file_path and Path(file_path).exists():
            fallbacks = (FileMasterKeyProvider(path=file_path),)
            logger.info(
                "master_key.file_fallback_active",
                extra={"path": str(file_path), "reason": "kms-migration-window"},
            )
        return CompositeMasterKeyProvider(primary=kms, fallbacks=fallbacks)
    raise MasterKeyError(
        f"unknown MDX_MASTER_KEY_PROVIDER {provider!r}; expected 'file' or 'vault'"
    )
