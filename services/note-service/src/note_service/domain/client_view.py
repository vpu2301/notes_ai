"""The client version: the one shape that may leave the workspace.

Until now every external surface — the shared page and the PDF — rendered
whatever sections the note happened to have. That was already wrong for
the transcript, and it became a disclosure the moment Sprint 34 gave every
template a `user_notes` section: the author's private in-meeting
scratchpad ("ask about budget", "Tom is stalling") was rendered to
recipients along with everything else.

So external rendering stops being "the note minus a few things" and
becomes its own document, built by an allow-list:

* sections are chosen **by role**, not by key — a key like `objections`
  means nothing outside a sales call, but `decisions` means the same
  everywhere, and a template we have never seen cannot smuggle a section
  in by naming it something new;
* the roles that may appear are fixed and ordered here;
* `user_notes` and `transcript` can never appear, in any family;
* a line marked `(internal)` is dropped, and its mark never renders;
* a family with no client (a 1:1, an interview debrief) produces nothing
  at all.

Pure: content in, document out. Nothing here reads the database, so the
shared page, the PDF and the preview cannot drift from each other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from note_models import NoteContent

from . import lines as line_rules
from .meeting_doc import types

# What a client may see, in the order they read it. Everything else —
# including every role not named here — is internal by omission, which is
# the direction a mistake should fail in.
CLIENT_ROLES: Final[tuple[str, ...]] = (
    types.SUMMARY,
    types.ATTENDEES,
    types.AGENDA,
    types.DECISIONS,
    types.TOPICS,
    # F3 — the figures a meeting gave (budget numbers, specifications).
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
    """Whether a section IS a transcript, whatever slot it sits in.

    This matters more than the slot's name: until the generation engine
    lands, `from-transcript` and `attach_transcript` drop the whole
    transcript into the first prose section — usually `discussion`. A
    client document that trusted section keys alone would hand a
    recipient the entire recording under the heading "Discussion".
    """
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
    """The document a client may receive.

    Raises nothing and invents nothing: a note whose sections are all
    internal produces an empty document, and the caller decides what to
    say about that.
    """
    if not types.supports_client_version(family):
        # A 1:1 or an interview debrief has no client version at all, and
        # returning "everything internal" instead of refusing would invite
        # a caller to render the empty shell as if it were a document.
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
                # An engine-made block without a title is read as the
                # document itself: no heading, never its key.
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
    """A section's text without its internal lines, and how many went.

    Two ways a line is internal: the author marked it ``(internal)``, or
    the engine wrote it from a kind that never leaves the workspace — an
    objection, a competitor mention, what we think of a candidate
    (`internal_keys`, by `item_key`).

    Blank lines between kept lines are preserved so the section still
    reads as it was written; a paragraph that loses every line loses its
    blank lines with it.
    """
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
        # The mark never renders, even when it was not internal: a line
        # reading "(internal) …" to a client would be worse than the leak.
        out.append(f"{marker}{bare}" if marker else bare)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out), dropped
