#!/usr/bin/env python3
"""The meaning check on golden claims: faithful restatements (same language and across
languages) must be accepted, corrupted ones (a dropped condition, a swapped entity,
"could" → "will", a lost negation, support ↔ opposition, thousands → millions, a
hypothetical made a fact) must not be.

    uv run --project services/note-service --with pyyaml python scripts/eval/fidelity_eval.py \
        --backend mistral_eu [--runs 3] [--corpus tests/fixtures/eval/notes/fidelity/golden_claims.json]

Accepting is the act that counts: ``precision`` = faithful among accepted, ``recall`` =
faithful accepted of all faithful; both gates hold together, so rejecting everything
fails. Any corrupted claim accepted is critical. Output is ids, verdicts and numbers.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REPO, Paced, load_registry  # noqa: E402

DEFAULT = REPO / "tests" / "fixtures" / "eval" / "notes" / "fidelity" / "golden_claims.json"
# Provisional until the release gates are set by the bilingual review.
GATE_PRECISION = 0.95
GATE_RECALL = 0.85


def claims_of(case: dict[str, Any]) -> list[dict[str, Any]]:
    return [*case["claims"], *case.get("same_language_claims", [])]


def build(case: dict[str, Any], claim: dict[str, Any]) -> tuple[Any, Any, str]:
    """``(window, pending fact, output language)`` exactly as the engine hands them over."""
    from note_service.domain.meeting_doc import verify
    from note_service.domain.meeting_doc.windows import Turn, Window

    recording = case["recording_language"]
    turns = tuple(
        Turn(
            index=n,
            speaker_label=line["speaker"],
            speaker_name=line["name"],
            text=line["text"],
            start_ms=n * 15_000,
            end_ms=n * 15_000 + 14_000,
            line=n,
            language=line["language"] if line["language"] not in (None, recording) else None,
        )
        for n, line in enumerate(case["lines"])
    )
    cited = turns[case["cite"]]
    output = claim.get("output_language") or case["output_language"]
    fact = verify.VerifiedFact(
        kind="key_point",
        text=claim["text"],
        quote=case["quote"],
        turn=cited.index,
        line=cited.number,
        start_ms=cited.start_ms,
        end_ms=cited.end_ms,
        speaker_label=cited.speaker_label,
        speaker_name=cited.speaker_name,
        flags=[verify.MEANING_PENDING],
        source_language=cited.language or recording,
    )
    return Window(index=0, turns=turns), fact, output


async def main(backend: str, corpus: Path, runs: int) -> int:
    from models import build_chat_provider
    from note_service.domain.meeting_doc import pipeline, prompts

    cases = json.loads(corpus.read_text("utf-8"))["cases"]
    provider = Paced(build_chat_provider(load_registry().backend(backend, expect_kind="chat")))
    outcome: Counter[str] = Counter()
    critical: list[str] = []
    try:
        for run in range(1, runs + 1):
            for case in cases:
                for n, claim in enumerate(claims_of(case)):
                    window, fact, language = build(case, claim)
                    tally: Counter[str] = Counter()
                    verdicts = await pipeline._meaning_verdicts(
                        provider, [fact], window, language, tally, task=prompts.task(language)
                    )
                    found = verdicts.get(id(fact))
                    verdict = found.verdict if found else "undecided"
                    faithful = bool(claim["faithful"])
                    accepted = verdict == "supported"
                    outcome[f"{'faithful' if faithful else 'corrupt'}:{verdict}"] += 1
                    if accepted and not faithful:
                        critical.append(f"run {run} {case['id']}[{n}] ({claim['corruption']})")
                    mark = "ok " if accepted == faithful else "BAD"
                    print(f"{mark} run {run} {case['id']}[{n}] faithful={faithful} → {verdict}")
    finally:
        if hasattr(provider, "aclose"):
            await provider.aclose()
    accepted_faithful = outcome["faithful:supported"]
    accepted = accepted_faithful + outcome["corrupt:supported"]
    faithful_total = sum(v for k, v in outcome.items() if k.startswith("faithful:"))
    precision = accepted_faithful / accepted if accepted else 0.0
    recall = accepted_faithful / faithful_total if faithful_total else 0.0
    print(f"\n{dict(sorted(outcome.items()))}")
    print(
        f"precision {precision:.2f} (gate {GATE_PRECISION})  recall {recall:.2f} (gate {GATE_RECALL})"
    )
    print(f"critical (corrupted accepted): {len(critical)}")
    for line in critical:
        print(f"  {line}")
    passed = not critical and precision >= GATE_PRECISION and recall >= GATE_RECALL
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backend", required=True)
    ap.add_argument("--corpus", type=Path, default=DEFAULT)
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.backend, args.corpus, args.runs)))
