"""The client version: the one shape that may leave the workspace, built by an
allow-list of roles (never keys). `user_notes` and `transcript` never appear;
`(internal)` lines are dropped; a family with no client produces nothing. Pure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from note_models import NoteContent

from . import lines as line_rules
from .meeting_doc import types

# What a client may see, in reading order; everything else is internal by omission.
CLIENT_ROLES: Final[tuple[str, ...]] = (
    types.SUMMARY,
    types.ATTENDEES,
    types.AGENDA,
    types.DECISIONS,
    types.TOPICS,
    types.SPECIFICATIONS,
    types.REQUESTS,
    types.ACTION_ITEMS,
    types.OPEN_QUESTIONS,
    types.NEXT_MEETING,
)

# Never, in any family, whatever role a template claims for them.
NEVER: Final[frozenset[str]] = frozenset({types.USER_NOTES, types.TRANSCRIPT})

# "Anna: we ship Friday" — one transcript turn.
_TURN = re.compile(r"^(?!https?:)[^\s*_`:][^*_`:]{0,39}?:\s+\S")


def looks_like_transcript(text: str) -> bool:
    """Whether a section IS a transcript, whatever slot it sits in (`from-transcript`
    parks the recording in the first prose section)."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) < 2:
        return False
    turns = sum(1 for p in paragraphs if _TURN.match(p))
    return turns * 10 >= len(paragraphs) * 6


@dataclass(frozen=True, slots=True)
class ClientSection:
    section_key: str
    role: str
    name: str
    text: str


@dataclass(frozen=True, slots=True)
class ClientDocument:
    title: str
    sections: tuple[ClientSection, ...]
    """Lines dropped because the author marked them internal. A count, for
    the preview to say "3 internal lines hidden" — never the lines."""
    hidden_lines: int
    """Sections dropped whole: `user_notes`, the transcript, anything whose
    role is not in :data:`CLIENT_ROLES`. Keys only, for the checklist."""
    hidden_sections: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return not self.sections


def build(
    content: NoteContent,
    *,
    family: types.Family,
    section_names: dict[str, str] | None = None,
    internal_keys: frozenset[str] = frozenset(),
) -> ClientDocument:
    """The document a client may receive; all-internal sections give an empty document."""
    if not types.supports_client_version(family):
        # No client version at all for this family.
        return ClientDocument(
            title=content.title,
            sections=(),
            hidden_lines=0,
            hidden_sections=tuple(s.section_key for s in content.sections),
        )

    names = section_names or {}
    kept: list[ClientSection] = []
    hidden_sections: list[str] = []
    hidden_lines = 0

    by_role = {role: i for i, role in enumerate(CLIENT_ROLES)}
    for section in content.sections:
        role = types.role_of(section.section_key)
        if role in NEVER or role not in by_role or looks_like_transcript(section.text or ""):
            if (section.text or "").strip():
                hidden_sections.append(section.section_key)
            continue
        text, dropped = public_text(section.text or "", internal_keys=internal_keys)
        hidden_lines += dropped
        if not text.strip():
            # Emptied by the internal marks, or empty to begin with.
            if (section.text or "").strip():
                hidden_sections.append(section.section_key)
            continue
        kept.append(
            ClientSection(
                section_key=section.section_key,
                role=role,
                # An untitled engine block: no heading, never its key.
                name=names.get(
                    section.section_key,
                    "" if section.section_key.startswith("gen:") else section.section_key,
                ),
                text=text,
            )
        )

    kept.sort(key=lambda s: by_role[s.role])
    return ClientDocument(
        title=content.title,
        sections=tuple(kept),
        hidden_lines=hidden_lines,
        hidden_sections=tuple(hidden_sections),
    )


def public_text(text: str, *, internal_keys: frozenset[str] = frozenset()) -> tuple[str, int]:
    """A section's text without its internal lines (marked ``(internal)`` or in
    `internal_keys`), and how many went; blank lines between kept lines survive."""
    if not text.strip():
        return text, 0
    out: list[str] = []
    dropped = 0
    for raw in text.splitlines():
        if not raw.strip():
            if out and out[-1].strip():
                out.append(raw)
            continue
        marker, content = line_rules.strip_marker(raw)
        bare, internal = line_rules.strip_internal(content)
        if not internal and internal_keys and bare:
            internal = line_rules.key_of(bare) in internal_keys
        if internal or not bare:
            dropped += 1 if internal else 0
            continue
        # The mark never renders.
        out.append(f"{marker}{bare}" if marker else bare)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out), dropped
