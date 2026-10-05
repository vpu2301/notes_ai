"""Line-level provenance (Summary Engine v2, Q1 T3).

Every written line of the document carries its kind and the fact ids it
rests on. Q1 added lines without changing a byte of the text (the
snapshot was then taken from the pre-Q1 renderer). Q3 changed the text on
purpose — one fact once, no single-bullet topics, time order, no
transcript note — and the snapshot was re-taken from the Q3 renderer
with the diff reviewed (``render_sections_q3.json``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from note_service.domain.meeting_doc import render, roles, schema
from note_service.domain.meeting_doc.verify import VerifiedFact

from .meeting_doc_fakes import spoken

SNAPSHOT = Path(__file__).parent / "snapshots" / "render_sections_q3.json"

ROLE_MAP = {
    "user_notes": roles.USER_NOTES,
    "agenda": roles.AGENDA,
    "decisions": roles.DECISIONS,
    "action_items": roles.ACTION_ITEMS,
}


def _fact(text: str, kind: str, start_ms: int, **kw: Any) -> VerifiedFact:
    base: dict[str, Any] = {
        "kind": kind,
        "text": text,
        "quote": spoken(text),
        "turn": start_ms // 1000,
        "start_ms": start_ms,
        "end_ms": start_ms + 4_000,
        "speaker_label": "SPEAKER_1",
        "speaker_name": None,
    }
    base.update(kw)
    return VerifiedFact(**base)


def snapshot_cases() -> dict[str, dict[str, Any]]:
    """The fixed inputs the snapshot was taken from. Old shapes only
    (bare bullet strings, bare summary sentences) — the shapes the
    pre-Q1 renderer accepted."""
    agenda = _fact("Review of the harbour ferry timetable", schema.AGENDA_ITEM, 1_000)
    decision = _fact(
        "The winter timetable starts on the first of the month", schema.DECISION, 9_000
    )
    action = _fact(
        "Publish the new timetable on the website",
        schema.ACTION,
        12_000,
        owner_label="Mira",
        due_text="by Friday",
    )
    unowned = _fact("Check the pier lighting", schema.ACTION, 15_000)
    question = _fact("Whether the night crossing continues", schema.OPEN_QUESTION, 20_000)
    risk = _fact("It was noted that fuel costs may rise", schema.RISK, 24_000)
    kp1 = _fact("Passenger numbers fell by 12 percent in August", schema.KEY_POINT, 30_000)
    kp2 = _fact("The second ferry returns from repair in October", schema.KEY_POINT, 34_000)
    kp3 = _fact("Ticket machines at the north pier are unreliable", schema.KEY_POINT, 38_000)
    facts = [agenda, decision, action, unowned, question, risk, kp1, kp2, kp3]

    ours = _fact("Send the revised offer", "commitment_ours", 5_000, owner_label="Ada", side="ours")
    theirs = _fact(
        "Sign the framework contract", "commitment_theirs", 8_000, owner_label="Ben", side="theirs"
    )
    loose = _fact("Share the reference list", "commitment_ours", 11_000)
    loose.side = None
    point = _fact("Die Laufzeit beträgt zwei Jahre", schema.KEY_POINT, 14_000)

    return {
        "topics_and_overview": {
            "facts": facts,
            "kwargs": {
                "role_by_key": ROLE_MAP,
                "topics": [
                    (
                        "Timetable",
                        [
                            "It was stated that the winter timetable starts soon.",
                            f"{kp2.item_key} (key_point, 00:34): echoed",
                            f"Machines fail often ({kp3.item_key}).",
                        ],
                        [decision.item_key],
                    ),
                    ("Passengers", ["Numbers fell in August."], [kp1.item_key]),
                    ("Empty", [], [kp1.item_key]),
                ],
                "summary": [
                    f"Passenger numbers fell by 12 percent ({kp1.item_key}).",
                    "The second ferry returns in October.",
                ],
                "framing": "A planning meeting about the harbour ferry.",
                "key_fact_ids": [kp1.item_key, "0000000000000000"],
                "language": "en",
            },
        },
        "overview_only": {
            "facts": [kp1, kp2, kp3, question],
            "kwargs": {
                "role_by_key": ROLE_MAP,
                "summary": ["Numbers fell."],
                "language": "en",
            },
        },
        "sided_actions_de": {
            "facts": [ours, theirs, loose, point],
            "kwargs": {
                "role_by_key": {},
                "language": "de",
                "counterpart": "Nordwind",
            },
        },
    }


def _render(case: dict[str, Any]) -> list[render.RenderedSection]:
    return render.render_sections(case["facts"], **case["kwargs"])


def _as_json(sections: list[render.RenderedSection]) -> list[dict[str, Any]]:
    return [
        {"section_key": s.section_key, "role": s.role, "title": s.title, "text": s.text}
        for s in sections
    ]


def test_render_output_matches_the_reviewed_snapshot() -> None:
    expected = json.loads(SNAPSHOT.read_text("utf-8"))
    for name, case in snapshot_cases().items():
        assert _as_json(_render(case)) == expected[name], name


def test_the_new_bullet_and_summary_shapes_render_the_same_text() -> None:
    """``(text, ids)`` bullets and sentences are what the pipeline now
    passes; the page must not change because of it."""
    case = snapshot_cases()["topics_and_overview"]
    kwargs = dict(case["kwargs"])
    kwargs["topics"] = [
        (title, [(b, list(ids)) for b in bullets], ids) for title, bullets, ids in kwargs["topics"]
    ]
    kwargs["summary"] = [(s, []) for s in kwargs["summary"]]
    new = render.render_sections(case["facts"], **kwargs)
    assert _as_json(new) == json.loads(SNAPSHOT.read_text("utf-8"))["topics_and_overview"]


def test_lines_are_the_section_text_line_by_line() -> None:
    for name, case in snapshot_cases().items():
        for section in _render(case):
            written = [line for line in section.text.split("\n") if line.strip()]
            assert [line.text for line in section.lines] == written, (name, section.section_key)
            assert all(line.kind in render.LINE_KINDS for line in section.lines)


def test_every_summary_bullet_and_framing_line_cites_a_fact() -> None:
    case = snapshot_cases()["topics_and_overview"]
    facts = case["facts"]
    kp1, kp2, kp3 = facts[6], facts[7], facts[8]
    extra = [_fact(f"Pier {n} gets new lights", schema.KEY_POINT, 50_000 + n) for n in range(2)]
    lines = [
        line
        for s in render.render_sections(
            [*facts, *extra],
            role_by_key=ROLE_MAP,
            framing="A planning meeting about the harbour ferry.",
            summary=[("Passenger numbers fell by 12 percent.", [kp1.item_key])],
            topics=[
                (
                    "Ferries",
                    [
                        f"{kp2.item_key} (key_point, 00:34): echoed",
                        f"Machines fail often ({kp3.item_key}).",
                    ],
                    [],
                ),
                ("Piers", [(f.text, [f.item_key]) for f in extra], []),
            ],
        )
        for line in s.lines
    ]
    kinds = {line.kind for line in lines}
    assert {"framing", "summary", "bullet", "decision", "action"} <= kinds
    for line in lines:
        if line.kind in ("framing", "summary", "bullet"):
            assert line.fact_ids, line
    # An echoed fact line and an inline id cite that fact, not just the topic.
    bullets = [line for line in lines if line.kind == "bullet"]
    assert kp2.item_key in bullets[0].fact_ids
    assert kp3.item_key in bullets[1].fact_ids


def test_a_fact_line_cites_its_own_fact() -> None:
    case = snapshot_cases()["sided_actions_de"]
    sections = _render(case)
    actions = next(s for s in sections if s.role == roles.ACTION_ITEMS)
    headings = [line for line in actions.lines if line.kind == "heading"]
    assert [h.text for h in headings] == [
        "### Wir übernehmen",
        "### Nordwind übernimmt",
        "### Noch zuzuordnen",
    ]
    for line, fact in zip(
        [line for line in actions.lines if line.kind == "action"], case["facts"][:3], strict=True
    ):
        assert line.fact_ids == (fact.item_key,)
    overview = sections[0]
    # Q3: no transcript note — every overview line rests on a fact.
    assert all(line.kind != "note" and line.fact_ids for line in overview.lines)
