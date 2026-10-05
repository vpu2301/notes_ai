"""Known Whisper non-speech artefacts, loaded from ``artefacts.yaml``; shared by the eval harness and the worker."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

ARTEFACTS_PATH = Path(__file__).with_name("artefacts.yaml")

_PUNCT = re.compile(r"[^\w\s♪]+", re.UNICODE)


@dataclass(frozen=True)
class ArtefactPhrase:
    language: str
    text: str
    match: Literal["exact", "prefix"]
    drop: Literal["always", "if_nonspeech"]
    key: str  # normalised text

    def hits(self, normalised: str) -> bool:
        if self.match == "exact":
            return normalised == self.key
        return normalised == self.key or normalised.startswith(self.key + " ")


def normalise(text: str) -> str:
    """NFKC, casefold, punctuation to spaces, whitespace collapsed."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(_PUNCT.sub(" ", folded).split())


@cache
def load_artefacts(path: str | None = None) -> tuple[ArtefactPhrase, ...]:
    import yaml  # imported on first use

    raw = yaml.safe_load(Path(path or ARTEFACTS_PATH).read_text(encoding="utf-8"))
    out: list[ArtefactPhrase] = []
    for language, items in (raw.get("languages") or {}).items():
        for item in items:
            match = item.get("match", "exact")
            drop = item.get("drop", "always")
            if match not in ("exact", "prefix") or drop not in ("always", "if_nonspeech"):
                raise ValueError(f"artefacts.yaml: bad match/drop on {language} entry")
            key = normalise(item["text"])
            if not key:
                raise ValueError(f"artefacts.yaml: {language} entry normalises to nothing")
            out.append(ArtefactPhrase(language, item["text"], match, drop, key))
    return tuple(out)


def match_artefact(text: str, language: str | None = None) -> ArtefactPhrase | None:
    """The phrase ``text`` matches, or ``None``; ``language=None`` checks every language."""
    normalised = normalise(text)
    if not normalised:
        return None
    for phrase in load_artefacts():
        if language is not None and phrase.language != language:
            continue
        if phrase.hits(normalised):
            return phrase
    return None
