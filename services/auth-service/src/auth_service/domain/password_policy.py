"""Password strength per NIST SP 800-63B §5.1.1.2: length + blocklist, no composition rules, no expiry.

The bundled blocklist is deliberately small. Results are machine-readable codes;
the SPA renders the strings.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

MIN_LENGTH_FLOOR: Final = 8
MAX_LENGTH: Final = 128

# Reason codes, mirrored by the SPA's message table.
TOO_SHORT: Final = "too_short"
TOO_LONG: Final = "too_long"
COMMON: Final = "common"
CONTAINS_IDENTIFIER: Final = "contains_identifier"
REPEATED: Final = "repeated"
SEQUENTIAL: Final = "sequential"
WHITESPACE_ONLY: Final = "whitespace_only"

# Head of every credential-stuffing wordlist, casefolded; the check also de-leets.
_COMMON_PASSWORDS: Final[frozenset[str]] = frozenset(
    {
        "123456",
        "123456789",
        "12345678",
        "1234567890",
        "1234567",
        "password",
        "password1",
        "password123",
        "passwort",
        "пароль",
        "qwerty",
        "qwerty123",
        "qwertyuiop",
        "asdfghjkl",
        "zxcvbnm",
        "111111",
        "000000",
        "123123",
        "654321",
        "666666",
        "121212",
        "iloveyou",
        "admin",
        "administrator",
        "welcome",
        "welcome1",
        "monkey",
        "dragon",
        "sunshine",
        "princess",
        "football",
        "letmein",
        "abc123",
        "trustno1",
        "master",
        "shadow",
        "superman",
        "michael",
        "jennifer",
        "jordan",
        "hunter",
        "harley",
        "ranger",
        "changeme",
        "secret",
        "default",
        "root",
        "toor",
        "test",
        "test123",
        "notes-ai",
        "notesai",
        "dictation",
        "notes",
        "meeting",
        "office",
        "company",
        "business",
        "qwerty12345",
        "1q2w3e4r",
        "1qaz2wsx",
        "zaq12wsx",
        "q1w2e3r4t5",
        "passw0rd",
        "p@ssw0rd",
        "dev-password",
        "devpassword",
        "changeit",
        "temporary",
    }
)

_LEET: Final[dict[str, str]] = {
    "0": "o",
    "1": "l",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "@": "a",
    "$": "s",
    "!": "i",
    "|": "l",
}

# Runs long enough to be a pattern rather than a coincidence.
_SEQUENCES: Final[tuple[str, ...]] = (
    "abcdefghijklmnopqrstuvwxyz",
    "0123456789",
    "qwertyuiop",
    "asdfghjkl",
    "zxcvbnm",
    "йцукенгшщзхї",
    "фівапролджє",
    "ячсмитьбю",
)
_SEQUENCE_RUN: Final = 5


@dataclass(frozen=True, slots=True)
class PolicyResult:
    """Outcome of a strength check; ``score`` (0–4) is for the meter only, ``ok`` decides."""

    ok: bool
    reasons: tuple[str, ...]
    score: int


def _normalise(value: str) -> str:
    """NFKC + casefold (Keycloak normalises on its side, so full-width lookalikes must match)."""
    return unicodedata.normalize("NFKC", value).casefold()


def _deleet(value: str) -> str:
    return "".join(_LEET.get(ch, ch) for ch in value)


def _is_blocklisted(normalised: str) -> bool:
    """Known-bad password, possibly disguised? Padding is stripped from the ORIGINAL string, never the de-leeted one."""
    stripped = re.sub(r"^[\W\d_]+|[\W\d_]+$", "", normalised)
    candidates = {
        normalised,
        _deleet(normalised),
        stripped,
        _deleet(stripped),
    }
    return any(c and c in _COMMON_PASSWORDS for c in candidates)


def _identifier_fragments(*identifiers: str) -> list[str]:
    """Pieces of the user's identifiers (local part, dotted/hyphenated words, domain label); fragments under 4 chars dropped."""
    out: list[str] = []
    for raw in identifiers:
        if not raw:
            continue
        local = _normalise(raw).split("@", 1)[0]
        out.append(local)
        out.extend(re.split(r"[.\-_+\s]+", local))
        domain = _normalise(raw).split("@", 1)[1] if "@" in raw else ""
        if domain:
            out.extend(re.split(r"[.\-_]+", domain)[:1])
    return list({f for f in out if len(f) >= 4})


def _has_sequential_run(value: str) -> bool:
    lowered = _normalise(value)
    for seq in _SEQUENCES:
        reverse = seq[::-1]
        for start in range(len(seq) - _SEQUENCE_RUN + 1):
            window = seq[start : start + _SEQUENCE_RUN]
            if window in lowered or reverse[start : start + _SEQUENCE_RUN] in lowered:
                return True
    return False


def strength_score(password: str) -> int:
    """0–4, for the meter only. Never gates acceptance."""
    if not password:
        return 0
    length = len(password)
    variety = sum(
        (
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        )
    )
    score = 0
    if length >= 12:
        score += 1
    if length >= 16:
        score += 1
    if length >= 20:
        score += 1
    if variety >= 3:
        score += 1
    # Cap rather than reward character mixture on its own.
    if length < 12:
        return 0
    return min(score, 4)


def check_password(
    password: str,
    *,
    min_length: int = 12,
    email: str = "",
    display_name: str = "",
) -> PolicyResult:
    """Evaluate a candidate password; ``min_length`` is floored at :data:`MIN_LENGTH_FLOOR`."""
    floor = max(int(min_length), MIN_LENGTH_FLOOR)
    reasons: list[str] = []

    if not password.strip():
        # Before the length check so an all-spaces string gets the specific message.
        return PolicyResult(ok=False, reasons=(WHITESPACE_ONLY,), score=0)

    if len(password) < floor:
        reasons.append(TOO_SHORT)
    if len(password) > MAX_LENGTH:
        # DoS guard for the KDF, not a security control.
        reasons.append(TOO_LONG)

    normalised = _normalise(password)
    if _is_blocklisted(normalised):
        reasons.append(COMMON)

    fragments = _identifier_fragments(email, display_name)
    if any(f in normalised for f in fragments):
        reasons.append(CONTAINS_IDENTIFIER)

    if len(set(password)) <= 2 and len(password) >= 4:
        reasons.append(REPEATED)

    if _has_sequential_run(password):
        reasons.append(SEQUENTIAL)

    ok = not reasons
    return PolicyResult(
        ok=ok,
        reasons=tuple(dict.fromkeys(reasons)),
        score=strength_score(password) if ok else 0,
    )
