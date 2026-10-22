"""The segment gates rule by rule; the rollback switch; no content in diagnostics."""

from __future__ import annotations

import json
from typing import Any

import pytest

from asr_models import (
    Diagnostics,
    Segment,
    SegmentDiagnostics,
    TranscriptionMetadata,
    TranscriptionOutput,
    WordTiming,
)
from asr_worker import guards
from asr_worker.config import settings
from asr_worker.vad import SpeechSegment


def _seg(start: int, text: str, *, ms_per_word: int = 300, prob: float = 0.9) -> Segment:
    words = []
    t = start
    for w in text.split():
        words.append(WordTiming(text=w, start_ms=t, end_ms=t + ms_per_word - 20, probability=prob))
        t += ms_per_word
    return Segment(
        text=text, start_ms=start, end_ms=max(t, start + 1), words=words, avg_confidence=prob
    )


def _out(
    segments: list[Segment], diags: list[SegmentDiagnostics] | None = None
) -> TranscriptionOutput:
    return TranscriptionOutput(
        language="de",
        segments=segments,
        metadata=TranscriptionMetadata(
            model="t", vad_seconds_speech=0, infer_seconds=0, beam_size=1
        ),
        diagnostics=Diagnostics(segments=diags or []),
    )


def _d(seg: Segment, **numbers: float) -> SegmentDiagnostics:
    return SegmentDiagnostics(start_ms=seg.start_ms, end_ms=seg.end_ms, **numbers)


SILENCE: list[SpeechSegment] = []


def _speech_over(seg: Segment) -> list[SpeechSegment]:
    return [SpeechSegment(seg.start_ms, seg.end_ms)]


@pytest.fixture(autouse=True)
def _enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "asr_gates_enabled", True)


# ── G1 ───────────────────────────────────────────────────────────────


def test_g1_drops_text_over_silence_the_decoder_calls_no_speech() -> None:
    seg = _seg(1000, "Ich danke Ihnen")
    out = guards.apply(_out([seg], [_d(seg, no_speech_prob=0.9, avg_logprob=-1.4)]), SILENCE).output
    assert out.segments == []
    (drop,) = out.diagnostics.dropped_segments
    assert (drop.reason, drop.no_speech_prob, drop.speech_share, drop.dry_run) == (
        "no_speech",
        0.9,
        0.0,
        False,
    )


def test_g1_keeps_the_same_segment_where_vad_heard_speech() -> None:
    seg = _seg(1000, "Ich danke Ihnen")
    speech = [SpeechSegment(seg.start_ms, seg.start_ms + int(0.8 * (seg.end_ms - seg.start_ms)))]
    out = guards.apply(_out([seg], [_d(seg, no_speech_prob=0.9, avg_logprob=-1.4)]), speech).output
    assert out.segments == [seg] and out.diagnostics.dropped_segments == []


def test_g1_keeps_a_confident_segment() -> None:
    seg = _seg(1000, "Ich danke Ihnen")
    out = guards.apply(_out([seg], [_d(seg, no_speech_prob=0.9, avg_logprob=-0.2)]), SILENCE).output
    assert out.segments == [seg]


def test_g1_without_the_decoders_figure_rests_on_vad_alone() -> None:
    seg = _seg(1000, "Ich danke Ihnen")
    out = guards.apply(_out([seg]), SILENCE).output
    assert out.segments == []
    assert out.diagnostics.gate_unavailable["no_speech_prob"] == 1


# ── G2 ───────────────────────────────────────────────────────────────


def test_g2_a_two_gram_repeated_six_times_is_cut_after_two() -> None:
    seg = _seg(0, "vielen dank " * 6)
    result = guards.apply(_out([seg]), _speech_over(seg))
    (kept,) = result.output.segments
    assert kept.text == "vielen dank vielen dank"
    assert result.loop_ranges == [(seg.start_ms, seg.end_ms)], "the range goes to the second pass"
    (drop,) = result.output.diagnostics.dropped_segments
    assert drop.reason == "loop" and drop.start_ms == seg.words[4].start_ms


