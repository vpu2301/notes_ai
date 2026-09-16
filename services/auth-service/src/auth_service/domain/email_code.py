"""Email one-time-code sign-in — the parts that need no database (IDX-A3).

What lives here:

* code generation and the challenge-bound hash (F1);
* the verify state machine as a pure function over a :class:`Challenge`
  snapshot — expired / consumed / exhausted / wrong / right — so the
  branch logic is unit-tested without Postgres;
* lockout arithmetic (F5): when a failure count trips the lock and for how
  long, doubling per lock up to a cap;
* the personal-workspace naming rule (F3).

What does not live here: reading and writing ``auth_challenges`` and
``identities`` rows. That is :class:`ChallengeStore`, a Protocol the A1
tables implement; the route handler composes the two.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

CODE_DIGITS = 6
KIND_EMAIL_LOGIN = "email_login"

# Local-part characters allowed to survive into a workspace *name* (the
# unique key). Everything else collapses to "-".
_NAME_UNSAFE = re.compile(r"[^a-z0-9._-]+")


def generate_code() -> str:
    """Six decimal digits from ``secrets``; leading zeros kept (``"004821"``)."""
    return f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


def normalise_code(raw: str) -> str:
    """What a person typed → the digits (``"482 913"`` → ``"482913"``)."""
    return "".join(ch for ch in (raw or "") if ch.isdigit())


def code_hash(code: str, challenge_id: UUID) -> str:
    """``sha256("<code>:<challenge_id>")`` hex — a leaked hash fits one challenge only."""
    return hashlib.sha256(f"{code}:{challenge_id}".encode("ascii")).hexdigest()


def hashes_match(stored_hex: str, candidate_hex: str) -> bool:
    return hmac.compare_digest(stored_hex.encode("ascii"), candidate_hex.encode("ascii"))


def normalise_email(raw: str) -> str:
    """Lower-cased, trimmed. The rate-limit subject and the identity lookup key."""
    return (raw or "").strip().lower()


def email_subject_hash(email: str) -> str:
    """The per-email rate-limit subject: never the address itself (F4)."""
    return hashlib.sha256(normalise_email(email).encode("utf-8")).hexdigest()[:32]


# ── verify state machine ─────────────────────────────────────────────────


class VerifyOutcome(StrEnum):
    OK = "ok"
    INVALID = "invalid"  # wrong code, attempts left
    EXHAUSTED = "exhausted"  # this attempt spent the last try → consume
    EXPIRED = "expired"
    CONSUMED = "consumed"  # already used or superseded


@dataclass(frozen=True, slots=True)
class Challenge:
    """A snapshot of one ``auth_challenges`` row."""

    id: UUID
    kind: str
    email: str
    identity_id: UUID | None
    code_hash: str
    expires_at: datetime
    attempts: int
    max_attempts: int
    consumed_at: datetime | None
    created_at: datetime
    # Flow context (IDX-A5): the first factor's client type for an
    # `mfa_login` row, the address being replaced for `email_change`.
    # Never a secret — codes live in `code_hash`, TOTP secrets in
    # `identity_totp.secret_enc`.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VerifyDecision:
    outcome: VerifyOutcome
    attempts_after: int
    attempts_left: int
    consume: bool
    """Whether the row must be marked consumed as part of this attempt."""


def evaluate(
    challenge: Challenge, submitted_code: str, *, now: datetime | None = None
) -> VerifyDecision:
    """Decide what one submission does to a challenge. Pure; the caller persists.

    Order matters: a consumed or expired challenge never learns whether the
    code was right (no oracle on dead challenges), and the attempt that
    exhausts the budget is refused as ``exhausted`` even when it would have
    matched — five wrong guesses buy nothing, not a sixth try.
    """
    now = now or datetime.now(UTC)
    if challenge.consumed_at is not None:
        return VerifyDecision(VerifyOutcome.CONSUMED, challenge.attempts, 0, consume=False)
    if now >= challenge.expires_at:
        return VerifyDecision(VerifyOutcome.EXPIRED, challenge.attempts, 0, consume=False)
    if challenge.attempts >= challenge.max_attempts:
        return VerifyDecision(VerifyOutcome.EXHAUSTED, challenge.attempts, 0, consume=True)

    candidate = code_hash(normalise_code(submitted_code), challenge.id)
    if hashes_match(challenge.code_hash, candidate):
        return VerifyDecision(VerifyOutcome.OK, challenge.attempts, 0, consume=True)

    attempts_after = challenge.attempts + 1
    left = challenge.max_attempts - attempts_after
    if left <= 0:
        return VerifyDecision(VerifyOutcome.EXHAUSTED, attempts_after, 0, consume=True)
    return VerifyDecision(VerifyOutcome.INVALID, attempts_after, left, consume=False)


def resend_allowed_at(created_at: datetime, *, cooldown_seconds: int) -> datetime:
    """DB-side half of the ``otp_cooldown`` rule (the Redis half may be down)."""
    return created_at + timedelta(seconds=cooldown_seconds)


# ── lockout (F5) ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class LockoutPolicy:
    threshold: int = 10
    base_seconds: int = 900
    max_seconds: int = 3600

    def lock_duration(self, previous_locks: int) -> timedelta:
        """15 min, doubling per subsequent lock, capped (900 → 1800 → 3600 → 3600…)."""
        seconds = min(self.base_seconds * (2 ** max(0, previous_locks)), self.max_seconds)
        return timedelta(seconds=seconds)

    def after_failure(
        self, *, failed_count: int, previous_locks: int, now: datetime
    ) -> tuple[int, datetime | None]:
        """New ``(failed_login_count, locked_until)`` after one more failure."""
        failed_count += 1
        if failed_count >= self.threshold:
            return 0, now + self.lock_duration(previous_locks)
        return failed_count, None


def is_locked(locked_until: datetime | None, *, now: datetime | None = None) -> bool:
    return locked_until is not None and (now or datetime.now(UTC)) < locked_until


# ── personal workspace (F3) ──────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class WorkspaceNames:
    name: str
    display_name: str
    slug: str


def personal_workspace_names(email: str, *, slug_hex: str | None = None) -> WorkspaceNames:
    """``ada.l@example.com`` → name ``ada.l``, display ``ada.l's workspace``, slug ``ws-<8 hex>``.

    ``name`` is UNIQUE on ``tenants``; the caller appends ``-<n>`` on
    collision. ``slug_hex`` is injectable so tests are deterministic.
    """
    local = normalise_email(email).split("@", 1)[0] or "me"
    name = _NAME_UNSAFE.sub("-", local).strip("-.") or "me"
    hex8 = (slug_hex or secrets.token_hex(4))[:8]
    return WorkspaceNames(name=name[:60], display_name=f"{local}'s workspace", slug=f"ws-{hex8}")


# ── the store the A1 tables implement ───────────────────────────────────


class ChallengeStore(Protocol):
    """Persistence for ``auth_challenges`` (IDX-A1). Every method is one statement
    or one transaction on the ``tenant_writer`` pool."""

    async def open(
        self,
        *,
        challenge_id: UUID,
        kind: str,
        email: str,
        identity_id: UUID | None,
        code_hash: str,
        expires_at: datetime,
        max_attempts: int,
        client_type: str,
        ip: str,
        metadata: dict[str, Any] | None = None,
    ) -> Challenge:
        """Insert a challenge under an id the CALLER chose.

        The id is an input rather than an output because ``code_hash`` is
        bound to it: generating it here would mean inserting a row with a
        placeholder hash and updating it a moment later, and a row that is
        briefly live with an unusable code is a row a concurrent start can
        supersede or a verify can hit.
        """
        ...

    async def consume_open_for_email(self, *, kind: str, email: str) -> int:
        """Supersede every open challenge of this kind for the email; returns how many."""
        ...

    async def latest_open_for_email(self, *, kind: str, email: str) -> Challenge | None:
        """The newest unconsumed challenge for the address — the resend cooldown's
        authority when Redis is unavailable (F4, ``otp_cooldown``)."""
        ...

    async def get(self, challenge_id: UUID) -> Challenge | None: ...

    async def record_attempt(self, challenge_id: UUID, *, attempts: int) -> None: ...

    async def consume(self, challenge_id: UUID) -> bool:
        """``UPDATE … SET consumed_at = now() WHERE id = $1 AND consumed_at IS NULL``;
        False when someone else consumed it first (double submit)."""
        ...

    async def delete(self, challenge_id: UUID) -> None:
        """Drop a challenge whose code could not be delivered (no dangling code)."""
        ...
