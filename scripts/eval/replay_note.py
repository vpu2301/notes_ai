#!/usr/bin/env python3
"""Replay one immutable transcript through the document engine — no ASR — and say
why a proposition did or did not reach the note.

    uv run --project services/note-service --with pyyaml python scripts/eval/replay_note.py \
        --backend mistral_eu --input eval/notes/multilingual-real/r04_….json \
        [--multilingual] [--find '5[.,]?000|dividend'] [--show-text]

``--input`` is a result-view snapshot (``turns``/``segments``, as the worker reads it)
or a gold-format meeting (``transcript``). The header pins what produced the run:
git SHA, input hash and revision, prompt version, backend, model, capability profile,
output language. ``--find`` lists the transcript lines matching a pattern and what
became of every fact cited to them: extracted → excluded / dropped (and why) →
verified → merged → rendered. Text is printed only with ``--show-text``: this is a
local tool, its output is never a log.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REPO, Paced, load_registry  # noqa: E402


def _git_sha() -> str:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
        ).stdout.strip()

    return git("rev-parse", "--short", "HEAD") + ("+dirty" if git("status", "--porcelain") else "")


def as_meeting(data: dict[str, Any], name: str) -> dict[str, Any]:
    """A gold meeting as is; a result-view snapshot as the gold shape run_pipeline reads."""
    if "transcript" in data:
        return data
    from note_service.domain.meeting_doc import windows

    recording = data.get("language") or "en"
    transcript = [
        {
            "speaker": t.speaker_label or "SPEAKER_1",
            "t_start_ms": t.start_ms,
            "t_end_ms": t.end_ms,
            "text": t.text,
            **({"language": t.language} if t.language else {}),
        }
        for t in windows.turns_from_result(data)
    ]
    meeting = {"id": name, "language": recording, "meeting_type": "auto", "transcript": transcript}
    if data.get("noise"):
        meeting["noise"] = data["noise"]
    return meeting


def numbered_lines(meeting: dict[str, Any]) -> dict[int, Any]:
    """``{line number: piece}`` exactly as the engine numbers them."""
    from notes_eval import as_asr_result

    from note_service.domain.meeting_doc import windows

    turns = windows.prepare_turns(windows.turns_from_result(as_asr_result(meeting))).turns
    return {t.number: t for w in windows.build_windows(turns) for t in w.turns}


async def main(args: argparse.Namespace) -> int:
    from notes_eval import run_pipeline

    from models import build_chat_provider

    raw = args.input.read_bytes()
    meeting = as_meeting(json.loads(raw), args.input.stem)
    provider = Paced(build_chat_provider(load_registry().backend(args.backend, expect_kind="chat")))
    try:
        produced = await run_pipeline(
            meeting, provider, multilingual=args.multilingual, fidelity=args.fidelity
        )
    finally:
        if hasattr(provider, "aclose"):
            await provider.aclose()
    stats = produced["stats"]
    print(f"git            {_git_sha()}")
    print(f"input          {args.input.name} sha256:{hashlib.sha256(raw).hexdigest()[:16]}")
    print(f"input revision {stats.get('input_revision')}")
    print(f"prompt version {stats.get('prompt_version')}")
    print(f"multilingual   {stats.get('multilingual_evidence')}")
    print(f"backend/model  {produced.get('backend')} / {produced.get('model_id')}")
    print(
        f"profile        small_model={stats.get('small_model_profile')} "
        f"context={stats.get('context_window')} window_chars={stats.get('window_chars')}"
    )
    print(
        f"language       output={stats.get('output_language') or produced.get('language')} "
        f"recording={stats.get('recording_language')}"
    )
    print(
        f"run            {produced['seconds']:.0f}s, {produced['model_calls']} calls, "
        f"{produced['input_tokens']}+{produced['output_tokens']} tokens"
    )
    print(
        "\nper source language (lines, speech_ms, extracted → excluded / dropped → verified → merged → rendered):"
    )
    for code, counts in (stats.get("languages") or {}).items():
        print(f"  {code}: {json.dumps(counts, sort_keys=True)}")
    keys = (
        "facts_dropped_noise", "noise_flagged", "noise_confirmed", "noise_advisory",
        "noise_other_language_advisory", "noise_overridden", "excluded_language_ms",
        "facts_dropped_paraphrase", "facts_cross_language", "meaning_check",
        "meaning_unverified", "summary_fallback", "topics_fallback",
    )  # fmt: skip
    print("\nstages:")
    for key in keys:
        print(f"  {key}: {stats.get(key)}")
    print(f"  excluded_ranges: {stats.get('excluded_ranges')}")

    if args.find:
        pattern = re.compile(args.find, re.IGNORECASE)
        lines = numbered_lines(meeting)
        wanted = sorted(n for n, t in lines.items() if pattern.search(t.text))
        cited = Counter()
        rendered_ids = {i for ln in produced["lines"] for i in ln.get("fact_ids") or []}
        print(f"\n--find matched lines {wanted}")
        for n in wanted:
            piece = lines[n]
            print(
                f"\n[{n}] {piece.speaker_label} {piece.start_ms}ms lang={piece.language or meeting.get('language')}"
            )
            if args.show_text:
                print(f"    {piece.text}")
            # Lines are renumbered in a coverage window: place everything by time.
            within = range(piece.start_ms, max(piece.end_ms, piece.start_ms + 1))
            for t in produced["trace"]:
                if t.get("start_ms") in within:
                    cited[n] += 1
                    print(f"    extracted ({t['kind']}, window {t['window']}) → {t['outcome']}")
            for f in produced["facts"]:
                if f["start_ms"] in within:
                    fate = "rendered" if f["item_key"] in rendered_ids else "merged, not rendered"
                    flags = ",".join(f.get("flags") or []) or "-"
                    print(f"    kept {f['item_key']} ({f['kind']}, flags {flags}) → {fate}")
                    if args.show_text:
                        print(f"      text:  {f['text']}\n      quote: {f['quote']}")
            if not cited[n]:
                print("    no fact was extracted from this line")
            if any(r[0] <= piece.start_ms < r[1] for r in stats.get("excluded_ranges") or []):
                print("    the line lies in an excluded range")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backend", required=True)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--multilingual", action="store_true")
    ap.add_argument("--fidelity", action="store_true", help="with --multilingual")
    ap.add_argument("--find", default=None, help="regex over transcript lines")
    ap.add_argument("--show-text", action="store_true", help="print lines, facts and quotes")
    sys.exit(asyncio.run(main(ap.parse_args())))
