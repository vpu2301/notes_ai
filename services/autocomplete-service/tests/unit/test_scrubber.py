"""PII scrubber regex coverage — the privacy surface."""

from __future__ import annotations

from autocomplete_service.scrubber import REDACTED, contains_pii, scrub_prefix


def test_email_redacted():
    out = scrub_prefix("contact me at vlad@example.org now")
    assert "vlad@example.org" not in out.text
    assert REDACTED in out.text
    assert out.redactions["email"] == 1


def test_card_like_grouped_redacted():
    out = scrub_prefix("card 4111 1111 1111 1111 on file")
    assert "4111 1111 1111 1111" not in out.text
    assert out.redactions["card_like"] == 1


def test_card_like_contiguous_redacted():
    out = scrub_prefix("pan 4111111111111111 saved")
    assert "4111111111111111" not in out.text
    assert out.redactions["card_like"] == 1


def test_national_id_redacted():
    out = scrub_prefix("ID AB 123456 on record")
    assert "AB 123456" not in out.text
    assert out.redactions["national_id"] == 1


def test_national_id_no_space_redacted():
    out = scrub_prefix("passport AB123456 on file")
    assert "AB123456" not in out.text
    assert out.redactions.get("national_id") == 1


def test_intl_phone_redacted():
    out = scrub_prefix("reach me at +380501234567 in the morning")
    assert "380501234567" not in out.text
    assert out.redactions["phone"] == 1


def test_separated_phone_redacted():
    # Digit groups broken by spaces used to be a documented gap — the
    # generic scrubber closes it.
    out = scrub_prefix("call 050 123 45 67 after 9")
    assert "050 123 45 67" not in out.text
    assert out.redactions["phone"] == 1


def test_parenthesised_phone_redacted():
    out = scrub_prefix("office (044) 123-45-67 desk")
    assert "123-45-67" not in out.text


def test_long_digit_runs_redacted():
    # Unformatted phones / tax numbers / account numbers of any length.
    for run in ("0501234567", "38050123456", "1234567890123"):
        out = scrub_prefix(f"number {run} in file")
        assert run not in out.text, f"leaked: {run}"


def test_digit_run_counted():
    out = scrub_prefix("account 123456789012345678901 ok")
    assert out.redactions.get("digit_run", 0) + out.redactions.get("card_like", 0) >= 1
    assert "123456789012345678901" not in out.text


def test_safe_text_unchanged():
    safe = "action items from the quarterly planning meeting"
    out = scrub_prefix(safe)
    assert out.text == safe
    assert out.redactions == {}


def test_short_numbers_not_scrubbed():
    safe = "revenue grew 12% in Q3, meeting at 10 30 tomorrow"
    out = scrub_prefix(safe)
    assert out.text == safe


def test_contains_pii_detects_email():
    assert "email" in contains_pii("vlad@example.org")


def test_contains_pii_clean_returns_empty():
    assert contains_pii("nothing sensitive here") == []


def test_scrub_corpus_completeness():
    """Representative PII fixtures must be 100% scrubbed."""
    cases = [
        "send to a@b.c",
        "ID AB 123456",
        "phone 0501234567",
        "card 4111 1111 1111 1111",
        "national id 1234567890123",
        "email john.doe+tag@example.co.uk",
        "mobile +380501234567",
        "tel 380501234567",
        "call 050 123 45 67",
    ]
    for c in cases:
        out = scrub_prefix(c)
        assert REDACTED in out.text, f"PII not scrubbed: {c!r}"