def test_g2_identical_segments_in_a_row_keep_two() -> None:
    segs = [_seg(k * 2000, "Vielen Dank.") for k in range(5)]
    result = guards.apply(_out(segs), [SpeechSegment(0, 10_000)])
    assert [s.start_ms for s in result.output.segments] == [0, 2000]
    assert [d.reason for d in result.output.diagnostics.dropped_segments] == ["loop"] * 3


def test_g2_a_high_compression_ratio_alone_asks_for_a_second_pass_without_cutting() -> None:
    seg = _seg(0, "das ist ein ganz normaler satz")
    result = guards.apply(_out([seg], [_d(seg, compression_ratio=2.9)]), _speech_over(seg))
    assert result.output.segments == [seg]
    assert result.loop_ranges == [(seg.start_ms, seg.end_ms)]


def test_g2_leaves_ordinary_repetition_alone() -> None:
    seg = _seg(0, "ja ja genau das das ist es")
    result = guards.apply(_out([seg]), _speech_over(seg))
    assert result.output.segments == [seg] and result.loop_ranges == []


# ── G3 ───────────────────────────────────────────────────────────────


def test_g3_drops_a_short_unsure_segment_where_vad_heard_nothing() -> None:
    seg = _seg(5000, "hm ja", prob=0.1)
    out = guards.apply(_out([seg], [_d(seg, no_speech_prob=0.1, avg_logprob=-0.5)]), SILENCE).output
    assert out.segments == []
    assert out.diagnostics.dropped_segments[0].reason == "low_confidence_nonspeech"


def test_g3_keeps_a_short_unsure_segment_over_speech() -> None:
    seg = _seg(5000, "hm ja", prob=0.1)
    out = guards.apply(
        _out([seg], [_d(seg, no_speech_prob=0.1, avg_logprob=-0.5)]), _speech_over(seg)
    ).output
    assert out.segments == [seg]


# ── T3 artefacts ─────────────────────────────────────────────────────


def test_an_artefact_in_silence_is_dropped() -> None:
    seg = _seg(30_000, "Vielen Dank.")
    out = guards.apply(_out([seg], [_d(seg, no_speech_prob=0.0, avg_logprob=-0.2)]), SILENCE).output
    assert out.segments == []
    (drop,) = out.diagnostics.dropped_segments
    assert drop.reason == "artefact" and drop.artefact and drop.artefact.startswith("de:")


def test_an_artefact_over_speech_is_kept_and_flagged() -> None:
    seg = _seg(30_000, "Vielen Dank.")
    out = guards.apply(
        _out([seg], [_d(seg, no_speech_prob=0.0, avg_logprob=-0.2)]), _speech_over(seg)
    ).output
    assert out.segments == [seg]
    assert len(out.diagnostics.artefact_kept) == 1 and out.diagnostics.dropped_segments == []


def test_an_artefact_the_decoder_calls_no_speech_is_dropped_even_over_vad_speech() -> None:
    seg = _seg(0, "Untertitelung des ZDF, 2020")
    out = guards.apply(_out([seg], [_d(seg, no_speech_prob=0.7)]), _speech_over(seg)).output
    assert out.segments == []


# ── Rollback switch ──────────────────────────────────────────────────


def test_gates_off_drop_nothing_and_record_a_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "asr_gates_enabled", False)
    silent = _seg(30_000, "Vielen Dank.")
    loop = _seg(0, "vielen dank " * 6)
    result = guards.apply(
        _out([loop, silent], [_d(silent, no_speech_prob=0.9, avg_logprob=-1.5)]), _speech_over(loop)
    )
    assert result.output.segments == [loop, silent]
    assert result.loop_ranges == []
    reasons = sorted(d.reason for d in result.output.diagnostics.dropped_segments)
    assert reasons == ["artefact", "loop"]
    assert all(d.dry_run for d in result.output.diagnostics.dropped_segments)


