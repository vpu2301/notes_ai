"""PDF rendering for note exports (M1·A3).

Builds a :class:`RenderInput` from a note + version row and renders it
through Jinja2 + WeasyPrint. The weasyprint/jinja2 import is lazy
inside ``_render`` so it stays out of the router import path — only an
actual render touches the native deps.

The document follows the product's design language (see
``web/src/styles/tokens.css``): warm paper rather than white, warm ink
rather than black, one moss accent, hairline rules instead of boxes,
and Geist — the same face the apps use — embedded from
``pdf_templates/fonts``. Section bodies go through
:mod:`.pdf_richtext`, so a generated meeting note lands as real
paragraphs, bullets and checklists instead of raw markdown.

Determinism (kept from the original renderer — useful for caching and
byte-level comparison in tests):
- Jinja2 template with no time-of-render injection.
- WeasyPrint with explicit pinned settings + ``presentational_hints=False``.
- ``mod_date`` / ``creation_date`` overridden via pypdf metadata write
  so the PDF bytes are stable across renders.
- Same input → byte-equal output.

Injection defence:
- Jinja2 autoescape on for HTML; the one unescaped value (the section
  body) is escaped inside :func:`.render_rich_text` before any markup
  is produced, and no user byte ever reaches an attribute.
- Nothing is interpolated into ``<style>``: the strings the running
  header/footer need reach the margin boxes through CSS ``string-set``
  on ordinary flow elements, not through generated CSS.
- Short fields are clamped to ``MAX_FIELD_LENGTH`` and section bodies
  to ``MAX_SECTION_LENGTH`` (with a whole-document budget) so a
  malicious 10MB-string can't OOM the renderer.

Name resolution is deliberately minimal (doc 02·A3): note-service does
not hold the user-name aggregate, so the author falls back to the
author UUID — and an opaque UUID is *not* printed as if it were a
person's name (see :func:`_looks_opaque`).
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .notes_repository import NoteRow, VersionRow
from .pdf_richtext import render_rich_text

logger = logging.getLogger(__name__)

# Short single-line fields (title, code, issuer, names).
MAX_FIELD_LENGTH = 500
# One section body. A real meeting note runs to a few thousand
# characters; the cap is only here to bound the renderer.
MAX_SECTION_LENGTH = 40_000
# Whole document, across all sections.
MAX_DOCUMENT_LENGTH = 400_000

_DETERMINISTIC_DATE = "D:20260101000000+00'00'"
_TEMPLATE_DIR = Path(__file__).resolve().parent / "pdf_templates"
_TEMPLATE_NAME = "note.html.j2"

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# Month names for the printed date. Deterministic and locale-free — the
# render must not depend on the container's locale.
_MONTHS = {
    "en": [
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
    ],
    "uk": [
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
    ],
    "de": [
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
    ],
}


@dataclass(frozen=True, slots=True)
class RenderInput:
    title: str
    code: str
    issuer_name: str
    primary_author_full_name: str
    co_author_names: list[str]
    sections: list[dict[str, Any]]
    finalized_at: str
    language: str = "en"
    is_draft: bool = False
    updated_at: str = ""
    section_names: dict[str, str] = field(default_factory=dict)


def _clamp(s: str | None, limit: int = MAX_FIELD_LENGTH) -> str:
    if not s:
        return ""
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "…"


def _looks_opaque(name: str) -> bool:
    """True when the "author name" is really just an identifier.

    note-service resolves the author to a UUID when it has no name
    aggregate to ask; printing that under "Author" makes the document
    look broken, so the template omits the line instead."""
    return bool(_UUID_RE.match(name.strip()))


def _humanize(key: str) -> str:
    """``action_items`` → ``Action items``. Only used when the caller
    could not resolve the note's template labels."""
    words = re.sub(r"[_\-.]+", " ", key).strip()
    if not words:
        return ""
    # camelCase → sentence case, not Title Case.
    words = re.sub(r"(?<=[a-z0-9])([A-Z])", lambda m: " " + m.group(1).lower(), words)
    return words[0].upper() + words[1:]


