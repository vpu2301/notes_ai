"""Jinja environment for the share mail.

``StrictUndefined`` is the load-bearing choice: a typo'd variable must
fail the render, not quietly produce a mail whose button links to
nothing. Autoescaping is the other one — a note title and a display name
are user-written, and unescaped they are an HTML-injection vector in a
mail client.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from . import share_mail_copy as copy

TEMPLATE_DIR: Final = Path(__file__).parent / "templates"
TEMPLATE_NAME: Final = "note_share.html"


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    subject: str
    text_body: str
    html_body: str


def build_environment(template_dir: Path | None = None) -> Environment:
    return Environment(
        loader=FileSystemLoader(str(template_dir or TEMPLATE_DIR)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(["html", "xml"], default_for_string=True),
        keep_trailing_newline=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


_ENV: Environment | None = None


def _env() -> Environment:
    global _ENV
    if _ENV is None:
        _ENV = build_environment()
    return _ENV


def render(
    *,
    lang: str,
    sharer_name: str,
    sharer_email: str,
    note_title: str,
    message: str,
    link_url: str,
    access: str,
    shared_at: datetime,
    env: Environment | None = None,
) -> RenderedEmail:
    lang = copy.normalize_lang(lang)
    strings = copy.strings(lang, sharer=sharer_name, access=access)
    # Blank lines separate paragraphs; the template renders each as its
    # own <p>. Splitting here rather than with `nl2br` in the template
    # keeps the escaping automatic — no `|safe` anywhere near text a
    # user typed.
    paragraphs = [p.strip() for p in message.strip().split("\n\n") if p.strip()]
    html = (
        (env or _env())
        .get_template(TEMPLATE_NAME)
        .render(
            lang=lang,
            t=strings,
            note_title=note_title.strip() or strings["title"],
            message_paragraphs=paragraphs,
            sharer_name=sharer_name,
            sharer_email=sharer_email,
            link_url=link_url,
            shared_at=copy.format_datetime(shared_at, lang),
        )
    )
    return RenderedEmail(
        # A newline in a subject is a header-injection primitive: the
        # bytes after it become additional headers. Stripped here, the
        # last place before the MIME document is assembled.
        subject=copy.subject(lang, sharer=sharer_name, note_title=note_title)
        .replace("\n", " ")
        .replace("\r", " ")
        .strip(),
        text_body=copy.text_body(
            lang,
            sharer=sharer_name,
            sharer_email=sharer_email,
            note_title=note_title,
            message=message,
            link_url=link_url,
            access=access,
            shared_at=shared_at,
        ).strip(),
        html_body=html.strip(),
    )
