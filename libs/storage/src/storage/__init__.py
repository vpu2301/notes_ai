"""Encrypted object I/O: ``EncryptedObjectStore`` is the only sanctioned path; no plaintext method by design."""

from __future__ import annotations

from .object_store import (
    EncryptedObjectStore,
    ObjectHeader,
    ObjectStoreDisabledError,
)
from .s3_client import ObjectNotFoundError, ObjectStoreNotConfiguredError, S3Client

__all__ = [
    "EncryptedObjectStore",
    "ObjectHeader",
    "ObjectNotFoundError",
    "ObjectStoreDisabledError",
    "ObjectStoreNotConfiguredError",
    "S3Client",
]
