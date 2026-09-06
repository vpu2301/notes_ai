"""Rendering and MIME assembly for the two account-security mails.

The parametrised render test is the important one: it proves every
kind × language combination produces a mail with no unsubstituted
variables and no leftover sample text, which is the failure that only
ever shows up in somebody's inbox.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from auth_service.adapters import email as email_mod
from auth_service.adapters import templates
from auth_service.domain import compose
from auth_service.domain import copy as copy_mod

APP = "https://app.notes-ai.local"
SUPPORT = "https://notes-ai.local/contact"
WHEN = datetime(2026, 8, 9, 14, 30, tzinfo=UTC)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120.0 Safari/537.36"
TOKEN = "tok-ABCDEF0123456789"


def _fields(kind: str, lang: str) -> tuple[dict, dict]:
    # IDX-A5 notices. Each is listed explicitly rather than defaulted, so
    # adding a kind without teaching this helper fails the render gate
    # instead of quietly rendering somebody else's variables.
    if kind == copy_mod.KIND_MFA_ENABLED:
        return compose.mfa_enabled_fields(lang=lang, changed_at=WHEN), {}
    if kind == copy_mod.KIND_MFA_DISABLED:
        return (
            compose.mfa_disabled_fields(lang=lang, changed_at=WHEN, by_admin=True),
            {},
        )
    if kind == copy_mod.KIND_RECOVERY_CODE_USED:
        return (
            compose.recovery_code_used_fields(lang=lang, remaining=4, used_at=WHEN),
            {},
        )
    if kind == copy_mod.KIND_EMAIL_CHANGED:
        return (
            compose.email_changed_fields(
                lang=lang,
                new_email="new-address@acme.example",
                revert_url=f"{APP}/auth/email/revert/{TOKEN}",
                revert_ttl_seconds=86400,
                changed_at=WHEN,
            ),
            {},
        )
    if kind == copy_mod.KIND_ACCOUNT_DELETION:
        return (
            compose.account_deletion_fields(lang=lang, purge_on=WHEN, requested_at=WHEN),
            {},
        )
    if kind == copy_mod.KIND_AUTH_CODE:
        return (
            compose.auth_code_fields(
                lang=lang, code="482913", ttl_seconds=600, user_agent=UA, requested_at=WHEN
            ),
            {},
        )
    if kind == copy_mod.KIND_AUTH_LOCKED:
        return compose.auth_locked_fields(lang=lang, locked_until=WHEN), {}
    if kind == copy_mod.KIND_SIGNUP_VERIFY:
        return (
            compose.signup_verify_fields(
                lang=lang, code="482913", ttl_seconds=600, user_agent=UA, requested_at=WHEN
            ),
            {},
        )
    if kind == copy_mod.KIND_CONCIERGE_WELCOME:
        return (
            compose.concierge_welcome_fields(
                lang=lang,
                display_name="Olena",
                temporary_password=TOKEN,
                app_base_url=APP,
                created_at=WHEN,
            ),
            {},
        )
    if kind == copy_mod.KIND_SIGNUP_EXISTS:
        return (
            compose.signup_exists_fields(
                lang=lang, app_base_url=APP, user_agent=UA, requested_at=WHEN
            ),
            {},
        )
    if kind == copy_mod.KIND_PASSWORD_RESET:
        return (
            compose.password_reset_fields(
                lang=lang,
                email="olena@acme.example",
                display_name="Olena",
                user_agent=UA,
                support_url=SUPPORT,
                app_base_url=APP,
                requested_at=WHEN,
                ttl_seconds=1800,
            ),
            compose.reset_secret_fields(app_base_url=APP, token=TOKEN),
        )
    return (
        compose.password_changed_fields(
            lang=lang,
            email="olena@acme.example",
            display_name="Olena",
            user_agent=UA,
            support_url=SUPPORT,
            app_base_url=APP,
            changed_at=WHEN,
            lockdown_ttl_seconds=604800,
        ),
        compose.lockdown_secret_fields(app_base_url=APP, token=TOKEN),
    )


def _render(kind: str, lang: str) -> templates.RenderedEmail:
    fields, secrets = _fields(kind, lang)
    return templates.render(
        kind,
        lang,
        subject=copy_mod.subject_for(kind, lang),
        text_body=copy_mod.text_body(kind, lang, compose.text_values(kind, lang, fields, secrets)),
        context={**fields, **secrets},
    )


@pytest.mark.parametrize("kind", copy_mod.KINDS)
@pytest.mark.parametrize("lang", copy_mod.SUPPORTED_LANGS)
def test_every_kind_and_language_renders(kind: str, lang: str) -> None:
    rendered = _render(kind, lang)
    assert rendered.subject
    assert "\n" not in rendered.subject  # header-injection guard
    assert rendered.html_body.startswith("<!doctype html>")
    assert rendered.text_body
    # No unsubstituted Jinja or str.format placeholders survived.
    assert "{{" not in rendered.html_body
    assert "}}" not in rendered.html_body
    assert "{" not in rendered.text_body


def _expected_link(kind: str) -> str:
    """What THIS kind's link must contain.

    Most link mails carry a one-shot token, and the token is the thing
    the mail exists to deliver. `signup_exists` is the exception: its
    link is the plain sign-in page, because there is nothing to confirm —
    the account already exists, and handing an unauthenticated caller a
    token for somebody else's account is precisely what that mail must
    not do.
    """
    if kind == copy_mod.KIND_SIGNUP_EXISTS:
        return f"{APP}/login"
    if kind == copy_mod.KIND_CONCIERGE_WELCOME:
        # The link is what this mail is for: the first thing to do with a
        # mailed password is replace it.
        return f"{APP}/settings/password"
    return TOKEN


@pytest.mark.parametrize("kind", copy_mod.LINK_KINDS)
@pytest.mark.parametrize("lang", copy_mod.SUPPORTED_LANGS)
def test_action_link_is_present_in_both_parts(kind: str, lang: str) -> None:
    """The one thing the mail exists to deliver must be in both parts."""
    rendered = _render(kind, lang)
    expected = _expected_link(kind)
    assert expected in rendered.html_body
    assert expected in rendered.text_body


@pytest.mark.parametrize("lang", copy_mod.SUPPORTED_LANGS)
def test_the_signup_confirmation_mail_carries_no_link(lang: str) -> None:
    """BE-0: a code, never a link.

    Corporate mail filters and some mobile clients open every URL in an
    inbound message. A confirmation link would be spent by a machine that
    merely read the mail, and the person would arrive to find their
    confirmation already used. A six-digit code cannot be consumed by a
    scanner.
    """
    rendered = _render(copy_mod.KIND_SIGNUP_VERIFY, lang)
    assert "http" not in rendered.text_body
    assert "482 913" in rendered.text_body
    assert "<a " not in rendered.html_body


@pytest.mark.parametrize("lang", copy_mod.SUPPORTED_LANGS)
def test_neither_signup_mail_says_whether_the_address_was_registered(lang: str) -> None:
    """The uniform 202 is only honest if the mails keep the secret too.

    `/auth/signup` answers identically for a new address and a known one,
    so the sole place the difference exists is a mailbox. Neither body may
    quote the address back, which is what would turn a forwarded screenshot
    into a disclosure.
    """
    for kind in (copy_mod.KIND_SIGNUP_VERIFY, copy_mod.KIND_SIGNUP_EXISTS):
        rendered = _render(kind, lang)
        assert "olena@acme.example" not in rendered.text_body
        assert "olena@acme.example" not in rendered.html_body


@pytest.mark.parametrize("lang", copy_mod.SUPPORTED_LANGS)
def test_email_change_notice_masks_the_new_address(lang: str) -> None:
    """It goes to the address that just lost the account.

    The reader is not necessarily the person who made the change, so the
    full destination is withheld — enough is shown to recognise your own
    other address, not enough to hand a stranger's mailbox to an attacker.
    """
    rendered = _render(copy_mod.KIND_EMAIL_CHANGED, lang)
    assert "new-address@acme.example" not in rendered.html_body
    assert "new-address@acme.example" not in rendered.text_body
    assert "n***s@acme.example" in rendered.text_body


@pytest.mark.parametrize("lang", copy_mod.SUPPORTED_LANGS)
def test_a5_notices_carry_no_link_except_the_revert(lang: str) -> None:
    """A security notice that trains people to click is a lure.

    Only the email-change notice has anything to undo, and that is the
    one place a link earns its place.
    """
    for kind in (
        copy_mod.KIND_MFA_ENABLED,
        copy_mod.KIND_MFA_DISABLED,
        copy_mod.KIND_RECOVERY_CODE_USED,
        copy_mod.KIND_ACCOUNT_DELETION,
    ):
        rendered = _render(kind, lang)
        assert "href=" not in rendered.html_body, kind
        assert "http" not in rendered.text_body, kind


@pytest.mark.parametrize("lang", copy_mod.SUPPORTED_LANGS)
def test_security_mail_carries_the_lockdown_route(lang: str) -> None:
    rendered = _render(copy_mod.KIND_PASSWORD_CHANGED, lang)
    assert "/#/account-recovery?token=" in rendered.html_body


@pytest.mark.parametrize("lang", copy_mod.SUPPORTED_LANGS)
def test_reset_mail_carries_the_reset_route(lang: str) -> None:
    rendered = _render(copy_mod.KIND_PASSWORD_RESET, lang)
    assert "/#/reset-password?token=" in rendered.html_body


def test_missing_variable_raises_rather_than_rendering_a_blank_link() -> None:
    """StrictUndefined is load-bearing, not decoration."""
    from jinja2 import UndefinedError

    with pytest.raises(UndefinedError):
        templates.render_html(copy_mod.KIND_PASSWORD_RESET, "en", {"greeting": "Hello,"})


def test_unknown_kind_and_language_are_refused() -> None:
    with pytest.raises(ValueError):
        templates.template_name("not_a_kind", "en")
    with pytest.raises(ValueError):
        templates.template_name(copy_mod.KIND_PASSWORD_RESET, "fr")


def test_attacker_supplied_email_is_html_escaped() -> None:
    """The address is attacker-chosen on the forgot endpoint."""
    fields, secrets = _fields(copy_mod.KIND_PASSWORD_RESET, "en")
    fields["email"] = "<script>alert(1)</script>@x.com"
    html = templates.render_html(copy_mod.KIND_PASSWORD_RESET, "en", {**fields, **secrets})
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_subject_newlines_are_stripped() -> None:
    rendered = templates.render(
        copy_mod.KIND_PASSWORD_RESET,
        "en",
        subject="Reset\r\nBcc: attacker@evil.example",
        text_body="body",
        context=dict(
            **_fields(copy_mod.KIND_PASSWORD_RESET, "en")[0],
            **_fields(copy_mod.KIND_PASSWORD_RESET, "en")[1],
        ),
    )
    assert "\n" not in rendered.subject
    assert "\r" not in rendered.subject


# ── Language and formatting ──────────────────────────────────────────


def test_language_falls_back_to_english() -> None:
    assert copy_mod.normalise_lang("fr") == "en"
    assert copy_mod.normalise_lang(None) == "en"
    assert copy_mod.normalise_lang("de-AT") == "de"
    assert copy_mod.normalise_lang("UK") == "uk"


def test_ukrainian_minutes_pluralisation_handles_the_teens() -> None:
    """11 takes the plural, 1 and 21 take the singular. The teens are
    the case a naive `n == 1` check gets wrong."""
    assert copy_mod.minutes_label(60, "uk") == "1 хвилина"
    assert copy_mod.minutes_label(11 * 60, "uk") == "11 хвилин"
    assert copy_mod.minutes_label(21 * 60, "uk") == "21 хвилина"
    assert copy_mod.minutes_label(3 * 60, "uk") == "3 хвилини"


def test_greeting_without_a_name_is_still_grammatical() -> None:
    for lang in copy_mod.SUPPORTED_LANGS:
        assert copy_mod.greeting(lang, "").strip()
        assert "{" not in copy_mod.greeting(lang, "")


def test_client_label_is_coarse_not_a_fingerprint() -> None:
    assert compose.client_label(UA, "en") == "Chrome on macOS"
    # Nothing usable → a named fallback, never an empty row.
    assert compose.client_label("", "en") == "Unrecognised device"
    assert compose.client_label("", "de") == "Unbekanntes Gerät"


def test_client_line_collapses_when_the_device_is_unknown() -> None:
    """An 'Unrecognised device' line in the text part reads as missing
    data; better to omit the line entirely."""
    fields, secrets = _fields(copy_mod.KIND_PASSWORD_RESET, "en")
    fields["client_label"] = "Unrecognised device"
    values = compose.text_values(copy_mod.KIND_PASSWORD_RESET, "en", fields, secrets)
    assert values["client_line"] == ""


def test_ip_hash_is_salted_and_truncated() -> None:
    a = compose.hash_ip("203.0.113.7", salt="salt-a")
    b = compose.hash_ip("203.0.113.7", salt="salt-b")
    assert a != b, "an unsalted IP hash is reversible by brute force"
    assert len(a) == 32
    assert compose.hash_ip("", salt="s") == ""


# ── MIME assembly ────────────────────────────────────────────────────


def test_mime_has_both_parts_and_the_headers_deliverability_needs() -> None:
    mime = email_mod.build_mime(
        email_mod.OutboundEmail(
            to_address="olena@acme.example",
            subject="Reset your Notes AI password",
            text_body="text",
            html_body="<p>html</p>",
            reply_to="sales@notes-ai.local",
        ),
        from_address="sales@notes-ai.local",
        from_name="Notes AI",
    )
    assert mime.get_content_type() == "multipart/alternative"
    assert mime["Message-ID"]
    assert mime["Date"]
    assert mime["Reply-To"] == "sales@notes-ai.local"
    # Security mail IS auto-generated: suppress out-of-office replies.
    assert mime["Auto-Submitted"] == "auto-generated"


def test_security_mail_is_not_unsubscribable() -> None:
    """RFC 8058 is for bulk mail. An unsubscribe path on a security
    notification would let whoever already holds the mailbox silence the
    one warning that would expose them."""
    mime = email_mod.build_mime(
        email_mod.OutboundEmail(
            to_address="a@b.example", subject="s", text_body="t", html_body="<p>h</p>"
        ),
        from_address="sales@notes-ai.local",
        from_name="Notes AI",
    )
    assert mime["List-Unsubscribe"] is None
    assert mime["List-Unsubscribe-Post"] is None


def test_ehlo_hostname_never_resolves_the_local_fqdn() -> None:
    """socket.getfqdn() blocks for 30s on a network with no PTR record,
    inside the send, inside the transaction holding the outbox row."""
    assert email_mod.ehlo_hostname("sales@notes-ai.local") == "notes-ai.local"
    assert email_mod.ehlo_hostname("") == "localhost"


def test_mock_provider_refuses_to_run_in_production() -> None:
    with pytest.raises(RuntimeError, match="never be used in production"):
        email_mod.MockProvider(is_production=True)
    with pytest.raises(RuntimeError):
        email_mod.build_provider(kind="mock", is_production=True)


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown email provider"):
        email_mod.build_provider(kind="carrier-pigeon", is_production=False)


async def test_mock_provider_captures_mail() -> None:
    provider = email_mod.MockProvider()
    result = await provider.send(
        email_mod.OutboundEmail(to_address="a@b.example", subject="s", text_body="t")
    )
    assert provider.sent[0].to_address == "a@b.example"
    assert result.provider_message_id


@pytest.mark.parametrize("lang", copy_mod.SUPPORTED_LANGS)
def test_auth_code_mail_carries_the_grouped_code_and_no_links(lang: str) -> None:
    rendered = _render(copy_mod.KIND_AUTH_CODE, lang)
    assert "482 913" in rendered.html_body and "482 913" in rendered.text_body
    assert "482913" not in rendered.subject  # never in a notification preview
    assert "href=" not in rendered.html_body
    assert "http" not in rendered.text_body
    assert "olena@" not in rendered.html_body  # the address stays in the envelope


@pytest.mark.parametrize("lang", copy_mod.SUPPORTED_LANGS)
def test_locked_mail_has_no_links_and_names_the_unlock_time(lang: str) -> None:
    rendered = _render(copy_mod.KIND_AUTH_LOCKED, lang)
    assert "href=" not in rendered.html_body
    assert "2026" in rendered.text_body
