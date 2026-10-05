#!/usr/bin/env python3
"""Build ``freq_<de|en|uk>.txt`` (50 000 most frequent lower-cased forms) and
``names.txt`` for ``entity_unify`` from Tatoeba sentence exports (CC-BY 2.0 FR;
attribution in docs/legal/third-party-notices.md).

    python scripts/models/build_frequency_lists.py <dir with deu.tsv eng.tsv ukr.tsv>
"""

from __future__ import annotations

import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "libs/asr_models/src/asr_models/resources"
LANGS = {"de": "deu", "en": "eng", "uk": "ukr"}
TOP = 50_000
WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*", re.UNICODE)


def build(path: Path, lang: str) -> tuple[list[str], list[str]]:
    """The common forms, and the forms left out as names (en and uk only)."""
    counts: Counter[str] = Counter()
    mid_caps: Counter[str] = Counter()
    mid_total: Counter[str] = Counter()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3:
                continue
            text = unicodedata.normalize("NFKC", parts[2]).replace("’", "'")
            for k, m in enumerate(WORD.finditer(text)):
                tok = m.group(0)
                low = tok.casefold()
                counts[low] += 1
                if k > 0:
                    mid_total[low] += 1
                    if tok[:1].isupper():
                        mid_caps[low] += 1
    out: list[str] = []
    names: list[str] = []
    for word, _n in counts.most_common():
        if len(word) < 2 and word not in ("a", "i", "я", "в", "з", "у", "і", "й", "о"):
            continue
        if lang != "de" and mid_total[word] >= 3 and mid_caps[word] / mid_total[word] > 0.5:
            names.append(word)
            continue
        if len(out) < TOP:
            out.append(word)
    return out, names


def main(src: str) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for lang, code in LANGS.items():
        words, names = build(Path(src) / f"{code}.tsv", lang)
        (OUT / f"freq_{lang}.txt").write_text("\n".join(words) + "\n", encoding="utf-8")
        print(lang, len(words))
        if lang == "en":
            (OUT / "names.txt").write_text("\n".join(names) + "\n", encoding="utf-8")
            print("names", len(names))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
