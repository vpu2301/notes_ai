"""Sprint I2 — nothing enters a transcript that was not said.

T3: the lexical prompt-echo guard on the 2026-09-25 incident's own
segments; T4: a chunk is decoded in its own language only when the
detector is sure; T5/T7: the decode options follow the settings.
"""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pytest

from asr_models import (
    Diagnostics,
    EchoSpan,
    Segment,
    TranscriptionMetadata,
    TranscriptionOutput,
    WordTiming,
)
from asr_worker import echo, inference, processor

# The affected workspace's hint, in the order `GET /v1/glossary/hint` sent it.
INCIDENT_PROMPT = (
    "Gregor Gysi, Moderator, Moderator II, moderatorin, narrator, speaker, speaker background"
)


def _words(text: str, *, start_ms: int = 0, step_ms: int = 300, gap_after: int | None = None):
    out: list[WordTiming] = []
    t = start_ms
    for i, token in enumerate(text.split()):
        out.append(WordTiming(text=token, start_ms=t, end_ms=t + step_ms - 50, probability=0.9))
        t += step_ms
        if gap_after is not None and i == gap_after:
            t += 2_000
    return out


def _text(words: list[WordTiming]) -> str:
    return " ".join(w.text for w in words)


# ── T3: the incident's two segments ─────────────────────────────────


def test_the_first_incident_segment_keeps_only_the_speech() -> None:
    words = _words(
        "Gysi, Moderator II, moderatorin, narrator, speaker background Questions or inquiries "
        "about this Pardo 65 GT"
    )
    kept, spans = echo.strip_prompt_echo(words, INCIDENT_PROMPT)
    assert _text(kept) == "Questions or inquiries about this Pardo 65 GT"
    assert [s.words for s in spans] == [7]
    assert spans[0].start_ms == 0 and spans[0].end_ms == words[6].end_ms


def test_the_second_incident_segment_with_repeats_keeps_only_the_speech() -> None:
    words = _words(
        "Gysi Gysi, Moderator, Moderator II, moderator, speaker, speaker, of Williams Jet Tender"
    )
    kept, spans = echo.strip_prompt_echo(words, INCIDENT_PROMPT)
    assert _text(kept) == "of Williams Jet Tender"
    assert [s.words for s in spans] == [8]


def test_a_real_name_said_mid_sentence_is_speech() -> None:
    words = _words("and my name is Mitchell and I run the yard")
    kept, spans = echo.strip_prompt_echo(words, "Mitchell, Springbrook Marine")
    assert kept == words and spans == []


def test_one_multi_word_term_said_once_at_a_segment_start_is_speech() -> None:
    """T7, the incident recording: the presenter names the product."""
    words = _words("of Williams Jet Tender that you can have in this boat")
    kept, spans = echo.strip_prompt_echo(words, "Gregor Gysi, Williams Jet Tender, Pardo")
    assert kept == words and spans == []
    # The same three tokens repeated, or next to another term, are an echo.
    kept, spans = echo.strip_prompt_echo(
        _words("Williams Jet Tender Williams Jet Tender that"), "Williams Jet Tender"
    )
    assert _text(kept) == "that"
    kept, spans = echo.strip_prompt_echo(
        _words("Pardo Williams Jet Tender that"), "Williams Jet Tender, Pardo"
    )
    assert _text(kept) == "that"


def test_a_two_word_term_at_a_segment_start_is_below_the_run_length() -> None:
    words = _words("Springbrook Marine builds the hull in Poole")
    kept, spans = echo.strip_prompt_echo(words, "Springbrook Marine, Mitchell")
    assert kept == words and spans == []


def test_a_run_after_a_pause_is_removed_even_late_in_the_segment() -> None:
    words = _words(
        "we then looked at the engine room and the tender garage Gysi Moderator narrator",
        gap_after=10,
    )
    kept, spans = echo.strip_prompt_echo(words, INCIDENT_PROMPT)
    assert _text(kept) == "we then looked at the engine room and the tender garage"
    assert len(spans) == 1 and spans[0].words == 3


def test_a_run_late_in_a_segment_without_a_pause_is_speech() -> None:
    """A presenter reading the roster aloud mid-sentence is not an echo."""
    words = _words(
        "we then looked at the engine room and the tender garage Gysi Moderator narrator"
    )
    kept, spans = echo.strip_prompt_echo(words, INCIDENT_PROMPT)
    assert kept == words and spans == []


