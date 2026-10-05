"""Async S3 adapter: the only place ``aioboto3`` is imported (CI greps for it)."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

# Importable without aioboto3 installed (test rigs use an in-memory S3 substitute).
try:  # pragma: no cover  — import-time guard
    import aioboto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover
    aioboto3 = None  # type: ignore[assignment]
    ClientError = Exception  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)


class ObjectNotFoundError(Exception):
    """The key does not exist in the bucket; raised instead of leaking ``botocore.ClientError``."""

    def __init__(self, *, bucket: str, key: str) -> None:
        self.bucket = bucket
        self.key = key
        super().__init__(f"object not found: s3://{bucket}/{key}")


class ObjectStoreNotConfiguredError(RuntimeError):
    """``S3_ENDPOINT`` is empty: a recognisable dependency error instead of aiobotocore's opaque ``Invalid endpoint``."""

    def __init__(self) -> None:
        super().__init__("object store is not configured (S3_ENDPOINT is empty)")


class S3Client:
    """aioboto3 session with a per-call client context; narrow methods so callers cannot bypass the envelope."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        use_ssl: bool = False,
    ) -> None:
        self._endpoint = endpoint_url
        self._access = access_key
        self._secret = secret_key
        self._region = region
        self._use_ssl = use_ssl
        if aioboto3 is None:
            raise RuntimeError(
                "aioboto3 is not installed; S3Client cannot be constructed. "
                "Install via `uv sync` or use a mock S3 in tests."
            )
        self._session = aioboto3.Session()

    def _client(self) -> Any:
        if not self._endpoint:
            raise ObjectStoreNotConfiguredError
        return self._session.client(
            "s3",
            endpoint_url=self._endpoint,
            aws_access_key_id=self._access,
            aws_secret_access_key=self._secret,
            region_name=self._region,
            use_ssl=self._use_ssl,
        )

    async def put_object(self, *, bucket: str, key: str, body: bytes) -> None:
        async with self._client() as c:
            await c.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentType="application/octet-stream",
            )

    async def get_object(self, *, bucket: str, key: str) -> bytes:
        async with self._client() as c:
            try:
                resp = await c.get_object(Bucket=bucket, Key=key)
            except ClientError as exc:
                # getattr: the import-guard fallback aliases ClientError to Exception.
                code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
                if code in ("NoSuchKey", "404"):
                    raise ObjectNotFoundError(bucket=bucket, key=key) from exc
                raise
            body = resp["Body"]
            return await body.read()

    async def delete_object(self, *, bucket: str, key: str) -> None:
        async with self._client() as c:
            with contextlib.suppress(ClientError):
                await c.delete_object(Bucket=bucket, Key=key)

    async def object_exists(self, *, bucket: str, key: str) -> bool:
        """HEAD the object: True if it exists, False on 404. Other errors raise."""
        async with self._client() as c:
            try:
                await c.head_object(Bucket=bucket, Key=key)
            except ClientError as exc:
                code = str(exc.response.get("Error", {}).get("Code", ""))
                if code in {"404", "NoSuchKey", "NotFound"}:
                    return False
                raise
        return True

    async def head_bucket(self, bucket: str) -> None:
        """Probe used by readiness checks."""
        async with self._client() as c:
            await c.head_bucket(Bucket=bucket)

    async def generate_presigned_url(self, *, bucket: str, key: str, expires_in: int) -> str:
        async with self._client() as c:
            url: str = await c.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )
            return url

    async def aclose(self) -> None:
        # aioboto3 Session has no explicit close; kept for teardown symmetry.
        return None
