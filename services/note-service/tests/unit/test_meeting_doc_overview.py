"""The overview is prose and always written; a long recording whose topics fail
is chaptered by time; a long recording's topics come in two stages.
"""

from __future__ import annotations

import asyncio
import dataclasses
import re
from datetime import date
from typing import Any

from note_service.domain import client_view
from note_service.domain.meeting_doc import overview, pipeline, roles, schema
from note_service.domain.meeting_doc.verify import VerifiedFact

from .meeting_doc_fakes import ScriptedProvider, as_result, spoken

NAMES = ["Peter Thiel", "Alex Karp", "PayPal", "Palantir", "Habermas", "Stanford"]


def _vf(text: str, start_ms: int, *, window: int = 0) -> VerifiedFact:
    return VerifiedFact(
        kind=schema.KEY_POINT,
        text=text,
        quote=spoken(text),
        turn=0,
        start_ms=start_ms,
        end_ms=start_ms + 1_000,
        speaker_label="SPEAKER_1",
        speaker_name=None,
        window_index=window,
    )


def _recording(turns: int, *, voices: tuple[str, ...] = ("SPEAKER_1", "SPEAKER_2")) -> dict:
    """A German recording, 20 s a turn, each turn a checkable claim."""
    transcript = []
    for n in range(turns):
        who = NAMES[(n // 6) % len(NAMES)]
        transcript.append(
            {
                "speaker": voices[n % len(voices)],
                "t_start_ms": n * 20_000,
                "t_end_ms": n * 20_000 + 19_000,
                "text": f"Im Jahr {2000 + n} traf {who} in Kalifornien genau {n + 3} "
                "Investoren aus dem Silicon Valley und sprach lange über Daten",
            }
        )
    return {"language": "de", "transcript": transcript}


def _run(meeting: dict, provider: ScriptedProvider, **kw: Any) -> pipeline.DocumentResult:
    return asyncio.run(
        pipeline.run(
            as_result(meeting),
            provider=provider,
            role_by_key={},
            language="de",
            meeting_date=date(2026, 9, 22),
            **kw,
        )
    )


FAIL_ALL: dict[str, Any] = {
    # Every block's call answers nothing usable.
    "block": lambda facts: {"heading": "", "bullets": []},
    "summary": lambda facts: {"summary": []},
}


# ── §2.9 paragraph 1: what this is, composed by code ────────────────


def test_the_first_paragraph_names_type_subject_speakers_guest_and_themes() -> None:
    text = overview.first_paragraph(
        language="de",
        recording_type="podcast_broadcast",
        subject="Palantir",
        speakers=[overview.NARRATOR["de"]],
        guests=["Felix Holtermann (Handelsblatt)"],
        themes=["der 11. September", "die Gründung von Palantir", "Alex Karp", "Überwachung"],
    )
    assert text.startswith("Podcast-Folge über Palantir.")
    assert "Erzähler/in und als Gast Felix Holtermann (Handelsblatt)" in text
    assert (
        "Themen sind der 11. September, die Gründung von Palantir, Alex Karp und Überwachung."
        in text
    )


def test_a_gated_model_framing_replaces_only_the_first_clause() -> None:
    text = overview.first_paragraph(
        language="en",
        recording_type="podcast_broadcast",
        subject="Palantir",
        framing="An episode on how Palantir began",
        speakers=["Mitchell"],
    )
    assert text == "An episode on how Palantir began. With Mitchell."


def test_the_first_paragraph_never_reads_as_a_transcript() -> None:
    """A "Label: text" line is what a transcript turn looks like; the
    client version and the shared page would take the overview for one."""
    for language in ("en", "de", "uk"):
        text = overview.first_paragraph(
            language=language,
            recording_type="interview",
            subject="x",
            speakers=["Ada", "Ben"],
            guests=["Cleo"],
            themes=["a", "b"],
        )
        summary = "\n".join(
            s
            for s, _ids in overview.composed_sentences(
                [_vf(f"Claim number {n} holds", n * 1_000) for n in range(4)], language=language
            )
        )
        assert ":" not in text
        assert not client_view.looks_like_transcript(f"{text}\n\n{summary}"), language


# ── §2.9 paragraph 2, ladder rung 3: composed prose ─────────────────


def test_composed_prose_is_three_to_six_cited_sentences_in_time_order() -> None:
    facts = [
        _vf(f"Im Jahr {2000 + n} gründet Peter Thiel Firma {n}", (9 - n) * 60_000) for n in range(9)
    ]
    out = overview.composed_sentences(facts, language="de")
    assert 3 <= len(out) <= 6
    by_id = {f.item_key: f for f in facts}
    starts = [by_id[ids[0]].start_ms for _s, ids in out]
    assert starts == sorted(starts)
    assert all(len(ids) == 1 for _s, ids in out)
    assert out[0][0].startswith("Zunächst — ")
    assert out[-1][0].startswith("Schließlich — ")
    assert all(s.endswith(".") for s, _ids in out)


def test_composed_prose_takes_the_named_key_facts_first() -> None:
    facts = [_vf(f"Fact {n} about Palantir in {2000 + n}", n * 60_000) for n in range(8)]
    keys = [facts[6].item_key, facts[1].item_key, facts[4].item_key]
    out = overview.composed_sentences(facts, language="en", key_ids=keys)
    assert [ids[0] for _s, ids in out] == [facts[1].item_key, facts[4].item_key, facts[6].item_key]


def test_composed_prose_never_uses_evidence() -> None:
    fact = _vf("I think so", 0)
    fact = dataclasses.replace(fact, copied=True)
    assert fact.evidence_only
    assert overview.composed_sentences([fact], language="en") == []


# ── §2.6 chapters and A-12 blocks ────────────────────────────────────


def test_chapters_are_time_spans_headed_by_what_that_span_names() -> None:
    facts = [
        _vf(f"In {2000 + n} {NAMES[n // 4]} met {n + 3} investors about Data", n * 60_000)
        for n in range(12)
    ]
    out = overview.chapters(facts, language="en")
    assert [title for title, _b, _ids in out] == [
        "00:00 — Peter Thiel",
        "03:00 — Alex Karp",
        "06:00 — Alex Karp",
        "09:00 — PayPal",
    ]
    # "Data" is in every span: the recording's subject, not a chapter's.
    assert all("Data" not in title for title, _b, _ids in out)
    assert all(len(ids) >= overview.CHAPTER_MIN_FACTS for _t, _b, ids in out)


def test_a_chapter_writes_a_fact_that_names_nothing_only_when_nothing_else_does() -> None:
    specific = [_vf(f"Palantir hires {n + 10} people", n * 1_000) for n in range(3)]
    vague = _vf("It was a strange time for everyone", 4_000)
    [(_title, bullets, ids)] = overview.chapters([*specific, vague], language="en")
    assert vague.text not in [b for b, _i, _c in bullets]
    assert vague.item_key in ids
    only_vague = [_vf(f"It was a strange time {w}", n * 1_000) for n, w in enumerate("abc")]
    [(_title, bullets, _ids)] = overview.chapters(only_vague, language="en")
    assert len(bullets) == 3


# ── The pipeline ────────────────────────────────────────────────────


def _bullets_above_first_heading(document: pipeline.DocumentResult) -> int:
    first = document.sections[0]
    assert first.section_key == roles.OVERVIEW_KEY
    return sum(1 for line in first.text.splitlines() if re.match(r"^\s*[-*] ", line))


def test_every_model_pass_failing_still_writes_prose_and_chapters() -> None:
    document = _run(_recording(40), ScriptedProvider(overrides=FAIL_ALL))  # 13 minutes
    assert document.stats["summary_ladder"] == "composed"
    assert document.stats["topics_fallback"] == "chapters"
    # Parts come from the transcript; a part with fewer than two
    # facts joins its neighbour, so a 13-minute recording may have two.
    assert document.stats["block_chapters"] == document.stats["blocks"] >= 2
    top = document.sections[0]
    paragraphs = top.text.split("\n\n")
    assert len(paragraphs) == 2
    assert len(paragraphs[1].splitlines()) >= 3
    assert all(line.fact_ids for line in top.lines)
    assert _bullets_above_first_heading(document) == 0
    chapters = [s for s in document.sections if s.role == roles.TOPICS]
    assert len(chapters) >= 2
    assert all(re.match(r"^\d\d:\d\d( — .+)?$", s.title or "") for s in chapters)


def test_a_failed_block_is_its_chapter_at_any_length() -> None:
    """A block whose call
    fails twice renders its facts by time under its name and time."""
    document = _run(_recording(20), ScriptedProvider(overrides=FAIL_ALL))  # under 7 minutes
    assert document.stats["block_calls"] == 2 * document.stats["blocks"]
    assert _bullets_above_first_heading(document) == 0


def test_the_model_summary_is_the_second_paragraph_and_speakers_stay_code() -> None:
    from note_service.domain.meeting_doc import types

    document = _run(
        _recording(12, voices=("SPEAKER_1",)),
        ScriptedProvider(),
        family=types.family_for_recording_type("podcast_broadcast"),
        recording_type="podcast_broadcast",
    )
    assert document.stats["summary_ladder"] == "model"
    top = document.sections[0]
    first, second = top.text.split("\n\n")
    assert "Es sprechen Erzähler/in." in first
    assert [line.kind for line in top.lines if line.text in second.splitlines()] == [
        "summary"
    ] * len(second.splitlines())


def test_a_meeting_names_nobody_by_role() -> None:
    """Decision 5: a meeting has participants, named only when verified."""
    document = _run(_recording(12, voices=("SPEAKER_1",)), ScriptedProvider())
    assert "Erzähler" not in document.sections[0].text


def test_two_unnamed_voices_sharing_the_talk_are_not_a_narrator() -> None:
    document = _run(_recording(12), ScriptedProvider())
    assert "Erzähler" not in document.sections[0].text


def test_a_long_recording_asks_block_by_block_and_merges_only_within_the_band() -> None:
    def block(facts: list[tuple[str, str, str]]) -> dict:
        found = [m[1] for _i, _k, t in facts if (m := re.search(r"traf (.+?) in", t))]
        name = max(set(found), key=found.count) if found else "Daten"
        return {
            "heading": f"{name} und die Investoren in Kalifornien",
            "bullets": [{"text": t, "fact_ids": [i]} for i, _k, t in facts[:3]],
        }

    def merge(_facts: list) -> dict:
        return {"merges": [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 6], [6, 7]]}

    provider = ScriptedProvider(overrides={"block": block, "merge": merge})
    document = _run(_recording(100), provider)  # 33 minutes
    calls = [c for c in provider.calls if c[0] == "block"]
    # The transcript gives 8 parts; parts the facts leave under two
    # are merged into a neighbour (counted), so at least five remain here.
    assert len(calls) == document.stats["blocks"] >= 5
    assert document.stats["blocks_boundaries"] == 7
    assert [c for c in provider.calls if c[0] == "merge"]
    assert document.stats["topics_fallback"] is None
    titles = [s.title for s in document.sections if s.role == roles.TOPICS]
    # Every proposed merge would have gone under the band: most are refused.
    assert document.stats["merges_refused"] >= 1
    assert len(titles) >= 5


# ── §2.10 the support gate per language ─────────────────────────────


def test_a_compound_is_supported_by_its_parts() -> None:
    from note_service.domain.meeting_doc import support

    claim = "Geheimdienstdaten fließen zusammen"
    evidence = "die Daten der Dienste fließen zusammen"
    assert support.support_ratio(claim, evidence, "de") == 1.0
    # A five-letter stem alone would not have found it.
    assert support._stem("geheimdienstdaten") not in {support._stem(w) for w in evidence.split()}
    # Words that share no run of six letters are still new.
    assert support.support_ratio("Waffenlieferungen stocken", evidence, "de") == 0.0


def test_the_line_gate_threshold_is_per_language() -> None:
    from note_service.domain.meeting_doc import support

    assert support.line_support_threshold("en") == 0.5
    assert support.line_support_threshold("de") == 0.4
    assert support.line_support_threshold("uk") == 0.4
    assert support.line_support_threshold("fr") == support.LINE_SUPPORT_DEFAULT


def test_introductions_sit_in_the_first_paragraph_and_never_read_as_turns() -> None:
    """Who presented and who was a guest are named once, inside
    "Es sprechen …" — no "Gast: X" paragraph, which every client would draw
    as a transcript turn."""
    from note_service.domain.meeting_doc import compose, render, roles_table, verify

    def person(name: str, self_intro: bool) -> verify.Person:
        return verify.Person(
            name=name,
            role="Reporterin",
            organisation="Handelsblatt",
            self_introduction=self_intro,
            joiner="beim",
        )

    table = roles_table.RolesTable(
        speakers={
            "SPEAKER_0": roles_table.Speaker(
                "SPEAKER_0", 0.6, 40, 0.1, roles_table.NARRATOR, "Anna Berg", person("Anna Berg", True)
            ),
            "SPEAKER_1": roles_table.Speaker(
                "SPEAKER_1", 0.3, 20, 0.4, roles_table.GUEST, "Felix Holtermann",
                person("Felix Holtermann", False),
            ),
        }
    )  # fmt: skip
    framing = compose.orientation_p1(
        language="de", recording_type="podcast_broadcast", table=table, subject="Palantir"
    )
    point = _vf("Palantir wurde im Jahr 2004 gegründet", 9_000)
    [top, *_rest] = render.render_sections(
        [point],
        role_by_key={},
        language="de",
        framing=framing,
        summary=[("Palantir wurde 2004 gegründet.", [point.item_key])],
        presenter_lines=True,
    )
    paragraphs = top.text.split("\n\n")
    assert len(paragraphs) == 2
    assert paragraphs[0].startswith("Podcast-Folge über Palantir.")
    assert "Anna Berg (Reporterin beim Handelsblatt)" in paragraphs[0]
    assert "als Gast Felix Holtermann (Reporterin beim Handelsblatt)" in paragraphs[0]
    assert "Gast:" not in top.text
    assert not client_view.looks_like_transcript(top.text)


def test_default_speaker_names_are_nobody() -> None:
    from note_service.domain.meeting_doc import compose, roles_table
    from note_service.domain.meeting_doc.windows import Turn

    turns = [
        Turn(0, "SPEAKER_1", "Speaker 1", "Erzählung", 0, 50_000),
        Turn(1, "UNKNOWN", "UNKNOWN", "Werbung", 50_000, 52_000),
        Turn(2, "SPEAKER_2", "Speaker 2", "Antwort", 52_000, 60_000),
    ]
    table = roles_table.build(turns, [], "podcast_broadcast")
    # The second voice speaks enough to be listed — unnamed, as a
    # person, never as its label.
    assert compose.speakers_of(table, "de") == (["Erzähler/in"], [], ["eine weitere Person"])
    named = [
        *turns,
        *(
            Turn(
                3 + n, "SPEAKER_3", "Ada Lovelace", "Hallo", 60_000 + n * 5_000, 64_000 + n * 5_000
            )
            for n in range(3)
        ),
    ]
    table = roles_table.build(named, [], "meeting")
    listed = [w for part in compose.speakers_of(table, "de") for w in part]
    assert "Ada Lovelace" in listed
    assert all("Speaker" not in s for s in listed)


def test_composed_prose_passes_over_a_part_that_names_nothing() -> None:
    facts = [
        _vf("The sky is clear over the towers", 0),
        _vf("It is a quiet morning", 60_000),
        _vf("Peter Thiel founds Palantir in 2004", 120_000),
        _vf("Palantir hires 3000 people", 180_000),
        _vf("Alex Karp becomes CEO in 2004", 240_000),
    ]
    out = overview.composed_sentences(facts, language="en", known=frozenset(NAMES))
    assert [ids[0] for _s, ids in out] == [f.item_key for f in facts[2:]]


def test_an_echoed_field_name_never_reaches_a_line() -> None:
    from note_service.domain.meeting_doc import render

    for echoed in (
        "Nach 9-11 steht das Land unter Schock. (fact_id:",
        "Nach 9-11 steht das Land unter Schock. fact_ids:",
        "Nach 9-11 steht das Land unter Schock. (fact ids)",
    ):
        assert render.strip_inline_ids(echoed)[0] == "Nach 9-11 steht das Land unter Schock."


def test_composed_prose_never_uses_a_fact_its_words_do_not_carry() -> None:
    from note_service.domain.meeting_doc.verify import PARAPHRASE_UNSUPPORTED

    facts = [_vf(f"Palantir hires {n + 10} people in {2000 + n}", n * 60_000) for n in range(4)]
    facts[0] = dataclasses.replace(facts[0], flags=(PARAPHRASE_UNSUPPORTED,))
    out = overview.composed_sentences(facts, language="en")
    assert facts[0].item_key not in {ids[0] for _s, ids in out}
