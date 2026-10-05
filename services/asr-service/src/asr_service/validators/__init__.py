"""8-step upload validation: auth, mime, magic_bytes, size, duration, codec, hash, quota.

``run_all`` short-circuits at the first failure; failures are RFC 9457 problems.
"""

from .codec import validate_codec
from .duration import validate_duration
from .hash import compute_hash
from .magic_bytes import validate_magic_bytes
from .mime import normalize_mime, validate_mime
from .quota import validate_quota
from .result import UploadFacts, ValidationCode, ValidationResult, ok, reject
from .runner import run_all
from .size import validate_size

__all__ = [
    "UploadFacts",
    "ValidationCode",
    "ValidationResult",
    "compute_hash",
    "ok",
    "reject",
    "run_all",
    "validate_codec",
    "validate_duration",
    "validate_magic_bytes",
    "normalize_mime",
    "validate_mime",
    "validate_quota",
    "validate_size",
]