# ── No content in diagnostics ────────────────────────────────────────


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (_strings(k) + _strings(v))]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def test_diagnostics_carry_no_text() -> None:
    segs = [
        _seg(0, "vielen dank " * 6),
        _seg(10_000, "Untertitelung des ZDF, 2020"),
        _seg(20_000, "Ein ganz gewöhnlicher Satz über Handala"),
        _seg(40_000, "Vielen Dank."),
    ]
    out = guards.apply(
        _out(segs, [_d(s, no_speech_prob=0.1, avg_logprob=-0.3) for s in segs]),
        [SpeechSegment(0, 25_000)],
    ).output
    dumped = json.loads(out.diagnostics.model_dump_json())
    for s in _strings(dumped):
        assert len(s) <= 32, s
    blob = json.dumps(dumped).casefold()
    for word in ("vielen", "dank", "untertitelung", "zdf", "handala", "satz"):
        assert word not in blob


def test_g3_is_skipped_when_the_backend_gave_no_word_probabilities() -> None:
    seg = _seg(5000, "hm ja", prob=1.0)  # read as 1.0 because none were sent
    out = _out([seg]).model_copy(
        update={"diagnostics": Diagnostics(gate_unavailable={"word_probability": 2})}
    )
    result = guards.apply(out, [SpeechSegment(0, 4000)]).output
    # No no_speech_prob either: G1 rests on VAD alone and drops it, G3 did not run.
    assert [d.reason for d in result.diagnostics.dropped_segments] == ["no_speech"]


# ── G2 near-repeats (Sprint B3 T3) ───────────────────────────────────


def test_g2_a_drifting_loop_is_cut_after_two_repetitions() -> None:
    # Articles and endings drift, as Whisper's loops do; no 2–6-gram repeats exactly 4 times.
    units = [
        "das ist der US -Präsident,",
        "das ist die US -Präsident,",
        "das ist der US -Präsidentin,",
    ]
    drift = "Das ist einmal das US -Präsident, " + " ".join(units * 3)
    seg = _seg(0, drift)
    assert guards.loop_cut([w.text for w in seg.words], 4, fuzzy_ratio=1.0) is None
    result = guards.apply(_out([seg]), _speech_over(seg))
    (kept,) = result.output.segments
    assert kept.text.lower().count("das ist") == 1 + 4, kept.text
    assert result.loop_ranges == [(seg.start_ms, seg.end_ms)]


def test_g2_near_repeat_grams_match_at_the_fuzzy_ratio_and_not_above_it() -> None:
    tokens = [
        "wir",
        "sehen",
        "uns",
        "dann",
        "morgen",
        "früh",
        "wir",
        "sehen",
        "uns",
        "dann",
        "morgen",
        "spät",
        "wir",
        "sehen",
        "uns",
        "dann",
        "morgen",
        "früh",
        "wir",
        "sehen",
        "uns",
        "dann",
        "morgen",
        "spät",
    ]
    assert guards.loop_cut(tokens, 4, fuzzy_ratio=0.8) == 12
    assert guards.loop_cut(tokens, 4, fuzzy_ratio=1.0) is None


def test_g2_exact_loops_are_cut_as_before() -> None:
    seg = _seg(0, "vielen dank " * 6)
    assert guards.loop_cut([w.text for w in seg.words], 4, fuzzy_ratio=1.0) == 4


# ── Stock credit lines (Sprint A3 T2, S1) ────────────────────────────


@pytest.mark.parametrize(
    ("language", "text"),
    [
        ("en", "Thank you for watching!"),
        ("de", "Danke fürs Zuschauen."),
        ("uk", "Дякую за перегляд!"),
    ],
)
def test_a_stock_outro_after_a_gap_is_cut(language: str, text: str) -> None:
    speech = _seg(0, "wir sprechen heute über den haushalt der stadt und den liefertermin")
    outro = _seg(speech.end_ms + 4000, text)
    out = _out([speech, outro], [_d(speech, no_speech_prob=0.01), _d(outro, no_speech_prob=0.05)])
    out = out.model_copy(update={"language": language})
    result = guards.apply(out, [SpeechSegment(0, outro.end_ms)])
    assert [s.start_ms for s in result.output.segments] == [speech.start_ms]
    (drop,) = result.output.diagnostics.dropped_segments
    assert drop.reason == "artefact_stock_line"


