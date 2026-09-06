"""Second-factor decisions that need no database (IDX-A5).

Recovery-code shape and hashing, and the rule that decides whether a TOTP
step may be spent. Everything here is pure, so the properties that matter
— a code is single-use, a time step is never re-spent, a printed code is
readable back over a phone line — are unit-testable without Postgres, an
envelope, or a clock.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from enum import StrEnum

RECOVERY_CODE_COUNT = 10
_GROUP_LEN = 4
_GROUPS = 3

# Base32's alphabet minus the four characters people confuse when reading a
# code off paper or dictating it: O/0 and I/1. (0 and 1 are not in RFC 4648
# base32 to begin with, so removing O and I is what actually does the work.)
# 30 symbols × 12 characters ≈ 58 bits — well past guessable, and the codes
# are rate-limited and single-use besides.
RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ234567"


class MfaMethod(StrEnum):
    TOTP = "totp"
    RECOVERY_CODE = "recovery_code"
    # IDX-A5's step-up for identities with no second factor and (until
    # IDX-A4) no password: a code mailed to the address on the account.
    EMAIL_CODE = "email_code"


def generate_recovery_code() -> str:
    """``"K7NM-2QXF-9RTB"`` — three groups of four, hyphenated for reading."""
    body = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(_GROUP_LEN * _GROUPS))
    return "-".join(body[i : i + _GROUP_LEN] for i in range(0, len(body), _GROUP_LEN))


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """``count`` distinct codes.

    Distinct because the store keys on ``(identity_id, code_hash)``: a
    duplicate would make "mark this one used" ambiguous, and would quietly
    give the user nine codes while telling them they have ten.
    """
    codes: set[str] = set()
    while len(codes) < count:
        codes.add(generate_recovery_code())
    return sorted(codes)


def normalise_recovery_code(raw: str) -> str:
    """What someone typed → the canonical form.

    Accepts lower case, missing hyphens, and spaces, because the code was
    printed for a human and will come back from a human — often at the
    worst moment of their week, having just lost their phone.
    """
    kept = [ch for ch in (raw or "").upper() if ch in RECOVERY_ALPHABET]
    return "-".join("".join(kept[i : i + _GROUP_LEN]) for i in range(0, len(kept), _GROUP_LEN))


def recovery_code_hash(code: str) -> bytes:
    """sha256 of the canonical form. Only this ever reaches the database."""
    return hashlib.sha256(normalise_recovery_code(code).encode("ascii")).digest()


def recovery_hashes_match(stored: bytes, candidate: bytes) -> bool:
    return hmac.compare_digest(stored, candidate)


# ── TOTP step accounting (F3) ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class StepDecision:
    accepted: bool
    step: int | None
    reason: str = ""


def decide_step(matched_step: int | None, last_used_step: int | None) -> StepDecision:
    """Whether a matched TOTP step may be spent.

    The drift window makes one code valid across three steps, which without
    this check means the same six digits authenticate up to three times. A
    step is spendable only if it is strictly newer than the last one spent,
    so a replayed code is refused even while it is still "valid".
    """
    if matched_step is None:
        return StepDecision(accepted=False, step=None, reason="code_invalid")
    if last_used_step is not None and matched_step <= last_used_step:
        return StepDecision(accepted=False, step=matched_step, reason="code_replayed")
    return StepDecision(accepted=True, step=matched_step)
