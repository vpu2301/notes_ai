"""``S3Client`` with no endpoint configured.

A service may run with ``S3_ENDPOINT`` empty (no object store in the stack).
Every call must then fail with :class:`ObjectStoreNotConfiguredError` — not
with aiobotocore's ``ValueError: Invalid endpoint:`` raised lazily inside a
request, which the services rendered as an opaque 500.
"""

from __future__ import annotations

import pytest

from storage import ObjectStoreNotConfiguredError, S3Client


async def test_empty_endpoint_fails_as_not_configured() -> None:
    client = S3Client(endpoint_url="", access_key="", secret_key="")
    with pytest.raises(ObjectStoreNotConfiguredError):
        await client.get_object(bucket="mdx-transcripts", key="tenant/job.json.enc")
    with pytest.raises(ObjectStoreNotConfiguredError):
        await client.put_object(bucket="mdx-audio", key="tenant/audio.enc", body=b"x")
    with pytest.raises(ObjectStoreNotConfiguredError):
        await client.head_bucket("mdx-transcripts")
    with pytest.raises(ObjectStoreNotConfiguredError):
        await client.generate_presigned_url(bucket="mdx-transcripts", key="k", expires_in=60)