def test_a_stock_outro_the_decoder_doubts_is_cut_without_a_gap() -> None:
    speech = _seg(0, "we talk about the budget and the delivery date today")
    outro = _seg(speech.end_ms + 100, "Thanks for watching")
    out = _out([speech, outro], [_d(speech, no_speech_prob=0.01), _d(outro, no_speech_prob=0.7)])
    result = guards.apply(
        out.model_copy(update={"language": "en"}), [SpeechSegment(0, outro.end_ms)]
    )
    assert len(result.output.segments) == 1


def test_a_short_credit_line_is_cut_without_gap_or_doubt() -> None:
    # NOTE-2026-00086: a confident 6-token credit 1 s after the narrator's sentence.
    before = _seg(61410, "In ganz China.")
    credit = _seg(64098, "Untertitelung des ZDF für funk, 2017")
    after = _seg(66626, "Chinesische E-Autos sind weltweit auf der Überholspur.")
    out = _out(
        [before, credit, after],
        [_d(s, no_speech_prob=0.01) for s in (before, credit, after)],
    )
    result = guards.apply(out, [SpeechSegment(0, after.end_ms)])
    texts = [s.text for s in result.output.segments]
    assert texts == [before.text, after.text]
    (drop,) = result.output.diagnostics.dropped_segments
    assert drop.reason == "artefact_stock_line"
    assert drop.segment_index == 1 and drop.artefact == "de:0"
    assert (drop.start_ms, drop.end_ms) == (credit.start_ms, credit.end_ms)


def test_a_credit_heading_a_long_segment_loses_only_the_credit() -> None:
    text = (
        "Untertitelung des ZDF für funk, 2017 Chinesische E-Autos sind weltweit auf der "
        "Überholspur und das ist kein Zufall"
    )
    seg = _seg(64098, text)
    out = _out([seg], [_d(seg, no_speech_prob=0.6)])
    result = guards.apply(out, [SpeechSegment(0, seg.end_ms)])
    (kept,) = result.output.segments
    assert kept.text.startswith("Chinesische E-Autos") and "Untertitelung" not in kept.text
    assert (kept.start_ms, kept.end_ms) == (seg.start_ms, seg.end_ms)
    assert kept.words == seg.words[6:]
    (drop,) = result.output.diagnostics.dropped_segments
    assert drop.reason == "artefact_stock_line" and drop.segment_index == 0
    assert (drop.start_ms, drop.end_ms) == (seg.start_ms, seg.words[5].end_ms)


def test_a_credit_heading_a_long_segment_without_words_cuts_the_substring() -> None:
    text = (
        "Untertitelung des ZDF für funk, 2017 Chinesische E-Autos sind weltweit auf der "
        "Überholspur und das ist kein Zufall"
    )
    seg = Segment(text=text, start_ms=10_000, end_ms=18_000, avg_confidence=0.9)
    out = _out([seg], [_d(seg, no_speech_prob=0.6)])
    (kept,) = guards.apply(out, [SpeechSegment(0, seg.end_ms)]).output.segments
    assert kept.text == text.split(" 2017 ", 1)[1]
    assert (kept.start_ms, kept.end_ms) == (10_000, 18_000)


def test_thanks_for_watching_spoken_mid_speech_stays() -> None:
    speech = _seg(0, "we talk about the budget and the delivery date today")
    said = _seg(
        speech.end_ms + 200,
        "Thanks for watching the budget numbers so closely, and now the second item on the list",
    )
    out = _out([speech, said], [_d(speech, no_speech_prob=0.01), _d(said, no_speech_prob=0.02)])
    result = guards.apply(
        out.model_copy(update={"language": "en"}), [SpeechSegment(0, said.end_ms)]
    )
    assert len(result.output.segments) == 2 and result.output.diagnostics.dropped_segments == []


