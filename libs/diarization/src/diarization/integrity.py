"""Startup re-check of the baked diarization weights against the build-time digests (docs/models/PINS.md). Fail-closed."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

VERIFIED_ARTIFACTS: tuple[str, ...] = ("embedding_model.ckpt", "mean_var_norm_emb.ckpt")


class ModelIntegrityError(Exception):
    """A baked model artifact does not match its pinned digest."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_model_dir(
    model_dir: str | Path,
    *,
    pins: dict[str, str],
    repo: str = "",
    revision: str = "",
    required_files: tuple[str, ...] = ("hyperparams.yaml",),
) -> dict[str, str]:
    """Verify each pinned artifact under ``model_dir``; returns artifact -> actual digest.

    An empty digest in ``pins`` = UNPINNED (dev path): presence required, content only logged with a warning.
    ``required_files`` are the repo-owned configs whose absence would send the loader to the network.
    """
    root = Path(model_dir)
    if not root.is_dir():
        raise ModelIntegrityError(
            f"diarization model dir not found: {root} "
            "(image should bake it at /opt/models/ecapa; dev: `make prepare-ecapa`)"
        )

    actual: dict[str, str] = {}
    unpinned: list[str] = []
    t0 = time.monotonic()
    for name, expected in pins.items():
        path = root / name
        if not path.is_file():
            raise ModelIntegrityError(f"missing diarization artifact: {path}")
        got = sha256_file(path)
        actual[name] = got
        if not expected:
            unpinned.append(name)
            continue
        if got != expected:
            raise ModelIntegrityError(
                f"checksum mismatch for {path}: expected {expected}, got {got}. "
                "Refusing to start (fail-closed, docs/models/PINS.md)."
            )

    # Without the repo-owned config the loader would resolve the model over the network (ADR-0034, ADR-0052).
    for required in required_files:
        if not (root / required).is_file():
            raise ModelIntegrityError(
                f"missing {root / required} — without the repo-owned config the "
                "loader re-resolves the model over the network (ADR-0034, ADR-0052)."
            )

    elapsed_ms = (time.monotonic() - t0) * 1000
    if unpinned:
        logger.warning(
            "diarization.model_unpinned",
            extra={
                "model_dir": str(root),
                "unpinned_artifacts": ",".join(unpinned),
                "detail": "no digest configured; verified presence only. "
                "Shipped images set MDX_DIAR_MODEL_SHA256 / MDX_DIAR_MEANVAR_SHA256.",
            },
        )
    logger.info(
        "diarization.model_verified",
        extra={
            "model_dir": str(root),
            "model_repo": repo or "(unset)",
            "model_revision": revision or "(unpinned)",
            "artifacts": ",".join(f"{k}={v[:12]}" for k, v in actual.items()),
            "verify_ms": round(elapsed_ms, 1),
        },
    )
    return actual
