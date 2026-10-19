"""Sprint B3 T2 — a segment in another language is decoded again in that language,
and the decoder's avg_logprob, never the lexical test, decides which decode stays."""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import numpy as np
import pytest

from asr_models import (
    Diagnostics,
    Segment,
    SegmentDiagnostics,
    TranscriptionMetadata,
    TranscriptionOutput,
    WordTiming,
)
from asr_worker import chunks, segment_lid
from asr_worker.chunks import LanguageGuess
from asr_worker.config import settings
from asr_worker.vad import SpeechSegment

SR = 16_000
JOB = UUID(int=0)

GERMAN = "Wir besprechen heute den Haushalt und die Pläne für das nächste Jahr."
ENGLISH = "The elections in this country are decided by the voters and not by the courts."
PRODUCT_TALK = "Wir haben den pull request gestern gemergt und das deployment läuft seit heute."


def _seg(start: int, end: int, text: str, *, language: str | None = None) -> Segment:
    words = text.split()
    step = max(1, (end - start) // max(1, len(words)))
    return Segment(
        text=text,
        start_ms=start,
        end_ms=end,
        words=[
            WordTiming(
                text=w,
                start_ms=start + k * step,
                end_ms=start + (k + 1) * step - 1,
                probability=0.9,
            )
            for k, w in enumerate(words)
        ],
        avg_confidence=0.9,
        language=language,
    )


def _out(
    segments: list[Segment],
    logprobs: list[float | None],
    *,
    language: str = "de",
    detected: bool = True,
) -> TranscriptionOutput:
    return TranscriptionOutput(
        language=language,
        language_detected=detected,
        segments=segments,
        metadata=TranscriptionMetadata(
            model="t", vad_seconds_speech=0, infer_seconds=0, beam_size=1
        ),
        diagnostics=Diagnostics(
            segments=[
                SegmentDiagnostics(start_ms=s.start_ms, end_ms=s.end_ms, avg_logprob=lp)
                for s, lp in zip(segments, logprobs, strict=True)
            ]
        ),
    )


class _Provider:
    """Answers a span decode with fixed text and avg_logprob; remembers what it was asked."""

    def __init__(self, text: str, logprob: float | None) -> None:
        self.text, self.logprob = text, logprob
        self.calls: list[tuple[int, str]] = []

    async def transcribe(
        self,
        pcm: np.ndarray,
        *,
        language: str,
        prompt: str | None,
        should_cancel: Any = None,
        second_pass: bool = False,
    ) -> TranscriptionOutput:
        assert prompt is None and second_pass
        self.calls.append((len(pcm) // 16, language))
        end = len(pcm) // 16
        seg = _seg(0, end, self.text)
        return TranscriptionOutput(
            language=language,
            segments=[seg],
            metadata=TranscriptionMetadata(
                model="t", vad_seconds_speech=0, infer_seconds=0, beam_size=5
            ),
            diagnostics=Diagnostics(
                segments=[SegmentDiagnostics(start_ms=0, end_ms=end, avg_logprob=self.logprob)]
            ),
        )


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "asr_segment_lid_enabled", True)
    monkeypatch.setattr(settings, "asr_segment_lid_min_ms", 3000)
    monkeypatch.setattr(settings, "asr_segment_lid_foreign_share", 0.6)
    monkeypatch.setattr(settings, "asr_gates_enabled", True)


async def _run(
    provider: Any, out: TranscriptionOutput, *, deadline: float | None = None
) -> TranscriptionOutput:
    pcm = np.zeros(SR * 40, dtype=np.float32)
    # One speech run over the decoded span: what VAD heard is what was written.
    end = max((s.end_ms for s in out.segments), default=0)
    return await segment_lid.rediscover(
        provider,
        pcm,
        out,
        speech=[SpeechSegment(0, end)],
        deadline=time.monotonic() + 60 if deadline is None else deadline,
        should_cancel=None,
        job_id=JOB,
    )


# ── The lexical test ─────────────────────────────────────────────────


def test_english_words_in_a_german_decode_name_english() -> None:
    assert segment_lid.lexical_language(ENGLISH, recording="de", share=0.6) == "en"


def test_german_talk_with_english_product_names_is_not_suspect() -> None:
    assert segment_lid.lexical_language(PRODUCT_TALK, recording="de", share=0.6) is None


def test_cyrillic_in_an_english_recording_names_ukrainian() -> None:
    text = "Ми обговорюємо бюджет на наступний рік і відкриті вакансії."
    assert segment_lid.lexical_language(text, recording="en", share=0.6) == "uk"


def test_too_few_markers_say_nothing() -> None:
    assert segment_lid.lexical_language("Okay, the budget.", recording="de", share=0.6) is None


# ── The re-decode ────────────────────────────────────────────────────


async def test_a_suspect_segment_is_decoded_in_its_language_and_kept_when_the_decoder_is_surer() -> (
    None
):
    out = _out(
        [_seg(0, 5000, GERMAN), _seg(5000, 12_000, ENGLISH), _seg(12_000, 17_000, GERMAN)],
        [-0.3, -0.9, -0.3],
    )
    provider = _Provider(ENGLISH, -0.2)
    got = await _run(provider, out)
    assert [c[1] for c in provider.calls] == ["en"]
    assert [s.language for s in got.segments] == [None, "en", None]
    assert got.segments[1].start_ms == 4900 and got.segments[1].speaker is None
    stats = got.diagnostics.segment_language
    assert (stats.segments, stats.suspects, stats.lexical, stats.switched) == (3, 1, 1, 1)
    assert [d.language for d in got.diagnostics.segments] == [None, "en", None]


async def test_the_original_decode_stays_when_its_logprob_is_better() -> None:
    out = _out([_seg(0, 5000, GERMAN), _seg(5000, 12_000, ENGLISH)], [-0.3, -0.4])
    provider = _Provider("nonsense decode", -0.9)
    got = await _run(provider, out)
    assert len(provider.calls) == 1
    # The text stays; its own words still say which language it is in.
    assert [s.text for s in got.segments] == [s.text for s in out.segments]
    assert got.segments[1].language == "en"
    stats = got.diagnostics.segment_language
    assert (stats.suspects, stats.switched, stats.relabelled) == (1, 0, 1)


async def test_product_names_never_trigger_a_re_decode() -> None:
    out = _out([_seg(0, 5000, GERMAN), _seg(5000, 12_000, PRODUCT_TALK)], [-0.3, -0.35])
    provider = _Provider(ENGLISH, -0.1)
    got = await _run(provider, out)
    assert provider.calls == [] and got.diagnostics.segment_language.suspects == 0


async def test_a_pinned_language_job_is_checked_the_same_way() -> None:
    out = _out([_seg(0, 5000, GERMAN), _seg(5000, 12_000, ENGLISH)], [-0.3, -0.9], detected=False)
    got = await _run(_Provider(ENGLISH, -0.2), out)
    assert got.segments[1].language == "en"


async def test_a_low_logprob_segment_asks_the_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    class _LID:
        source = "engine"

        async def run_language(self, _pcm: np.ndarray) -> LanguageGuess:
            return LanguageGuess("en", 0.95, {"en": 0.95, "de": 0.02})

        async def recording_language(self, _s: np.ndarray) -> LanguageGuess:
            raise AssertionError("not asked")

    async def identifier_for(_provider: Any) -> _LID:
        return _LID()

    monkeypatch.setattr(chunks, "identifier_for", identifier_for)
    translated = "Die Wahlen in diesem Land werden von den Wählern entschieden."
    out = _out(
        [_seg(0, 5000, GERMAN), _seg(5000, 12_000, translated), _seg(12_000, 17_000, GERMAN)],
        [-0.3, -1.4, -0.3],
    )
    provider = _Provider(ENGLISH, -0.3)
    got = await _run(provider, out)
    assert [c[1] for c in provider.calls] == ["en"]
    assert got.segments[1].language == "en"
    assert got.diagnostics.segment_language.logprob == 1


async def test_short_segments_and_already_labelled_runs_are_left_alone() -> None:
    out = _out([_seg(0, 2000, ENGLISH), _seg(2000, 9000, ENGLISH, language="en")], [-0.9, -0.3])
    provider = _Provider(ENGLISH, -0.1)
    got = await _run(provider, out)
    assert provider.calls == [] and got.diagnostics.segment_language.suspects == 0


async def test_without_a_logprob_nothing_is_decided() -> None:
    out = _out([_seg(0, 5000, GERMAN), _seg(5000, 12_000, ENGLISH)], [None, None])
    provider = _Provider(ENGLISH, -0.1)
    got = await _run(provider, out)
    assert provider.calls == []
    assert got.diagnostics.segment_language.unavailable == 1
    assert got.segments[1].text == ENGLISH and got.segments[1].language == "en"


async def test_past_the_deadline_the_suspect_is_skipped() -> None:
    out = _out([_seg(0, 5000, GERMAN), _seg(5000, 12_000, ENGLISH)], [-0.3, -0.9])
    provider = _Provider(ENGLISH, -0.1)
    got = await _run(provider, out, deadline=time.monotonic())
    assert provider.calls == [] and got.diagnostics.segment_language.skipped == 1


async def test_adjacent_suspects_are_decoded_as_one_span() -> None:
    out = _out(
        [_seg(0, 5000, GERMAN), _seg(5000, 9000, ENGLISH), _seg(9200, 14_000, ENGLISH)],
        [-0.3, -0.9, -0.9],
    )
    provider = _Provider(ENGLISH, -0.2)
    got = await _run(provider, out)
    assert len(provider.calls) == 1 and provider.calls[0][0] == 9200
    assert [s.language for s in got.segments] == [None, "en"]


# ── The clip a pinned decoder wrote nothing for ───────────────────────


def test_a_word_free_stretch_inside_a_run_is_found() -> None:
    segs = [_seg(0, 5000, GERMAN), _seg(14_000, 19_000, GERMAN)]
    gaps = segment_lid.uncovered([SpeechSegment(0, 19_000)], segs, min_ms=3000)
    assert len(gaps) == 1 and gaps[0][1] == 14_000 and gaps[0][0] < 5000
    assert segment_lid.uncovered([SpeechSegment(0, 19_000)], segs, min_ms=10_000) == []
    assert segment_lid.uncovered([SpeechSegment(0, 5000)], segs[:1], min_ms=3000) == []


class _SureLID:
    source = "engine"

    def __init__(self, language: str, probability: float = 0.97) -> None:
        self.language, self.probability = language, probability
        self.asked: list[int] = []

    async def run_language(self, pcm: np.ndarray) -> LanguageGuess:
        self.asked.append(len(pcm) // 16)
        return LanguageGuess(self.language, self.probability, {self.language: self.probability})

    async def recording_language(self, _s: np.ndarray) -> LanguageGuess:
        raise AssertionError("not asked")


async def test_a_clip_the_pinned_decoder_skipped_is_identified_and_decoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lid = _SureLID("en")

    async def identifier_for(_provider: Any) -> _SureLID:
        return lid

    monkeypatch.setattr(chunks, "identifier_for", identifier_for)
    out = _out([_seg(0, 5000, GERMAN), _seg(14_000, 19_000, GERMAN)], [-0.3, -0.3])
    provider = _Provider(ENGLISH, -0.4)
    got = await _run(provider, out)
    assert len(provider.calls) == 1 and provider.calls[0][1] == "en"
    assert [s.language for s in got.segments] == [None, "en", None]
    assert got.segments[1].start_ms < 14_000 <= got.segments[1].end_ms + 200
    stats = got.diagnostics.segment_language
    assert (stats.gaps, stats.switched) == (1, 1)


async def test_a_skipped_stretch_the_identifier_cannot_name_stays_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lid = _SureLID("de", 0.9)

    async def identifier_for(_provider: Any) -> _SureLID:
        return lid

    monkeypatch.setattr(chunks, "identifier_for", identifier_for)
    out = _out([_seg(0, 5000, GERMAN), _seg(14_000, 19_000, GERMAN)], [-0.3, -0.3])
    provider = _Provider(ENGLISH, -0.1)
    got = await _run(provider, out)
    assert provider.calls == [] and got.diagnostics.segment_language.gaps == 0


async def test_english_words_under_a_german_decode_keep_the_english_label() -> None:
    out = _out([_seg(0, 5000, GERMAN), _seg(5000, 12_000, ENGLISH)], [-0.3, -0.3])
    provider = _Provider(ENGLISH, -0.5)  # the re-decode is no surer: the text stays
    got = await _run(provider, out)
    assert got.segments[1].text == ENGLISH and got.segments[1].language == "en"
    stats = got.diagnostics.segment_language
    assert (stats.switched, stats.relabelled) == (0, 1)