def test_one_filler_inside_a_run_does_not_break_it_but_two_do() -> None:
    one = _words("Gysi and Moderator narrator speaker then we")
    kept, spans = echo.strip_prompt_echo(one, INCIDENT_PROMPT)
    assert _text(kept) == "then we" and spans[0].words == 5
    two = _words("Gysi and the Moderator narrator speaker")
    kept, spans = echo.strip_prompt_echo(two, INCIDENT_PROMPT)
    # "Gysi" alone is a run of 1; "Moderator narrator speaker" starts at word
    # 3 (< LEAD_WORDS) and is a run of 3.
    assert _text(kept) == "Gysi and the" and spans[0].words == 3


def test_the_twenty_eight_minute_silence_echo_is_dropped_whole() -> None:
    segments = [
        Segment(
            text="Gysi, Moderator. Gysi, Moderator.",
            start_ms=i * 4_000,
            end_ms=i * 4_000 + 3_000,
            words=_words("Gysi, Moderator. Gysi, Moderator.", start_ms=i * 4_000),
            avg_confidence=0.8,
        )
        for i in range(420)
    ]
    kept, spans, dropped = echo.guard_segments(segments, "Moderator, Gregor Gysi")
    assert kept == [] and dropped == 420 and len(spans) == 420


def test_the_guard_never_adds_or_rewrites_a_word() -> None:
    words = _words("Gysi Moderator narrator Questions about the Pardo")
    kept, _spans = echo.strip_prompt_echo(words, INCIDENT_PROMPT)
    assert all(w in words for w in kept)
    assert [w.text for w in kept] == ["Questions", "about", "the", "Pardo"]


def test_no_prompt_means_no_change() -> None:
    words = _words("Gysi Moderator narrator")
    assert echo.strip_prompt_echo(words, None) == (words, [])
    assert echo.strip_prompt_echo(words, "") == (words, [])


def test_a_backend_without_word_timings_is_guarded_by_text() -> None:
    seg = Segment(
        text="Gysi, Moderator II, narrator, of Williams Jet Tender",
        start_ms=1_000,
        end_ms=5_000,
        avg_confidence=0.7,
    )
    kept, spans, dropped = echo.guard_segments([seg], INCIDENT_PROMPT)
    assert dropped == 0 and len(spans) == 1
    assert kept[0].text == "of Williams Jet Tender"
    assert (kept[0].start_ms, kept[0].end_ms) == (1_000, 5_000) and kept[0].words == []


def test_guarded_output_records_spans_and_counts_never_words() -> None:
    output = TranscriptionOutput(
        language="en",
        segments=[
            Segment(
                text="Gysi Moderator narrator Questions about the Pardo",
                start_ms=0,
                end_ms=2_400,
                words=_words("Gysi Moderator narrator Questions about the Pardo"),
                avg_confidence=0.9,
            ),
            Segment(
                text="Gysi Moderator narrator",
                start_ms=10_000,
                end_ms=11_000,
                words=_words("Gysi Moderator narrator", start_ms=10_000),
                avg_confidence=0.9,
            ),
        ],
        metadata=TranscriptionMetadata(
            model="t", vad_seconds_speech=1, infer_seconds=1, beam_size=1
        ),
    )
    guarded = processor._guarded(output, INCIDENT_PROMPT, job_id=uuid4())
    assert [s.text for s in guarded.segments] == ["Questions about the Pardo"]
    assert guarded.diagnostics.prompt_echo_segments_dropped == 1
    assert [(s.start_ms, s.words) for s in guarded.diagnostics.prompt_echo] == [(0, 3), (10_000, 3)]
    assert "Gysi" not in guarded.diagnostics.model_dump_json()


def test_the_old_whole_segment_rule_still_holds() -> None:
    assert inference._is_prompt_echo("Gysi, Moderator", INCIDENT_PROMPT, 0.9)
    assert not inference._is_prompt_echo("Gysi, Moderator", INCIDENT_PROMPT, 0.1)


# ── T4: a chunk in another language ─────────────────────────────────


