"""Confirm/override audit signals for typed fields: the extractor's quality loop.
Payloads carry section key, field type and, for CLOSED vocabularies only, the
option slug; never free text (the audit chain is unerasable). Enforced by tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from note_models import NoteContent

# Field types whose values are closed vocabularies and therefore safe to record.
_CLOSED_VOCABULARY: frozenset[str] = frozenset({"choice", "multi_choice"})


@dataclass(frozen=True, slots=True)
class FieldAuditEvent:
    kind: Literal["confirmed", "overridden"]
    section_key: str
    field_type: str
    payload: dict[str, Any]


def _selected(metadata: dict[str, Any]) -> tuple[str, ...]:
    raw = metadata.get("selected")
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list | tuple):
        return tuple(str(v) for v in raw)
    return ()


def diff_field_events(
    *,
    before: NoteContent | None,
    after: NoteContent,
    field_types: dict[str, str],
) -> list[FieldAuditEvent]:
    """Compare two draft versions: **confirmed** (extracted → manual, same content)
    or **overridden** (a DIFFERENT manual value). ``field_types`` maps section_key → field_type."""
    events: list[FieldAuditEvent] = []
    old_by_key = {s.section_key: s for s in (before.sections if before else [])}

    for section in after.sections:
        field_type = field_types.get(section.section_key, "free_text")
        old = old_by_key.get(section.section_key)
        old_meta: dict[str, Any] = dict(getattr(old, "field_specific_metadata", {}) or {})
        new_meta: dict[str, Any] = dict(section.field_specific_metadata or {})

        safe = field_type in _CLOSED_VOCABULARY

        if not old_meta and not new_meta:
            continue

        old_source = old_meta.get("source")
        new_source = new_meta.get("source")
        if new_source != "manual":
            continue

        old_values, new_values = _selected(old_meta), _selected(new_meta)
        if old_source == "extracted":
            same = old_values == new_values
            kind: Literal["confirmed", "overridden"] = "confirmed" if same else "overridden"
            payload: dict[str, Any] = {}
            if safe:
                payload["selected"] = list(new_values)
                if not same:
                    payload["was"] = list(old_values)
            events.append(
                FieldAuditEvent(
                    kind=kind,
                    section_key=section.section_key,
                    field_type=field_type,
                    payload=payload,
                )
            )
    return events