def test_a_long_sentence_starting_with_subscribe_stays() -> None:
    speech = _seg(0, "we talk about the budget and the delivery date today")
    said = _seg(
        speech.end_ms + 100,
        "Subscribe to the vendor portal before Friday so the finance team can approve the order",
    )
    out = _out([speech, said], [_d(speech, no_speech_prob=0.01), _d(said, no_speech_prob=0.02)])
    result = guards.apply(
        out.model_copy(update={"language": "en"}), [SpeechSegment(0, said.end_ms)]
    )
    assert [s.text for s in result.output.segments] == [speech.text, said.text]


def test_a_stock_line_in_dry_run_is_recorded_and_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "asr_gates_enabled", False)
    seg = _seg(0, "Untertitelung des ZDF für funk, 2017")
    result = guards.apply(_out([seg]), [SpeechSegment(0, seg.end_ms)])
    assert result.output.segments == [seg]
    (drop,) = result.output.diagnostics.dropped_segments
    assert drop.dry_run and drop.reason == "artefact_stock_line"


@pytest.mark.parametrize(
    ("language", "text", "prefix"),
    [
        ("de", "Untertitelung des ZDF für funk, 2017", "untertitelung des zdf"),
        ("de", "Untertitel im Auftrag des ZDF, 2020", "untertitel im auftrag des zdf"),
        ("de", "Untertitelung. BR 2018", "untertitelung"),
        ("de", "Untertitel von Stephanie Geiges", "untertitel von"),
        ("de", "Copyright WDR 2021", "copyright wdr"),
        ("de", "Danke fürs Zuschauen!", "danke fürs zuschauen"),
        ("de", "Vielen Dank fürs Zuschauen!", "vielen dank fürs zuschauen"),
        ("de", "Abonniert den Kanal!", "abonniert"),
        ("en", "Thank you for watching!", "thank you for watching"),
        ("en", "Thanks for watching!", "thanks for watching"),
        ("en", "Subscribe to my channel", "subscribe to"),
        ("en", "Subtitles by the Amara.org community", "subtitles by"),
        ("en", "Captions by GetTranscribed.com", "captions by"),
        ("en", "Transcribed by ESO", "transcribed by"),
        ("uk", "Дякую за перегляд!", "дякую за перегляд"),
        ("uk", "Підпишіться на канал", "підпишіться"),
        ("uk", "Субтитри зроблені спільнотою", "субтитри"),
    ],
)
def test_the_stock_line_table_names_each_language(language: str, text: str, prefix: str) -> None:
    match = guards.stock_line(text.split(), language)
    assert match is not None
    lang, k = match[0].split(":")
    assert guards.STOCK_LINES[lang][int(k)] == prefix


def test_stock_lines_match_only_at_the_start() -> None:
    assert guards.stock_line(["Wir", "haben", "die", "Untertitelung", "bestellt"], "de") is None
    assert guards.stock_line(["Subscribers", "grew", "this", "quarter"], "en") is None


def test_a_long_sentence_opening_with_a_stock_line_after_a_gap_stays() -> None:
    # The Pardo opening (Sprint I3): a gap before it, but no end to a credit in sight.
    text = (
        "Thank you for watching this highly anticipated world debut of the Pardo 65 GT here "
        "at the Cannes Yachting Festival"
    )
    seg = _seg(11_000, text)
    out = _out([seg], [_d(seg, no_speech_prob=0.01)]).model_copy(update={"language": "en"})
    result = guards.apply(out, [SpeechSegment(0, seg.end_ms)])
    assert [s.text for s in result.output.segments] == [text]
    assert result.output.diagnostics.dropped_segments == []
