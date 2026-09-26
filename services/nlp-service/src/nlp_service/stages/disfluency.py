"""Readable conversation transcripts without touching the words (Sprint I3 T3).

A conversation transcript is served verbatim (Sprint G0): no punctuation
model, no number or date rewriting. What a reader still trips over is the
speech itself — "uh", "um", "this is this is the swim platform" — and the
chunk-to-chunk casing the decoder leaves behind ("the tender garage takes"
starting a paragraph in lower case).

This stage hides, never deletes: a filler token or the first copy of an
immediate repeat is marked ``hidden`` and keeps its timing, the displayed
``text`` is rebuilt from the visible words, and the first visible word of
the segment is capitalised. ``raw_text`` on the served segment is the
decoder's own text; the note engine's ``normalise_quote`` drops the same
fillers, so a quote taken from either text verifies against the other.

Conversation only (``ctx.conversation``): dictation keeps every word the
person said, because there a filler may be the person's own word.
The filler table is ``tests/fixtures/glossary/../nlp/fillers.json``; the
test asserts this module's copy equals it.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Final

from ..pipeline.base import ProcessingContext, StageInput, StageOutput

FILLERS: Final[dict[str, frozenset[str]]] = {
    "en": frozenset({"uh", "um", "erm", "er", "hmm", "hm", "mm", "mhm", "ah", "eh", "uh-huh"}),
    "de": frozenset({"äh", "ähm", "hm", "hmm", "öh", "öhm", "mh"}),
    "uk": frozenset({"е", "ем", "мм", "ммм", "хм", "е-е", "а-а"}),
}
# An immediate repeat of up to this many words ("this is this is") hides
# the first copy; the later copy usually carries the punctuation.
MAX_REPEAT_WORDS: Final = 3

_EDGE_PUNCT = re.compile(r"^[^\w'-]+|[^\w'-]+$", re.UNICODE)


def token_of(text: str) -> str:
    """The comparison form of a word: case-folded, edge punctuation off."""
    return _EDGE_PUNCT.sub("", text).casefold()


def hidden_positions(tokens: list[str], language: str) -> set[int]:
    """Which word positions to hide: fillers, and the first copy of an
    immediate repeat among the words that remain."""
    fillers = FILLERS.get(language, frozenset())
    hidden = {i for i, tok in enumerate(tokens) if tok in fillers}
    visible = [i for i in range(len(tokens)) if i not in hidden]
    i = 0
    while i < len(visible):
        found = False
        for n in range(MAX_REPEAT_WORDS, 0, -1):
            first = [tokens[k] for k in visible[i : i + n]]
            second = [tokens[k] for k in visible[i + n : i + 2 * n]]
            if len(first) == n and first == second and all(first):
                hidden.update(visible[i : i + n])
                del visible[i : i + n]
                found = True
                break
        if not found:
            i += 1
    return hidden


def _capitalise_first(words: list[str]) -> list[str]:
    for k, word in enumerate(words):
        stripped = _EDGE_PUNCT.sub("", word)
        if not stripped:
            continue
        if stripped[0].isalpha() and stripped[0].islower():
            head = word.index(stripped[0])
            words[k] = word[:head] + word[head].upper() + word[head + 1 :]
        break
    return words


class DisfluencyStage:
    name = "disfluency"

    @property
    def runs_on_partials(self) -> bool:
        return False

    async def process(self, ctx: ProcessingContext, input: StageInput) -> StageOutput:
        passthrough = StageOutput(
            text=input.text,
            words=input.words,
            confidence_spans=input.confidence_spans,
            voice_commands=input.voice_commands,
            operations=input.operations,
            warnings=input.warnings,
            numeric_artifacts=input.numeric_artifacts,
            date_artifacts=input.date_artifacts,
        )
        if not ctx.conversation:
            return passthrough
        if input.words:
            tokens = [token_of(w.text) for w in input.words]
            hidden = hidden_positions(tokens, ctx.language)
            words = tuple(
                replace(w, hidden=True) if i in hidden else w for i, w in enumerate(input.words)
            )
            visible = _capitalise_first([w.text for w in words if not w.hidden])
            text = " ".join(visible)
        else:
            # No timings (an older artifact): the text's own tokens.
            pieces = input.text.split()
            hidden = hidden_positions([token_of(p) for p in pieces], ctx.language)
            words = input.words
            visible = _capitalise_first([p for i, p in enumerate(pieces) if i not in hidden])
            text = " ".join(visible)
        if not hidden and text == input.text:
            return passthrough
        return StageOutput(
            text=text,
            words=words,
            confidence_spans=(),  # recomputed by the confidence stage on the new text
            voice_commands=input.voice_commands,
            operations=input.operations,
            warnings=input.warnings,
            metadata={"disfluency.hidden": len(hidden)},
            numeric_artifacts=input.numeric_artifacts,
            date_artifacts=input.date_artifacts,
        )
