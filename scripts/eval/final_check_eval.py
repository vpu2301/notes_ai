#!/usr/bin/env python3
"""The final check (F1-02) against a corrupting composer, on a real model: the extractor
is right (each golden case's first faithful claim is the verified fact), the composer
writes every other claim of the case as a line citing that fact — faithful restatements
and corruptions (inverted comparison, dropped condition, changed recipient, …).

    uv run --project services/note-service --with pyyaml python scripts/eval/final_check_eval.py \
        --backend mistral_eu [--runs 3] [--corpus tests/fixtures/eval/notes/fidelity/golden_claims.json]

A corrupted line written as composed is critical. A faithful line kept as composed
counts for recall; a faithful line restored to its fact or repaired is safe but a
loss. Output is ids, outcomes and numbers; never claim text.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import Paced, load_registry  # noqa: E402
from fidelity_eval import DEFAULT, GATE_RECALL, build, claims_of  # noqa: E402

# A profile's stage texts (``--profile``), in place of the bundled ones.
OVERRIDES: dict[str, str] | None = None


def load_profile(path: Path) -> dict[str, str]:
    from note_service.domain import prompt_profiles as profiles

    config = profiles.ProfileConfig.model_validate(json.loads(path.read_text("utf-8"))["config"])
    return profiles.stage_overrides(config)


async def main(backend: str, corpus: Path, runs: int) -> int:
    from models import build_chat_provider
    from note_service.domain.meeting_doc import final_check, prompts, verify
    from note_service.domain.meeting_doc.render import Line, RenderedSection

    cases = json.loads(corpus.read_text("utf-8"))["cases"]
    provider = Paced(build_chat_provider(load_registry().backend(backend, expect_kind="chat")))
    outcome: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    critical: list[str] = []
    try:
        for run in range(1, runs + 1):
            for case in cases:
                claims = claims_of(case)
                window, fact, _ = build(case, claims[0])
                # The extractor's fact is verified: no pending meaning check left on it.
                fact.flags = [f for f in fact.flags if f != verify.MEANING_PENDING]
                for n, claim in enumerate(claims[1:], start=1):
                    _w, _f, language = build(case, claim)
                    composed = Line(f"- {claim['text'].rstrip('.')}", "bullet", (fact.item_key,))
                    section = RenderedSection(
                        section_key="gen:case", role="topics", text=composed.text,
                        title="Case", lines=(composed,),
                    )  # fmt: skip
                    tally: Counter[str] = Counter()
                    kept, rejected = await final_check.validate(
                        [section],
                        facts=[fact],
                        windows_by_index={0: window},
                        verifier=provider,
                        language=language,
                        task=prompts.task(language, overrides=OVERRIDES),
                        cache={},
                        tally=tally,
                    )
                    totals.update(tally)
                    written = [ln.text for s in kept for ln in s.lines]
                    fate = (
                        "held"
                        if rejected
                        else "kept"
                        if written == [composed.text]
                        else "repaired"
                        if tally["repaired"]
                        else "restored"
                        if tally["restored"]
                        else "fact_text"
                    )
                    faithful = bool(claim["faithful"])
                    outcome[f"{'faithful' if faithful else 'corrupt'}:{fate}"] += 1
                    if fate == "kept" and not faithful:
                        critical.append(f"run {run} {case['id']}[{n}] ({claim['corruption']})")
                    ok = (fate == "kept") == faithful
                    print(
                        f"{'ok ' if ok else 'BAD'} run {run} {case['id']}[{n}] faithful={faithful} → {fate}"
                    )
    finally:
        if hasattr(provider, "aclose"):
            await provider.aclose()
    faithful_total = sum(v for k, v in outcome.items() if k.startswith("faithful:"))
    recall = outcome["faithful:kept"] / faithful_total if faithful_total else 0.0
    print(f"\n{dict(sorted(outcome.items()))}")
    print(f"calls {totals['calls']}  latency {totals['latency_ms'] / 1000:.0f}s  "
          f"unavailable {totals['unavailable']}  timeout {totals['timeout']}  "
          f"malformed {totals['malformed']}  foreign_lines {totals['foreign_lines']}")  # fmt: skip
    print(f"faithful kept as composed: {recall:.2f} (gate {GATE_RECALL})")
    print(f"critical (corrupted written as composed): {len(critical)}")
    for line in critical:
        print(f"  {line}")
    passed = not critical and recall >= GATE_RECALL
    print("PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backend", required=True)
    ap.add_argument("--corpus", type=Path, default=DEFAULT)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--profile", type=Path, default=None, help="profile JSON: its stage texts")
    args = ap.parse_args()
    if args.profile is not None:
        OVERRIDES = load_profile(args.profile)
    sys.exit(asyncio.run(main(args.backend, args.corpus, args.runs)))
