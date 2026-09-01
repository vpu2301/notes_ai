"""Pre-transition finalize validation.

Ensures every section flagged ``required`` in the template has content
≥ ``min_chars``.

Sprint 13 adds **typed** completeness: ``min_chars`` measures prose, so
it says nothing about a ``choice`` section whose answer lives in
``field_specific_metadata``. Each typed field type gets its own
"filled" rule (see ``_typed_problem``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from note_models import NoteContent
from template_models import TemplateDefinition

# Normalised, contract-facing reasons keyed by the legacy ``code``.
# Anything unmapped falls through to the code itself.
_REASON_BY_CODE: Final[dict[str, str]] = {
    "missing_required_section": "required_empty",
    "below_min_chars": "below_min_chars",
    # Sprint 13 — typed completeness.
    "choice_not_selected": "choice_not_selected",
    "numeric_not_filled": "numeric_not_filled",
    "date_not_filled": "date_not_filled",
}

# Field types whose completeness lives in metadata, not in prose.
_TYPED_FIELD_TYPES: Final[frozenset[str]] = frozenset(
    {
        "choice",
        "multi_choice",
        "numeric_with_unit",
        "date",
        "date_with_note",
    }
)


@dataclass(slots=True)
class FinalizeProblem:
    field: str
    code: str
    detail: str
    section_key: str | None = None

    @property
    def reason(self) -> str:
        return _REASON_BY_CODE.get(self.code, self.code)

    def as_dict(self) -> dict[str, str | None]:
        # Legacy keys (field/code/detail) retained for backward compat;
        # section_key + reason added for the aligned finalize contract.
        return {
            "field": self.field,
            "code": self.code,
            "detail": self.detail,
            "section_key": self.section_key,
            "reason": self.reason,
        }


def _field_type_of(tpl_section: object) -> str:
    """The section's field type as a plain string.

    ``TemplateDefinition`` carries a ``FieldType`` StrEnum, but the
    sprint-08 tests (and any legacy ad-hoc template) pass duck-typed
    objects without one — those default to free_text and keep their
    sprint-08 behaviour exactly.
    """
    raw = getattr(tpl_section, "field_type", "free_text")
    return str(getattr(raw, "value", raw))


def _typed_problem(
    *,
    field_type: str,
    section_key: str,
    body: object | None,
) -> FinalizeProblem | None:
    """Typed "filled" check for one required section. ``None`` ⇒ filled."""
    metadata: dict[str, object] = dict(getattr(body, "field_specific_metadata", {}) or {})

    if field_type in {"choice", "multi_choice"}:
        selected = metadata.get("selected")
        # Any source counts: the author saw the proposal and chose to
        # finalize, which is acceptance.
        if selected in (None, "", [], ()):
            return FinalizeProblem(
                field=f"sections.{section_key}.field_specific_metadata.selected",
                code="choice_not_selected",
                detail=f"section {section_key!r} requires a selection",
                section_key=section_key,
            )
        return None

    if field_type == "numeric_with_unit":
        if metadata.get("value") is None or not metadata.get("unit"):
            return FinalizeProblem(
                field=f"sections.{section_key}.field_specific_metadata.value",
                code="numeric_not_filled",
                detail=f"section {section_key!r} requires a value and a unit",
                section_key=section_key,
            )
        return None

    if field_type in {"date", "date_with_note"}:
        if not metadata.get("date"):
            return FinalizeProblem(
                field=f"sections.{section_key}.field_specific_metadata.date",
                code="date_not_filled",
                detail=f"section {section_key!r} requires a date",
                section_key=section_key,
            )
        return None

    return None


def validate_finalize(
    *,
    content: NoteContent,
    template: TemplateDefinition,
) -> list[FinalizeProblem]:
    problems: list[FinalizeProblem] = []

    by_key = {s.section_key: s for s in content.sections}
    for tpl_section in template.sections:
        # TemplateSection's key field is ``id`` (template_models.schema);
        # older ad-hoc definitions used ``key`` — accept both.
        section_key = getattr(tpl_section, "key", None) or tpl_section.id
        body = by_key.get(section_key)
        required = bool(getattr(tpl_section, "required", False))
        min_chars = int(getattr(tpl_section, "min_chars", 0) or 0)

        field_type = _field_type_of(tpl_section)

        # ── Sprint 13: typed sections measure completeness in metadata ──
        if field_type in _TYPED_FIELD_TYPES:
            if required:
                problem = _typed_problem(
                    field_type=field_type,
                    section_key=section_key,
                    body=body,
                )
                if problem is not None:
                    problems.append(problem)
            # date_with_note additionally holds prose: the note IS content,
            # so min_chars still applies to it when the author set one.
            if (
                field_type == "date_with_note"
                and body is not None
                and min_chars > 0
                and len(body.text.strip()) < min_chars
            ):
                problems.append(
                    FinalizeProblem(
                        field=f"sections.{section_key}.text",
                        code="below_min_chars",
                        detail=f"section {section_key!r} needs at least {min_chars} chars",
                        section_key=section_key,
                    )
                )
            continue

        if required and (body is None or len(body.text.strip()) == 0):
            problems.append(
                FinalizeProblem(
                    field=f"sections.{section_key}.text",
                    code="missing_required_section",
                    detail=f"section {section_key!r} is required",
                    section_key=section_key,
                )
            )
            continue
        if body is not None and min_chars > 0 and len(body.text.strip()) < min_chars:
            problems.append(
                FinalizeProblem(
                    field=f"sections.{section_key}.text",
                    code="below_min_chars",
                    detail=f"section {section_key!r} needs at least {min_chars} chars",
                    section_key=section_key,
                )
            )
    return problems
