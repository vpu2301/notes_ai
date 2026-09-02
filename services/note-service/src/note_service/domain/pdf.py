"""PDF rendering for note exports (M1·A3).

Builds a :class:`RenderInput` from a note + version row and renders it
through Jinja2 + WeasyPrint. The weasyprint/jinja2 import is lazy
inside ``_render`` so it stays out of the router import path — only an
actual render touches the native deps.

Determinism (kept from the original renderer — useful for caching and
byte-level comparison in tests):
- Jinja2 template with no time-of-render injection.
- WeasyPrint with explicit pinned settings + ``presentational_hints=False``.
- ``mod_date`` / ``creation_date`` overridden via pypdf metadata write
  so the PDF bytes are stable across renders.
- Same input → byte-equal output.

CSS injection defence:
- Jinja2 autoescape on for HTML; we never inject untrusted bytes into
  ``<style>`` blocks (the template has none).
- User strings are clamped to ``MAX_FIELD_LENGTH`` (500 chars) before
  rendering so a malicious 10MB-string can't OOM the renderer.

Name resolution is deliberately minimal (doc 02·A3): the author UUID is
the ``primary_author_full_name`` fallback — note-service does not hold
the user-name aggregate.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .notes_repository import NoteRow, VersionRow

logger = logging.getLogger(__name__)

MAX_FIELD_LENGTH = 500
_DETERMINISTIC_DATE = "D:20260101000000+00'00'"
_TEMPLATE_DIR = Path(__file__).resolve().parent / "pdf_templates"


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


def _clamp(s: str | None) -> str:
    if not s:
        return ""
    return s[:MAX_FIELD_LENGTH]


def build_render_input(
    *,
    note: NoteRow,
    version: VersionRow,
    issuer_name: str,
    is_draft: bool = False,
    language: str = "en",
) -> RenderInput:
    content = version.content

    # ``finalized_at`` may be empty for non-finalized (draft) notes; the
    # template omits the "finalized" line when it is blank.
    finalized_at = note.finalized_at.isoformat() if note.finalized_at else ""

    return RenderInput(
        title=note.title,
        code=note.code,
        issuer_name=issuer_name,
        primary_author_full_name=str(note.primary_author_id),
        co_author_names=[str(a) for a in note.co_author_ids],
        sections=[{"section_key": s.section_key, "text": s.text} for s in content.sections],
        finalized_at=finalized_at,
        language=language,
        is_draft=is_draft,
    )


def render_note_pdf(
    *,
    note: NoteRow,
    version: VersionRow,
    issuer_name: str,
    is_draft: bool = False,
    language: str = "en",
) -> bytes:
    """Render the PDF bytes for a note version.

    ``is_draft`` toggles the draft watermark/banner treatment;
    ``language`` selects the label set (uk/en/de) in the template.
    """
    payload = build_render_input(
        note=note,
        version=version,
        issuer_name=issuer_name,
        is_draft=is_draft,
        language=language,
    )
    return _render(payload)


def _render(payload: RenderInput) -> bytes:
    import os

    # WeasyPrint's font subsetting (fontTools) stamps time-of-render into
    # the subset font's `head` table unless SOURCE_DATE_EPOCH is set —
    # breaking the byte-equal determinism. noqa justified: this is a
    # reproducible-build knob for the render library, not application
    # config; 1767225600 = 2026-01-01T00:00Z, matching _DETERMINISTIC_DATE.
    os.environ.setdefault("SOURCE_DATE_EPOCH", "1767225600")  # noqa: ENV001
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        from weasyprint import HTML
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "PDF rendering requires weasyprint + jinja2. Original error: " + str(exc)
        ) from exc

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tpl = env.get_template("note.html.j2")
    html = tpl.render(
        title=_clamp(payload.title),
        code=_clamp(payload.code),
        issuer=_clamp(payload.issuer_name),
        primary_author=_clamp(payload.primary_author_full_name),
        co_authors=[_clamp(c) for c in payload.co_author_names],
        sections=[
            {"key": _clamp(s.get("section_key", "")), "text": _clamp(s.get("text", ""))}
            for s in payload.sections
        ],
        finalized_at=payload.finalized_at,
        language=payload.language,
        is_draft=payload.is_draft,
    )
    pdf_bytes = HTML(string=html, base_url=str(_TEMPLATE_DIR)).write_pdf(
        presentational_hints=False,
    )
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
