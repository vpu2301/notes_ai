#!/usr/bin/env python3
"""Regression checklists for the document engine (Summary Engine v2, Q1 T7).

    make eval-notes-assert BACKEND=dev_mac CORPUS=eval/notes/v2

For every meeting ``<id>.json`` in the corpus that has a checklist —
``<id>.assertions.json`` beside it, or in ``tests/fixtures/eval/notes/
assertions/`` — run the pipeline arm and check the audit's findings as
data. ``r01_de_zeit_was_jetzt`` is the 2026-09-22 audit itself; its
transcript is third-party content and lives only in the eval bucket and
``scripts/eval/local/`` (gitignored). The repo holds its checklist.

A checklist may say which sprint owns each check (``"sprint": {check:
"Q3"}``); the output reports it, so a failing check that belongs to a
later sprint reads as planned rather than as a regression.

Output is check names, indices and PASS/FAIL — never the string a check
looks for, so a run against the real corpus is safe to paste anywhere.
Exit 1 when any check fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REPO, load_registry  # noqa: E402
from notes_scoring import (  # noqa: E402
    copies_transcript,
    informs,
    recording_type_of,
    transcript_sentences,
)

ASSERTIONS = REPO / "tests" / "fixtures" / "eval" / "notes" / "assertions"
_CONTENT_KINDS_EXCLUDED = frozenset({"heading", "note"})


def _fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _has(text: str, needle: str) -> bool:
    return _fold(needle) in _fold(text)


def checklist_for(meeting_file: Path) -> dict[str, Any] | None:
    stem = meeting_file.name.removesuffix(".json")
    for candidate in (
        meeting_file.with_name(f"{stem}.assertions.json"),
        ASSERTIONS / f"{stem}.assertions.json",
    ):
        if candidate.is_file():
            return json.loads(candidate.read_text("utf-8"))
    return None


_MARKS = re.compile(r"❝|\[↗\]|\b[0-9a-f]{16}\b")


def check(
    checklist: dict[str, Any], produced: dict[str, Any], meeting: dict[str, Any] | None = None
) -> list[tuple[str, bool, str]]:
    """``[(check name, passed, owning sprint)]`` for one produced document.
    ``meeting`` (its transcript) is needed only by ``no_copied_lines``."""
    owners: dict[str, str] = checklist.get("sprint") or {}
    lines = [ln for ln in produced.get("lines", []) if ln.get("text", "").strip()]
    content = [ln for ln in lines if ln.get("kind") not in _CONTENT_KINDS_EXCLUDED]
    everything = "\n".join([*(ln["text"] for ln in lines), produced.get("title") or ""])
    out: list[tuple[str, bool, str]] = []

    def add(name: str, passed: bool, family: str) -> None:
        out.append((name, passed, owners.get(family, "")))

    if "recording_type" in checklist:
        stats = produced.get("stats") or {}
        got = stats.get("recording_type") or recording_type_of(
            (produced.get("brief") or {}).get("conversation_type")
        )
        add("recording_type", got == checklist["recording_type"], "recording_type")

    if "topics_min" in checklist:
        topics = {
            ln["section_key"]
            for ln in lines
            if str(ln.get("section_key", "")).startswith("gen:")
            and ln["section_key"] != "gen:overview"
        }
        add("topics_min", len(topics) >= int(checklist["topics_min"]), "topics_min")

    for label, _name in (checklist.get("speakers") or {}).items():
        # A named speaker never appears under its label or its default name.
        default = f"Speaker {label[8:]}" if label.startswith("SPEAKER_") else label
        add(
            f"speakers[{label}]",
            not (_has(everything, label) or _has(everything, default)),
            "speakers",
        )

    for i, forbidden in enumerate(checklist.get("must_not_contain", [])):
        add(f"must_not_contain[{i}]", not _has(everything, forbidden), "must_not_contain")

    for i, group in enumerate(checklist.get("must_contain_any", [])):
        add(
            f"must_contain_any[{i}]",
            any(_has(everything, alt) for alt in group),
            "must_contain_any",
        )

    for i, hedge in enumerate(checklist.get("hedged_must_keep", [])):
        matching = [ln for ln in content if _has(ln["text"], hedge["match"])]
        kept = bool(matching) and all(
            any(_has(ln["text"], m) for m in hedge["markers"]) for ln in matching
        )
        add(f"hedged_must_keep[{i}]", kept, "hedged_must_keep")

    exposed = produced.get("dates")
    for i, want in enumerate(checklist.get("dates", [])):
        got = None
        if exposed is not None:
            got = {_fold(d.get("text", "")): d.get("resolved") for d in exposed}.get(
                _fold(want["text"])
            )
        add(f"dates[{i}]", got == want["resolved"], "dates")

    if checklist.get("every_line_cited"):
        add("every_line_cited", all(ln.get("fact_ids") for ln in content), "every_line_cited")

    # F2 — statements, not quotes.
    language = (meeting or {}).get("language", "en")
    if checklist.get("no_copied_lines") and meeting is not None:
        sentences = transcript_sentences(meeting)
        add(
            "no_copied_lines",
            not any(copies_transcript(ln["text"], sentences) for ln in content),
            "no_copied_lines",
        )
    if "no_information_lines_max" in checklist:
        chatter = sum(1 for ln in content if not informs(ln["text"], ln.get("kind"), language))
        add(
            "no_information_lines",
            chatter <= int(checklist["no_information_lines_max"]),
            "no_information_lines",
        )
    if checklist.get("no_marks"):
        text = "\n".join([produced.get("note_text") or "", *(ln["text"] for ln in lines)])
        add("no_marks", not _MARKS.search(text), "no_marks")
    for i, topic in enumerate(checklist.get("topics", [])):
        under = [
            ln
            for ln in lines
            if any(_has(ln.get("section_title") or "", m) for m in topic["match"])
        ]
        add(
            f"topics[{i}]",
            bool(under)
            and len(under) <= int(topic.get("max_lines", 10**6))
            and sum(1 for ln in under if ln.get("parent")) >= int(topic.get("min_children", 0)),
            "topics",
        )
    return out


# `--backend scripted`: the engine tests' deterministic stand-in for the
# model (no network, same answers every run) — what CI's notes-engine job
# runs, so a checklist check that passes there fails only when the ENGINE
# changed, never the model.
SCRIPTED = "scripted"
# What the engine guarantees whatever a model says: no label or default name
# for a named speaker, none of the audit's strings, every line cited. The
# other checks measure what a model extracted and are shown, not gated.
ENGINE_CHECKS = frozenset({"speakers", "must_not_contain", "every_line_cited", "no_marks"})


def family(name: str) -> str:
    return name.split("[", 1)[0]


def _scripted_provider() -> Any:
    tests = REPO / "services" / "note-service" / "tests" / "unit"
    sys.path.insert(0, str(tests))
    from meeting_doc_fakes import ScriptedProvider

    return ScriptedProvider()


async def main(backend_name: str, corpus: Path) -> int:
    from notes_eval import EngineBlindError, run_pipeline

    from models import ProviderError, build_chat_provider

    if not corpus.is_dir():
        print(f"corpus not found: {corpus}", file=sys.stderr)
        return 3
    cases = [
        (path, checklist)
        for path in sorted(corpus.glob("*.json"))
        if not path.name.endswith(".assertions.json")
        and (checklist := checklist_for(path)) is not None
    ]
    if not cases:
        print(f"no checklists for the meetings in {corpus}", file=sys.stderr)
        return 3

    if backend_name == SCRIPTED:
        provider = _scripted_provider()
    else:
        resolved = load_registry().backend(backend_name, expect_kind="chat")
        provider = build_chat_provider(resolved)
    failures = 0
    try:
        for path, checklist in cases:
            meeting = json.loads(path.read_text("utf-8"))
            gold = meeting.setdefault("gold", {})
            # The checklist's roster is what a person would have named.
            gold.setdefault("speakers", dict(checklist.get("speakers") or {}))
            try:
                produced = await run_pipeline(meeting, provider)
            except (ProviderError, EngineBlindError) as exc:
                print(f"{meeting['id']}: RUN FAILED ({type(exc).__name__})")
                failures += 1
                continue
            shown = results = check(checklist, produced, meeting)
            if backend_name == SCRIPTED:
                results = [r for r in results if family(r[0]) in ENGINE_CHECKS]
            passed = sum(1 for _n, ok, _s in results if ok)
            print(f"{meeting['id']}: {passed}/{len(results)} checks pass")
            gated = {name for name, _ok, _s in results}
            for name, ok, sprint in shown:
                owner = f"  ({sprint})" if sprint else ""
                verdict = ("PASS" if ok else "FAIL") if name in gated else "----"
                note = "" if name in gated else "  (needs a model)"
                print(f"  {verdict}  {name}{owner}{note}")
            failures += len(results) - passed
    finally:
        if hasattr(provider, "aclose"):
            await provider.aclose()
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backend", required=True)
    ap.add_argument("--corpus", type=Path, default=REPO / "tests" / "fixtures" / "eval" / "notes")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.backend, args.corpus)))