def _format_date(iso: str, language: str) -> str:
    """``2026-09-04T14:32:00+00:00`` → ``4 September 2026, 14:32``.

    Falls back to the raw string if it will not parse — a printed ISO
    stamp is ugly, a traceback is worse."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    months = _MONTHS.get(language, _MONTHS["en"])
    month = months[dt.month - 1]
    day = f"{dt.day}. {month} {dt.year}" if language == "de" else f"{dt.day} {month} {dt.year}"
    return f"{day}, {dt:%H:%M}"


def template_env() -> Any:
    """The Jinja environment the PDF is rendered with.

    ``autoescape=True`` unconditionally — NOT
    ``select_autoescape(["html", "xml"])``, which keys off the file
    extension and therefore left ``note.html.j2`` (a ``.j2`` file)
    unescaped. Tests build the document through this same factory so
    the two can never drift.
    """
    from jinja2 import Environment, FileSystemLoader

    return Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)


def build_render_input(
    *,
    note: NoteRow,
    version: VersionRow,
    issuer_name: str,
    is_draft: bool = False,
    language: str = "en",
    section_names: dict[str, str] | None = None,
) -> RenderInput:
    content = version.content
    names = dict(section_names or {})

    # ``finalized_at`` may be empty for non-finalized (draft) notes; the
    # template falls back to the last-updated stamp for those.
    finalized_at = note.finalized_at.isoformat() if note.finalized_at else ""

    # The document reads in template order — the order the editor shows
    # and the shared view serves — not in whatever order the version's
    # content happens to hold. Sections the template no longer knows
    # about keep their relative order at the end.
    order = list(names)
    sections = sorted(
        content.sections,
        key=lambda s: order.index(s.section_key) if s.section_key in order else len(order),
    )

    return RenderInput(
        title=note.title,
        code=note.code,
        issuer_name=issuer_name,
        primary_author_full_name=str(note.primary_author_id),
        co_author_names=[str(a) for a in note.co_author_ids],
        sections=[{"section_key": s.section_key, "text": s.text} for s in sections],
        finalized_at=finalized_at,
        language=language,
        is_draft=is_draft,
        updated_at=note.updated_at.isoformat() if note.updated_at else "",
        section_names=names,
    )


def render_note_pdf(
    *,
    note: NoteRow,
    version: VersionRow,
    issuer_name: str,
    is_draft: bool = False,
    language: str = "en",
    section_names: dict[str, str] | None = None,
) -> bytes:
    """Render the PDF bytes for a note version.

    ``is_draft`` toggles the draft treatment; ``language`` selects the
    label set (uk/en/de); ``section_names`` maps ``section_key`` to the
    human heading from the note's template (falling back to a humanized
    key when the caller has none).
    """
    payload = build_render_input(
        note=note,
        version=version,
        issuer_name=issuer_name,
        is_draft=is_draft,
        language=language,
        section_names=section_names,
    )
    return _render(payload)


def _prepare_sections(payload: RenderInput) -> list[dict[str, str]]:
    """Clamp, name and typeset each section; drop the empty ones.

    Returns ``{"name", "html"}`` per rendered section — ``html`` is
    already-escaped markup from :func:`.render_rich_text`."""
    out: list[dict[str, str]] = []
    budget = MAX_DOCUMENT_LENGTH
    for s in payload.sections:
        key = str(s.get("section_key", ""))
        text = str(s.get("text", "") or "")
        if not text.strip() or budget <= 0:
            continue
        text = _clamp(text, min(MAX_SECTION_LENGTH, budget))
        budget -= len(text)
        name = payload.section_names.get(key) or _humanize(key)
        out.append({"name": _clamp(name), "html": render_rich_text(text)})
    return out


def _render(payload: RenderInput) -> bytes:
    import os

    # WeasyPrint's font subsetting (fontTools) stamps time-of-render into
    # the subset font's `head` table unless SOURCE_DATE_EPOCH is set —
    # breaking the byte-equal determinism. noqa justified: this is a
    # reproducible-build knob for the render library, not application
    # config; 1767225600 = 2026-01-01T00:00Z, matching _DETERMINISTIC_DATE.
    os.environ.setdefault("SOURCE_DATE_EPOCH", "1767225600")  # noqa: ENV001
    try:
        from markupsafe import Markup
        from weasyprint import HTML
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "PDF rendering requires weasyprint + jinja2. Original error: " + str(exc)
        ) from exc

    tpl = template_env().get_template(_TEMPLATE_NAME)

    author = _clamp(payload.primary_author_full_name)
    html = tpl.render(
        title=_clamp(payload.title),
        code=_clamp(payload.code),
        issuer=_clamp(payload.issuer_name),
        # An unresolved author is a bare UUID — printed under "Author" it
        # reads as a bug, so the block is dropped instead.
        primary_author="" if _looks_opaque(author) else author,
        co_authors=[_clamp(c) for c in payload.co_author_names if not _looks_opaque(c)],
        sections=[
            # Markup(): the body is escaped in render_rich_text before any
            # tag is emitted, and carries no user bytes in attributes.
            {"name": s["name"], "html": Markup(s["html"])}
            for s in _prepare_sections(payload)
        ],
        finalized_at=payload.finalized_at,
        date_label=_format_date(payload.finalized_at or payload.updated_at, payload.language),
        language=payload.language,
        is_draft=payload.is_draft,
    )
    # base_url must name a *document*, not a directory: WeasyPrint joins
    # relative URLs (the embedded fonts) against it the way a browser
    # would, dropping the last segment.
    pdf_bytes = HTML(
        string=html,
        base_url=(_TEMPLATE_DIR / "note.html.j2").as_uri(),
    ).write_pdf(presentational_hints=False)
    return _normalise_pdf_dates(pdf_bytes)


def compute_pdf_hash(pdf_bytes: bytes) -> bytes:
    import hashlib

    return hashlib.sha256(pdf_bytes).digest()


def _normalise_pdf_dates(pdf_bytes: bytes) -> bytes:
    """Rewrite /CreationDate and /ModDate so two renders of the same
    input produce byte-equal PDFs."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter(clone_from=reader)
    try:
        writer.add_metadata(
            {
                "/CreationDate": _DETERMINISTIC_DATE,
                "/ModDate": _DETERMINISTIC_DATE,
                "/Producer": "note-service",
                "/Creator": "note-service",
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("pdf metadata stamp failed (non-fatal): %s", exc)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
