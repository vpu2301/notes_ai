"""The terminology post-pass (N2 T4): composed lines only, never a quote or a name."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from note_service.domain import note_instructions as ni
from note_service.domain.meeting_doc import roles
from note_service.domain.meeting_doc.render import Line, RenderedSection


@dataclass
class Doc:
    sections: list[RenderedSection]
    stats: dict[str, Any] = field(default_factory=dict)


def _section(
    lines: list[Line], role: str = roles.TOPICS, title: str | None = "Reviews"
) -> RenderedSection:
    return RenderedSection(
        "gen:reviews", role, "\n".join(ln.text for ln in lines), title=title, lines=tuple(lines)
    )


def _profile(*pairs: tuple[str, str]) -> ni.WritingProfile:
    return ni.WritingProfile.model_validate(
        {"terminology": [{"use": u, "instead_of": i} for u, i in pairs]}
    )


PR = _profile(("PR", "pull request"))


def test_a_bullet_and_the_section_text_are_rewritten_with_the_flag() -> None:
    doc = Doc([_section([Line("- Pull request for the export merged", "bullet", ("f1",))])])
    doc.stats["instructions_applied"] = {}
    assert ni.apply_terminology(doc, PR, known=frozenset()) == 1
    line = doc.sections[0].lines[0]
    assert line.text == "- PR for the export merged"
    assert doc.sections[0].text == "- PR for the export merged"
    assert ni.TERM_REPLACED in line.flags
    assert doc.stats["instructions_applied"]["terms_replaced"] == 1


def test_case_is_preserved_for_a_lower_case_use() -> None:
    doc = Doc([_section([Line("- Release notes are due", "bullet", ("f1",))])])
    ni.apply_terminology(doc, _profile(("changelog", "release notes")), known=frozenset())
    assert doc.sections[0].lines[0].text == "- Changelog are due"


def test_a_quote_line_is_untouched() -> None:
    quote = Line("  - „we merged the pull request“", "quote", ("f1",))
    doc = Doc([_section([Line("- A pull request", "bullet", ("f1",)), quote])])
    assert ni.apply_terminology(doc, PR, known=frozenset()) == 1
    assert doc.sections[0].lines[1] is quote
    assert "„we merged the pull request“" in doc.sections[0].text


def test_a_pair_sharing_a_word_with_a_known_name_is_never_applied() -> None:
    line = Line("- Pull Requester GmbH reviewed the pull request", "bullet", ("f1",))
    doc = Doc([_section([line])])
    doc.stats["instructions_applied"] = {}
    assert ni.apply_terminology(doc, PR, known=frozenset({"Pull Requester GmbH"})) == 0
    assert doc.sections[0].lines[0] is line
    assert doc.stats["instructions_applied"]["terms_skipped"] == 1


def test_inside_a_longer_word_is_not_a_match() -> None:
    line = Line("- Pull Requester GmbH sent it", "bullet", ("f1",))
    doc = Doc([_section([line])])
    assert ni.apply_terminology(doc, PR, known=frozenset()) == 0


def test_transcript_and_user_notes_are_untouched() -> None:
    for role in (roles.TRANSCRIPT, roles.USER_NOTES):
        doc = Doc([_section([Line("- a pull request", "bullet", ("f1",))], role=role)])
        assert ni.apply_terminology(doc, PR, known=frozenset()) == 0


def test_the_empty_profile_does_not_touch_the_document() -> None:
    sections = [_section([Line("- a pull request", "bullet", ("f1",))])]
    doc = Doc(list(sections))
    assert ni.apply_terminology(doc, ni.EMPTY, known=frozenset()) == 0
    assert all(a is b for a, b in zip(doc.sections, sections, strict=True))
    assert doc.stats == {}


def test_no_quote_and_no_line_with_a_known_name_changes_under_random_pairs() -> None:
    """Acceptance 4: random pairs drawn from the lines' own words."""
    rng = random.Random(18)
    names = frozenset({"Anna Weber", "Quill Haven"})
    texts = [
        "- Anna Weber sends the pricing proposal by Tuesday",
        "- The print run moves to the second week",
        "- Quill Haven confirms the reprint budget",
    ]
    quotes = ["  - „the pricing proposal is late“", "  - „Anna Weber agreed“"]
    for _ in range(200):
        words = [w for t in texts for w in t.split() if w.isalpha()]
        pair = (rng.choice(words).lower() + "x", rng.choice(words))
        lines = [Line(t, "bullet", ("f",)) for t in texts] + [
            Line(q, "quote", ("f",)) for q in quotes
        ]
        doc = Doc([_section(lines)])
        ni.apply_terminology(doc, _profile(pair), known=names)
        after = doc.sections[0].lines
        for before, now in zip(lines, after, strict=True):
            if before.kind == "quote" or any(n.split()[0] in before.text for n in names):
                assert now.text == before.text