def test_a_chunk_is_decoded_in_another_language_only_when_the_detector_is_sure() -> None:
    sure = inference.LanguageGuess("uk", 0.93, {"uk": 0.93, "en": 0.04})
    assert inference.other_language(sure, recording="en") == "uk"
    same = inference.LanguageGuess("en", 0.99, {"en": 0.99})
    assert inference.other_language(same, recording="en") is None
    # Ukrainian shares probability with Russian: 0.75 is a sure Ukrainian.
    related = inference.LanguageGuess("uk", 0.75, {"uk": 0.75, "ru": 0.18, "en": 0.002})
    assert inference.other_language(related, recording="en") == "uk"
    unsure = inference.LanguageGuess("uk", 0.5, {"uk": 0.5, "ru": 0.3, "en": 0.15})
    assert inference.other_language(unsure, recording="en") is None
    # The detector's "Welsh" on accented English is never decoded as Welsh.
    welsh = inference.LanguageGuess("cy", 0.95, {"cy": 0.95, "en": 0.03})
    assert inference.other_language(welsh, recording="en") is None
    # A stray English word in a Ukrainian meeting: the recording language
    # keeps enough probability to hold.
    stray = inference.LanguageGuess("en", 0.85, {"en": 0.85, "uk": 0.3})
    assert inference.other_language(stray, recording="uk") is None
    fallback = inference.LanguageGuess("en", 0.0)
    assert inference.other_language(fallback, recording="uk") is None


def test_the_probability_table_reads_faster_whispers_shape() -> None:
    assert inference._probability_table([("uk", 0.9), ("EN", 0.1)]) == {"uk": 0.9, "en": 0.1}
    assert inference._probability_table(None) == {}
    assert inference._probability_table("nonsense") == {}


def test_chunks_in_another_language_are_labelled_and_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = inference.WhisperEngine()
    engine._loaded = True  # type: ignore[attr-defined]
    calls: list[tuple[str, str | None]] = []

    def run_chunk(chunk, language, prompt, offset_ms):  # noqa: ANN001, ANN202
        calls.append((language, prompt))
        return [Segment(text="x", start_ms=offset_ms, end_ms=offset_ms + 900, avg_confidence=0.9)]

    guesses = iter(
        [
            inference.LanguageGuess("en", 0.99, {"en": 0.99}),
            inference.LanguageGuess("uk", 0.95, {"uk": 0.95, "en": 0.02}),
        ]
    )
    monkeypatch.setattr(engine, "_run_chunk", run_chunk)
    monkeypatch.setattr(engine, "_detect_chunk_language", lambda pcm: next(guesses))
    monkeypatch.setattr(
        inference,
        "detect_speech",
        lambda pcm: [
            inference.SpeechSegment(start_ms=0, end_ms=3_000),
            inference.SpeechSegment(start_ms=5_000, end_ms=8_000),
        ],
    )
    import asyncio

    output = asyncio.run(
        engine.transcribe(np.zeros(16_000 * 9, dtype=np.float32), language="en", prompt="P")
    )
    assert calls == [("en", "P"), ("uk", "P")]
    assert [s.language for s in output.segments] == [None, "uk"]
    assert output.diagnostics == Diagnostics(other_language_chunks=1, language_id="engine")


# ── T5 / T7: the decode options follow the settings ─────────────────


def test_conditioning_and_vocabulary_mode_follow_the_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(inference.settings, "asr_condition_prev", False)
    monkeypatch.setattr(inference.settings, "asr_vocabulary_mode", "prompt")
    assert inference.chunk_decode_options("Gysi") == {
        "condition_on_previous_text": False,
        "initial_prompt": "Gysi",
    }
    monkeypatch.setattr(inference.settings, "asr_condition_prev", True)
    monkeypatch.setattr(inference.settings, "asr_vocabulary_mode", "hotwords")
    assert inference.chunk_decode_options("Gysi") == {
        "condition_on_previous_text": True,
        "hotwords": "Gysi",
        "initial_prompt": None,
    }


def test_the_defaults_are_conditioning_and_the_prompt() -> None:
    from asr_worker.config import Settings

    fresh = Settings(_env_file=None)  # type: ignore[call-arg]
    # T7: off makes conversation chunks lower-case run-ons; the guard
    # contains the cascade instead.
    assert fresh.asr_condition_prev is True
    assert fresh.asr_vocabulary_mode == "prompt"
    assert fresh.asr_chunk_language_id is True


def test_older_artifacts_parse_with_empty_diagnostics() -> None:
    raw = {
        "language": "en",
        "segments": [{"text": "a", "start_ms": 0, "end_ms": 1, "avg_confidence": 0.5}],
        "metadata": {"model": "m", "vad_seconds_speech": 1, "infer_seconds": 1, "beam_size": 1},
    }
    output = TranscriptionOutput.model_validate(raw)
    assert output.diagnostics == Diagnostics() and output.segments[0].language is None
    assert EchoSpan(start_ms=0, end_ms=1, words=1).words == 1
