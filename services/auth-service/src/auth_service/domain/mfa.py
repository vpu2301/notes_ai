"""Pure second-factor decisions: recovery-code shape and hashing, TOTP step spending."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from enum import StrEnum

RECOVERY_CODE_COUNT = 10
_GROUP_LEN = 4
_GROUPS = 3

# Base32 minus O and I (confused with 0/1 when read aloud); 30^12 ≈ 58 bits.
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ234567"


class MfaMethod(StrEnum):
    TOTP = "totp"
    RECOVERY_CODE = "recovery_code"
    # Step-up for identities with no second factor: a mailed code.
    EMAIL_CODE = "email_code"


def generate_recovery_code() -> str:
    """``"K7NM-2QXF-9RTB"`` — three groups of four, hyphenated for reading."""
    body = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(_GROUP_LEN * _GROUPS))
    return "-".join(body[i : i + _GROUP_LEN] for i in range(0, len(body), _GROUP_LEN))


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """``count`` distinct codes (the store keys on ``(identity_id, code_hash)``)."""
    codes: set[str] = set()
    while len(codes) < count:
        codes.add(generate_recovery_code())
    return sorted(codes)


def normalise_recovery_code(raw: str) -> str:
    """What someone typed → the canonical form (accepts lower case, missing hyphens, spaces)."""
    kept = [ch for ch in (raw or "").upper() if ch in RECOVERY_ALPHABET]
    return "-".join("".join(kept[i : i + _GROUP_LEN]) for i in range(0, len(kept), _GROUP_LEN))


def recovery_code_hash(code: str) -> bytes:
    """sha256 of the canonical form. Only this ever reaches the database."""
    return hashlib.sha256(normalise_recovery_code(code).encode("ascii")).digest()


def recovery_hashes_match(stored: bytes, candidate: bytes) -> bool:
    return hmac.compare_digest(stored, candidate)


# ── TOTP step accounting ─────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class StepDecision:
    accepted: bool
    step: int | None
    reason: str = ""


def decide_step(matched_step: int | None, last_used_step: int | None) -> StepDecision:
    """A matched TOTP step is spendable only if strictly newer than the last one spent (drift window replay)."""
    if matched_step is None:
        return StepDecision(accepted=False, step=None, reason="code_invalid")
    if last_used_step is not None and matched_step <= last_used_step:
        return StepDecision(accepted=False, step=matched_step, reason="code_replayed")
    return StepDecision(accepted=True, step=matched_step)
