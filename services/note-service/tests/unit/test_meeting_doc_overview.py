"""F3 amendment after r03 — the overview is prose and always written
(§2.9, A-10), a long recording whose topics fail is chaptered by time
(§2.6, A-6), and a long recording's topics come in two stages (§5, A-12).
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


def _run(meeting: dict, provider: ScriptedProvider) -> pipeline.DocumentResult:
    return asyncio.run(
        pipeline.run(
            as_result(meeting),
            provider=provider,
            role_by_key={},
            language="de",
            meeting_date=date(2026, 9, 22),
        )
    )


FAIL_ALL: dict[str, Any] = {
    "topics": lambda facts: {"topics": []},
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


def test_reduce_blocks_are_contiguous_and_bounded() -> None:
    facts = [_vf(f"Claim {n}", n * 20_000) for n in range(90)]  # 30 minutes, one window
    blocks = overview.reduce_blocks(facts)
    assert 2 <= len(blocks) <= overview.REDUCE_MAX_BLOCKS
    assert all(len(b) >= overview.REDUCE_MIN_BLOCK_FACTS for b in blocks)
    flat = [f for b in blocks for f in b]
    assert flat == sorted(facts, key=lambda f: f.start_ms)


# ── The pipeline ────────────────────────────────────────────────────


def _bullets_above_first_heading(document: pipeline.DocumentResult) -> int:
    first = document.sections[0]
    assert first.section_key == roles.OVERVIEW_KEY
    return sum(1 for line in first.text.splitlines() if re.match(r"^\s*[-*] ", line))


def test_every_model_pass_failing_still_writes_prose_and_chapters() -> None:
    document = _run(_recording(40), ScriptedProvider(overrides=FAIL_ALL))  # 13 minutes
    assert document.stats["summary_ladder"] == "composed"
    assert document.stats["topics_fallback"] == "chapters"
    assert document.stats["topics_failure"] in ("too_few_topics", "all_bullets_unsupported")
    top = document.sections[0]
    paragraphs = top.text.split("\n\n")
    assert len(paragraphs) == 2
    assert len(paragraphs[1].splitlines()) >= 3
    assert all(line.fact_ids for line in top.lines)
    assert _bullets_above_first_heading(document) == 0
    # A chapter whose facts the composed prose already says gives its
    # remaining bullets to the next one (render's redundancy rule).
    chapters = [s for s in document.sections if s.role == roles.TOPICS]
    assert len(chapters) >= 2
    assert all(re.match(r"^\d\d:\d\d( — .+)?$", s.title or "") for s in chapters)


def test_a_short_recording_is_not_chaptered() -> None:
    document = _run(_recording(20), ScriptedProvider(overrides=FAIL_ALL))  # under 7 minutes
    assert document.stats["topics_fallback"] is None
    assert not [s for s in document.sections if s.role == roles.TOPICS]
    assert _bullets_above_first_heading(document) == 0


def test_the_model_summary_is_the_second_paragraph_and_speakers_stay_code() -> None:
    document = _run(_recording(12, voices=("SPEAKER_1",)), ScriptedProvider())
    assert document.stats["summary_ladder"] == "model"
    top = document.sections[0]
    first, second = top.text.split("\n\n")
    assert "Es sprechen Erzähler/in." in first
    assert [line.kind for line in top.lines if line.text in second.splitlines()] == [
        "summary"
    ] * len(second.splitlines())


def test_two_unnamed_voices_sharing_the_talk_are_not_a_narrator() -> None:
    document = _run(_recording(12), ScriptedProvider())
    assert "Erzähler" not in document.sections[0].text


def test_a_long_recording_asks_for_topics_block_by_block_and_merges_same_headings() -> None:
    def block(facts: list[tuple[str, str, str]]) -> dict:
        found = [m[1] for _i, _k, t in facts if (m := re.search(r"traf (.+?) in", t))]
        name = max(set(found), key=found.count) if found else "Daten"
        return {
            "topics": [
                {
                    "title": f"{name} und die Investoren",
                    "fact_ids": [i for i, _k, _t in facts],
                    "bullets": [{"text": t, "fact_ids": [i]} for i, _k, t in facts[:3]],
                }
            ]
        }

    provider = ScriptedProvider(overrides={"topics": block})
    document = _run(_recording(100), provider)  # 33 minutes, > 40 facts
    assert len(document.facts) > pipeline.TWO_STAGE_MIN_FACTS
    calls = [c for c in provider.calls if c[0] == "topics"]
    assert 2 <= len(calls) <= overview.REDUCE_MAX_BLOCKS
    assert document.stats["topics_fallback"] is None
    titles = [s.title for s in document.sections if s.role == roles.TOPICS]
    assert len(titles) >= 2
    # Neighbouring blocks with the same heading are one topic.
    assert all(a != b for a, b in zip(titles, titles[1:], strict=False))
