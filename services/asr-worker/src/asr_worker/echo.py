"""The prompt-echo guard (Sprint I2 T3): words the decoder copied from its
prompt come out of the transcript, word by word.

Whisper is given the workspace vocabulary as ``initial_prompt``. Over audio
it cannot decode — silence that passed VAD, a breath, speech in another
language — it writes the prompt back, as a run of prompt terms in prompt
order with repeats and case changes, usually at the start of a segment, and
sometimes with real speech glued on after it. The 2026-09-25 transcript:
"Gysi, Moderator II, moderatorin, narrator, speaker background Questions or
inquiries about this Pardo 65 GT".

The old rule (``inference._is_prompt_echo``) dropped a segment only when it
was NOTHING but prompt words and the decoder rated it as non-speech; an
echo fused with speech passed both tests. This one is lexical and
positional and does not depend on a confidence: a run of at least
``MIN_ECHO_RUN`` consecutive prompt tokens — immediate repeats allowed, one
non-prompt filler allowed inside the run — that starts within the first
``LEAD_WORDS`` words of the segment or after a pause of ``GAP_MS`` is an
echo and is removed. A prompt term said once in the middle of a sentence
("my name is Mitchell") is speech and stays.

The guard only ever removes words; it never adds or rewrites one. Removed
spans are returned with their timestamps so the job's diagnostics can say
where and how much — and so a person can disagree.

Pure, backend-agnostic: it runs in the processor on every backend's output,
not inside one engine, because the dev and hosted backends are HTTP
services that never see this code otherwise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from asr_models.output import EchoSpan, Segment, WordTiming

MIN_ECHO_RUN: Final = 3
LEAD_WORDS: Final = 8
GAP_MS: Final = 1500

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def prompt_tokens(prompt: str | None) -> frozenset[str]:
    """The prompt's words, case-folded, punctuation off."""
    if not prompt:
        return frozenset()
    return frozenset(t.casefold() for t in _TOKEN.findall(prompt))


def prompt_terms(prompt: str | None) -> list[tuple[str, ...]]:
    """The prompt's comma-separated terms as token tuples ("Williams Jet
    Tender" is one term of three tokens)."""
    if not prompt:
        return []
    out: list[tuple[str, ...]] = []
    for part in prompt.split(","):
        tokens = tuple(t.casefold() for t in _TOKEN.findall(part))
        if tokens and tokens not in out:
            out.append(tokens)
    return out


def _is_echo(run_tokens: list[str], terms: list[tuple[str, ...]]) -> bool:
    """A run of prompt tokens is an echo when it spans two or more distinct
    prompt terms, or repeats a token straight away. One multi-word term said
    once — "of Williams Jet Tender that you can have" (T7, the incident
    recording) — is the presenter naming the product, not the decoder
    copying its prompt."""
    if len(set(run_tokens)) < len(run_tokens):
        return True  # a word the decoder wrote twice: "Gysi, Moderator. Gysi, Moderator."
    occurrences = 0
    for term in terms:
        n = len(term)
        occurrences += sum(
            1 for k in range(len(run_tokens) - n + 1) if tuple(run_tokens[k : k + n]) == term
        )
        if occurrences >= 2:
            return True
    return False


def _token(text: str) -> str:
    found = _TOKEN.findall(text)
    return found[0].casefold() if found else ""


@dataclass(frozen=True, slots=True)
class _Run:
    start: int  # index of the first word in the run
    end: int  # index after the last word in the run
    prompt_words: int


def _runs(
    words: list[WordTiming], tokens: frozenset[str], terms: list[tuple[str, ...]]
) -> list[_Run]:
    """Every removable run, non-overlapping, left to right."""
    out: list[_Run] = []
    i = 0
    n = len(words)
    while i < n:
        is_prompt = _token(words[i].text) in tokens
        gap_before = words[i].start_ms - words[i - 1].end_ms if i > 0 else 0
        if not is_prompt or not (i < LEAD_WORDS or gap_before >= GAP_MS):
            i += 1
            continue
        # Extend: prompt tokens, or one filler that is followed by a prompt
        # token. The run ends on the last prompt token.
        j = i
        last_prompt = i
        count = 0
        while j < n:
            token = _token(words[j].text)
            if token in tokens:
                count += 1
                last_prompt = j
                j += 1
                continue
            # One filler inside the run, never two, never at the end.
            if j + 1 < n and _token(words[j + 1].text) in tokens and last_prompt == j - 1:
                j += 1
                continue
            break
        end = last_prompt + 1
        run_tokens = [_token(w.text) for w in words[i:end] if _token(w.text) in tokens]
        if count >= MIN_ECHO_RUN and _is_echo(run_tokens, terms):
            out.append(_Run(start=i, end=end, prompt_words=count))
            i = end
        else:
            i += 1
    return out


def strip_prompt_echo(
    words: list[WordTiming], prompt: str | None
) -> tuple[list[WordTiming], list[EchoSpan]]:
    """``(kept words, removed spans)`` for one segment's words."""
    tokens = prompt_tokens(prompt)
    if not tokens or not words:
        return list(words), []
    runs = _runs(words, tokens, prompt_terms(prompt))
    if not runs:
        return list(words), []
    removed: set[int] = set()
    spans: list[EchoSpan] = []
    for run in runs:
        removed.update(range(run.start, run.end))
        spans.append(
            EchoSpan(
                start_ms=words[run.start].start_ms,
                end_ms=words[run.end - 1].end_ms,
                words=run.end - run.start,
            )
        )
    kept = [w for k, w in enumerate(words) if k not in removed]
    return kept, spans


def _rebuild_text(words: list[WordTiming]) -> str:
    text = " ".join(w.text.strip() for w in words if w.text.strip())
    # A removed run leaves its trailing comma on the first kept word only
    # when the decoder attached it there; a leading punctuation mark on a
    # transcript line is noise, not a word.
    return text.lstrip(" ,;:—-–").strip()


def _words_from_text(segment: Segment) -> list[WordTiming]:
    """A backend without word timings: one synthetic word per token, all
    stamped with the segment's own time so gaps never fire and only the
    lead-word rule applies."""
    return [
        WordTiming(text=t, start_ms=segment.start_ms, end_ms=segment.end_ms, probability=1.0)
        for t in segment.text.split()
    ]


def guard_segments(
    segments: list[Segment], prompt: str | None
) -> tuple[list[Segment], list[EchoSpan], int]:
    """Apply the guard to a transcript: ``(segments kept, spans removed,
    segments dropped)``. A segment left without words is dropped."""
    if not prompt_tokens(prompt):
        return list(segments), [], 0
    kept_segments: list[Segment] = []
    all_spans: list[EchoSpan] = []
    dropped = 0
    for segment in segments:
        timed = bool(segment.words)
        words = segment.words if timed else _words_from_text(segment)
        kept, spans = strip_prompt_echo(words, prompt)
        if not spans:
            kept_segments.append(segment)
            continue
        all_spans.extend(spans)
        if not kept:
            dropped += 1
            continue
        text = _rebuild_text(kept)
        if not text:
            dropped += 1
            continue
        kept_segments.append(
            segment.model_copy(
                update={
                    "text": text,
                    "words": kept if timed else [],
                    "start_ms": kept[0].start_ms if timed else segment.start_ms,
                    "end_ms": kept[-1].end_ms if timed else segment.end_ms,
                }
            )
        )
    return kept_segments, all_spans, dropped
