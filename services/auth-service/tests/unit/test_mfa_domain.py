"""IDX-A5 — the second-factor logic that needs no database.

Recovery-code shape and single-use hashing, the TOTP replay rule, IP
masking, and the revert-token round trip. Each of these is a security
property stated as arithmetic, which is exactly the kind of thing that
should be provable without a Postgres.
"""

from __future__ import annotations

import ipaddress
from uuid import uuid4

import pytest

from auth_service import totp
from auth_service.domain import mfa
from auth_service.domain.account_service import (
    mask_ip,
    parse_revert_token,
    revert_token,
)
from auth_service.domain.compose import mask_email

# ── recovery codes ───────────────────────────────────────────────────────


def test_a_recovery_code_avoids_the_characters_people_misread() -> None:
    code = mfa.generate_recovery_code()
    assert len(code) == 14  # xxxx-xxxx-xxxx
    assert code.count("-") == 2
    body = code.replace("-", "")
    assert set(body) <= set(mfa.RECOVERY_ALPHABET)
    # The whole point of the alphabet: no O/0 or I/1 confusion when the
    # code is read off paper or dictated over a phone.
    assert not (set(body) & set("OI01"))


def test_a_set_of_codes_is_distinct() -> None:
    codes = mfa.generate_recovery_codes()
    assert len(codes) == mfa.RECOVERY_CODE_COUNT == 10
    assert len(set(codes)) == 10


def test_codes_are_unguessable_between_sets() -> None:
    first = set(mfa.generate_recovery_codes())
    second = set(mfa.generate_recovery_codes())
    assert not (first & second)


def test_the_alphabet_is_base32_minus_the_confusable_letters() -> None:
    """Base32 has no 0, 1, 8 or 9 to begin with; O and I are what get
    dropped. Pinned because the set is what makes a dictated code work."""
    assert set(mfa.RECOVERY_ALPHABET) == set("ABCDEFGHJKLMNPQRSTUVWXYZ") | set("234567")
    assert not (set(mfa.RECOVERY_ALPHABET) & set("OI0189"))


@pytest.mark.parametrize(
    "typed",
    ["K7NM-2QXF-4RTB", "k7nm2qxf4rtb", "K7NM 2QXF 4RTB", "  k7nm-2qxf-4rtb  "],
)
def test_a_code_is_accepted_however_a_person_types_it(typed: str) -> None:
    """It was printed for a human and comes back from a human — often on
    the worst day of their week, having just lost their phone."""
    assert mfa.normalise_recovery_code(typed) == "K7NM-2QXF-4RTB"
    assert mfa.recovery_code_hash(typed) == mfa.recovery_code_hash("K7NM-2QXF-4RTB")


def test_a_character_outside_the_alphabet_is_dropped_so_the_code_cannot_match() -> None:
    """Anything not in the alphabet is discarded, separators included.

    A real code is always twelve alphabet characters, so a submission
    containing a stray one comes out short and matches nothing that was
    ever issued. That also means the two characters the alphabet exists to
    avoid — O/0 — normalise identically: neither can appear in a genuine
    code, so collapsing them costs nothing and spares the user a failed
    attempt for reading a letter as a digit.
    """
    issued = mfa.generate_recovery_code()
    assert len(mfa.normalise_recovery_code(issued).replace("-", "")) == 12
    assert len(mfa.normalise_recovery_code("K7NM-2QXF-4RT0").replace("-", "")) == 11
    assert mfa.recovery_code_hash("K7NM-2QXF-4RT0") == mfa.recovery_code_hash("K7NM-2QXF-4RTO")


def test_hashing_is_what_reaches_the_database() -> None:
    code = mfa.generate_recovery_code()
    digest = mfa.recovery_code_hash(code)
    assert len(digest) == 32
    assert code.encode() not in digest
    assert mfa.recovery_hashes_match(digest, mfa.recovery_code_hash(code))
    assert not mfa.recovery_hashes_match(digest, mfa.recovery_code_hash("AAAA-BBBB-CCCC"))


# ── TOTP replay ──────────────────────────────────────────────────────────


def test_a_code_matches_the_step_it_was_generated_for() -> None:
    secret = totp.generate_secret()
    at = 1_800_000_000.0
    code = totp.totp_at(secret, at_unix=at)
    step = totp.matching_step(secret, code, at_unix=at)
    assert step == int(at // totp.TOTP_PERIOD_SECONDS)


def test_the_drift_window_still_matches_but_reports_the_older_step() -> None:
    """A code from the previous window is accepted, and charged to ITS step —
    which is what stops it being re-spent once the clock moves on."""
    secret = totp.generate_secret()
    at = 1_800_000_000.0
    previous = totp.totp_at(secret, at_unix=at - totp.TOTP_PERIOD_SECONDS)
    step = totp.matching_step(secret, previous, at_unix=at)
    assert step == int(at // totp.TOTP_PERIOD_SECONDS) - 1


def test_a_wrong_or_malformed_code_matches_nothing() -> None:
    secret = totp.generate_secret()
    assert totp.matching_step(secret, "abcdef") is None
    assert totp.matching_step(secret, "12345") is None
    assert totp.matching_step(secret, "") is None


def test_the_same_step_cannot_be_spent_twice() -> None:
    """The drift window keeps one code valid for up to 90 seconds. Without
    step accounting the same six digits authenticate three times."""
    first = mfa.decide_step(matched_step=100, last_used_step=None)
    assert first.accepted and first.step == 100

    replay = mfa.decide_step(matched_step=100, last_used_step=100)
    assert not replay.accepted
    assert replay.reason == "code_replayed"

    older = mfa.decide_step(matched_step=99, last_used_step=100)
    assert not older.accepted

    newer = mfa.decide_step(matched_step=101, last_used_step=100)
    assert newer.accepted


def test_a_code_that_matched_nothing_is_not_a_replay() -> None:
    decision = mfa.decide_step(matched_step=None, last_used_step=100)
    assert not decision.accepted
    assert decision.reason == "code_invalid"


# ── masking ──────────────────────────────────────────────────────────────


def test_an_ipv4_address_is_shown_as_its_network() -> None:
    assert mask_ip("203.0.113.7") == "203.0.113.0/24"


def test_an_ipv6_address_is_shown_as_a_48() -> None:
    masked = mask_ip("2001:db8:1234:5678::1")
    assert masked.endswith("/48")
    assert ipaddress.ip_address("2001:db8:1234:5678::1") in ipaddress.ip_network(masked)


def test_an_unparsable_address_masks_to_nothing_rather_than_leaking_it() -> None:
    assert mask_ip("not-an-ip") == ""
    assert mask_ip("") == ""


def test_the_new_address_is_masked_in_the_notice_to_the_old_one() -> None:
    """The reader may not be the person who made the change."""
    assert mask_email("ada.lovelace@example.com") == "a***e@example.com"
    assert "lovelace" not in mask_email("ada.lovelace@example.com")


# ── revert token ─────────────────────────────────────────────────────────


def test_the_revert_token_round_trips() -> None:
    challenge_id = uuid4()
    token = revert_token(challenge_id, "s3cr3t-value")
    assert parse_revert_token(token) == (challenge_id, "s3cr3t-value")


@pytest.mark.parametrize("bad", ["", "nonsense", "no-dot-here", ".missing-id", "zzz.secret"])
def test_a_malformed_revert_token_is_rejected_not_guessed(bad: str) -> None:
    assert parse_revert_token(bad) is None
