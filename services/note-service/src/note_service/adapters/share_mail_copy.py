"""Every word the share mail says, in every language it says it.

Split from the template so the prose can be proofread by somebody who
does not read Jinja, and so the two body parts (HTML and text/plain) are
built from the SAME strings and cannot drift into saying different
things to the same recipient.

It lives beside the renderer in ``adapters`` rather than in ``domain``
because the layering runs routers → domain → adapters: the renderer is
an adapter, and an adapter reaching back up into the domain for its own
strings is the inversion the contract exists to prevent.

The plain-text alternate uses ``str.format`` rather than Jinja, and that
is deliberate: Jinja's autoescaping would turn the ``&`` in a link's
query string into ``&amp;`` inside a text/plain part, where it is not
markup and the link would arrive broken.

Dates are formatted by hand rather than through ``locale``: the C locale
is process-global and not thread-safe, so one request formatting a
Ukrainian date would change what every concurrent request produced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

SUPPORTED_LANGS: Final[tuple[str, ...]] = ("en", "de", "uk")
DEFAULT_LANG: Final = "en"

# How the recipient gets in. `member` already has an account and the note
# is now on their list; `link` is anybody else, reading through a public
# link. The two say different things about access, and saying the wrong
# one is how somebody learns the hard way that a link is public.
ACCESS_MEMBER: Final = "member"
ACCESS_LINK: Final = "link"

_MONTHS: Final[dict[str, tuple[str, ...]]] = {
    "en": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
    "de": (
        "Januar",
        "Februar",
        "März",
        "April",
        "Mai",
        "Juni",
        "Juli",
        "August",
        "September",
        "Oktober",
        "November",
        "Dezember",
    ),
    "uk": (
        "січня",
        "лютого",
        "березня",
        "квітня",
        "травня",
        "червня",
        "липня",
        "серпня",
        "вересня",
        "жовтня",
        "листопада",
        "грудня",
    ),
}

_COPY: Final[dict[str, dict[str, str]]] = {
    "en": {
        "title": "A note was shared with you",
        "eyebrow": "SHARED NOTE",
        "preheader": "{sharer} shared a note with you.",
        "kicker": "{sharer} shared a note with you",
        "lede": "Everything from the meeting — what was decided, and what happens next.",
        "cta": "Open the note",
        "link_label": "Or paste this address into your browser:",
        "from_label": "Shared by",
        "sent_label": "Sent",
        "access_member": ("It is on your notes list — sign in with this address to open it."),
        "access_link": ("Anyone who has this link can read the note. No account needed."),
        "footer_why": ("You received this because {sharer} shared a note with this address."),
        "subject": "{sharer} shared “{title}” with you",
        "subject_untitled": "{sharer} shared a note with you",
    },
    "de": {
        "title": "Eine Notiz wurde mit Ihnen geteilt",
        "eyebrow": "GETEILTE NOTIZ",
        "preheader": "{sharer} hat eine Notiz mit Ihnen geteilt.",
        "kicker": "{sharer} hat eine Notiz mit Ihnen geteilt",
        "lede": "Alles aus dem Gespräch — was entschieden wurde und was als Nächstes ansteht.",
        "cta": "Notiz öffnen",
        "link_label": "Oder diese Adresse in den Browser kopieren:",
        "from_label": "Geteilt von",
        "sent_label": "Gesendet",
        "access_member": (
            "Sie steht in Ihrer Notizenliste — melden Sie sich mit dieser "
            "Adresse an, um sie zu öffnen."
        ),
        "access_link": ("Jede Person mit diesem Link kann die Notiz lesen. Kein Konto nötig."),
        "footer_why": (
            "Sie erhalten diese E-Mail, weil {sharer} eine Notiz mit dieser Adresse geteilt hat."
        ),
        "subject": "{sharer} hat „{title}“ mit Ihnen geteilt",
        "subject_untitled": "{sharer} hat eine Notiz mit Ihnen geteilt",
    },
    "uk": {
        "title": "Вам надіслали нотатку",
        "eyebrow": "СПІЛЬНА НОТАТКА",
        "preheader": "{sharer} поділився з вами нотаткою.",
        "kicker": "{sharer} поділився з вами нотаткою",
        "lede": "Усе з зустрічі — що вирішили та що робимо далі.",
        "cta": "Відкрити нотатку",
        "link_label": "Або скопіюйте цю адресу у браузер:",
        "from_label": "Поділився",
        "sent_label": "Надіслано",
        "access_member": (
            "Вона вже у вашому списку нотаток — увійдіть із цією адресою, щоб відкрити її."
        ),
        "access_link": (
            "Будь-хто з цим посиланням може прочитати нотатку. Обліковий запис не потрібен."
        ),
        "footer_why": ("Ви отримали цей лист, бо {sharer} поділився нотаткою з цією адресою."),
        "subject": "{sharer} поділився з вами «{title}»",
        "subject_untitled": "{sharer} поділився з вами нотаткою",
    },
}

# The legal sender line every mail ends with (the HTML template carries
# the same line in its footer).
LEGAL_LINE: Final = "3Days Labs Inc, 2166 Market Street, San Francisco, CA 94114"

# The plain-text alternate. Same order as the HTML, so a recipient whose
# client shows text/plain reads the same mail in the same sequence.
_TEXT: Final[dict[str, str]] = {
    "en": (
        "{kicker}\n"
        "\n"
        "{title}\n"
        "{message_block}"
        "{access}\n"
        "\n"
        "{link}\n"
        "\n"
        "--\n"
        "Shared by {sharer}{sharer_email_suffix}\n"
        "Sent {shared_at}\n"
        "Notes AI\n"
        "{legal}"
    ),
    "de": (
        "{kicker}\n"
        "\n"
        "{title}\n"
        "{message_block}"
        "{access}\n"
        "\n"
        "{link}\n"
        "\n"
        "--\n"
        "Geteilt von {sharer}{sharer_email_suffix}\n"
        "Gesendet {shared_at}\n"
        "Notes AI\n"
        "{legal}"
    ),
    "uk": (
        "{kicker}\n"
        "\n"
        "{title}\n"
        "{message_block}"
        "{access}\n"
        "\n"
        "{link}\n"
        "\n"
        "--\n"
        "Поділився: {sharer}{sharer_email_suffix}\n"
        "Надіслано {shared_at}\n"
        "Notes AI\n"
        "{legal}"
    ),
}


def normalize_lang(lang: str | None) -> str:
    """``de-CH`` → ``de``; anything we do not write → English."""
    if not lang:
        return DEFAULT_LANG
    base = lang.strip().lower().replace("_", "-").split("-", 1)[0]
    return base if base in SUPPORTED_LANGS else DEFAULT_LANG


def format_datetime(when: datetime, lang: str) -> str:
    when = when.astimezone(UTC)
    months = _MONTHS[lang]
    month = months[when.month - 1]
    if lang == "uk":
        return f"{when.day} {month} {when.year}, {when:%H:%M} UTC"
    if lang == "de":
        return f"{when.day}. {month} {when.year}, {when:%H:%M} UTC"
    return f"{month} {when.day}, {when.year} at {when:%H:%M} UTC"


def strings(lang: str, *, sharer: str, access: str) -> dict[str, str]:
    """The per-language strings the HTML template renders, resolved.

    `access` picks between the two truthful sentences about who can read
    the note; there is no default, because guessing wrong is the failure
    that matters here.
    """
    if access not in (ACCESS_MEMBER, ACCESS_LINK):
        raise ValueError(f"unknown access kind {access!r}")
    copy = _COPY[lang]
    return {
        "title": copy["title"],
        "eyebrow": copy["eyebrow"],
        "preheader": copy["preheader"].format(sharer=sharer),
        "kicker": copy["kicker"].format(sharer=sharer),
        "lede": copy["lede"],
        "cta": copy["cta"],
        "link_label": copy["link_label"],
        "from_label": copy["from_label"],
        "sent_label": copy["sent_label"],
        "access_note": copy["access_member" if access == ACCESS_MEMBER else "access_link"],
        "footer_why": copy["footer_why"].format(sharer=sharer),
    }


def subject(lang: str, *, sharer: str, note_title: str) -> str:
    copy = _COPY[lang]
    title = note_title.strip()
    if not title:
        return copy["subject_untitled"].format(sharer=sharer)
    return copy["subject"].format(sharer=sharer, title=title)


def text_body(
    lang: str,
    *,
    sharer: str,
    sharer_email: str,
    note_title: str,
    message: str,
    link_url: str,
    access: str,
    shared_at: datetime,
) -> str:
    resolved = strings(lang, sharer=sharer, access=access)
    message_block = ""
    if message.strip():
        quoted = "\n".join(f"> {line}" for line in message.strip().splitlines())
        message_block = f"\n{quoted}\n\n"
    else:
        message_block = "\n"
    return _TEXT[lang].format(
        legal=LEGAL_LINE,
        kicker=resolved["kicker"],
        title=note_title.strip() or resolved["title"],
        message_block=message_block,
        access=resolved["access_note"],
        link=link_url,
        sharer=sharer,
        sharer_email_suffix=f" <{sharer_email}>" if sharer_email else "",
        shared_at=format_datetime(shared_at, lang),
    )


# ── Sprint 22: the recipient-link mail's extra facts ─────────────────

_RECIPIENT: Final[dict[str, dict[str, str]]] = {
    "en": {
        "issuer_label": "Shared from the workspace of",
        "expires_label": "This link expires on",
        "unsubscribe": "Don't want e-mails like this? Unsubscribe",
    },
    "de": {
        "issuer_label": "Geteilt aus dem Workspace von",
        "expires_label": "Dieser Link läuft ab am",
        "unsubscribe": "Keine solchen E-Mails mehr? Abmelden",
    },
    "uk": {
        "issuer_label": "Поділився робочий простір",
        "expires_label": "Посилання дійсне до",
        "unsubscribe": "Не хочете таких листів? Відписатися",
    },
}


def recipient_strings(lang: str) -> dict[str, str]:
    return dict(_RECIPIENT[normalize_lang(lang)])


def recipient_text_footer(
    lang: str, *, issuer_name: str, expires_on: str, brand_line: str, unsubscribe_url: str
) -> str:
    """Plain-text lines appended under the share mail; empty when the
    caller passed nothing (the member/public mail)."""
    t = recipient_strings(lang)
    lines: list[str] = []
    if issuer_name:
        lines.append(f"{t['issuer_label']} {issuer_name}")
    if expires_on:
        lines.append(f"{t['expires_label']} {expires_on}")
    if brand_line:
        lines.append(brand_line)
    if unsubscribe_url:
        lines.append(f"{t['unsubscribe']}: {unsubscribe_url}")
    return ("\n\n" + "\n".join(lines)) if lines else ""
