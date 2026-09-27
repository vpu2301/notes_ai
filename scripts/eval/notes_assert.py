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

Each check prints its error-taxonomy codes (``scripts/eval/taxonomy.py``,
``docs/eval/error-taxonomy.md``); a checklist may pin them per check under
``"codes"``.

Output is check names, indices, codes and PASS/FAIL — never the string a check
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
from taxonomy import check_codes  # noqa: E402

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
    # F3 — figures with their values and qualifiers, the presenter line,
    # the contact line.
    if "figures" in checklist:
        from notes_scoring import _name_match, _value

        made = [f["figure"] for f in produced.get("facts", []) if f.get("figure")]
        right = 0
        for want in checklist["figures"]:
            value = _value(want["value"])
            if any(
                _name_match(want["name"], m["name"])
                and _value(m["value"]) == value
                and (m.get("qualifier") or "") == want.get("qualifier", "")
                for m in made
            ):
                right += 1
        need = int(checklist.get("figures_min", len(checklist["figures"])))
        add("figures", right >= need, "figures")
        rows = [ln for ln in lines if ln.get("kind") == "figure"]
        add("figures_cited", bool(rows) and all(ln.get("fact_ids") for ln in rows), "figures")
    if "presenter_line" in checklist:
        add(
            "presenter_line",
            any(
                ln.get("kind") == "presenter"
                and _fold(ln["text"]) == _fold(checklist["presenter_line"])
                for ln in lines
            ),
            "presenter_line",
        )
    if checklist.get("contact_line"):
        add("contact_line", any(ln.get("kind") == "next_step" for ln in lines), "contact_line")
    # F3 amendment after r03 — adverts cut, the guest line, chapters, and
    # the overview as two paragraphs of prose.
    stats = produced.get("stats") or {}
    for i, reason in enumerate(checklist.get("excluded_reasons", [])):
        reasons = {r[2] for r in stats.get("excluded_ranges") or [] if len(r) > 2}
        add(f"excluded_reasons[{i}]", reason in reasons, "excluded_reasons")
    if "guest_line" in checklist:
        from note_service.domain.meeting_doc.render import GUEST_LABELS

        labels = {_fold(label) for label in GUEST_LABELS.values()}
        add(
            "guest_line",
            any(
                ln.get("kind") == "presenter"
                and _has(ln["text"], checklist["guest_line"])
                and _fold(ln["text"]).split(":", 1)[0] in labels
                for ln in lines
            ),
            "guest_line",
        )
    headed = [
        s
        for s in produced.get("sections") or []
        if s.get("role") == "topics" and (s.get("title") or "").strip()
    ]
    if "chapters_min" in checklist:
        add("chapters_min", len(headed) >= int(checklist["chapters_min"]), "chapters_min")
    if "overview" in checklist:
        add_overview(checklist["overview"], produced, add)
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


def add_overview(want: dict[str, Any], produced: dict[str, Any], add: Any) -> None:
    """The top of the note (F3 amendment §2.9): ``overview.<check>``."""
    from note_service.domain.meeting_doc.overview import TYPE_LABELS

    top = next(
        (s for s in produced.get("sections") or [] if s.get("section_key") == "gen:overview"),
        None,
    )
    text = (top or {}).get("text") or ""
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    first = paragraphs[0] if paragraphs else ""
    bullets = sum(1 for line in text.splitlines() if re.match(r"^\s*[-*] ", line))
    if "prose_paragraphs_min" in want:
        add(
            "overview.prose_paragraphs_min",
            len(paragraphs) >= int(want["prose_paragraphs_min"]) and not bullets,
            "overview",
        )
    if want.get("names_recording_type"):
        language = produced.get("language", "en")
        kind = (produced.get("stats") or {}).get("recording_type") or ""
        label = (TYPE_LABELS.get(language) or TYPE_LABELS["en"]).get(kind, "")
        add("overview.names_recording_type", bool(label) and _has(first, label), "overview")
    if "names_guest" in want:
        add("overview.names_guest", _has(first, want["names_guest"]), "overview")
    if "themes_min" in want:
        themes = (produced.get("brief") or {}).get("themes") or []
        written = sum(1 for t in themes if t.strip() and _has(first, t.strip().rstrip(".")))
        add("overview.themes_min", written >= int(want["themes_min"]), "overview")
    if "bullets_above_first_heading" in want:
        add(
            "overview.bullets_above_first_heading",
            bullets <= int(want["bullets_above_first_heading"]),
            "overview",
        )


# `--backend scripted`: the engine tests' deterministic stand-in for the
# model (no network, same answers every run) — what CI's notes-engine job
# runs, so a checklist check that passes there fails only when the ENGINE
# changed, never the model.
SCRIPTED = "scripted"
# What the engine guarantees whatever a model says: no label or default name
# for a named speaker, none of the audit's strings, every line cited. The
# other checks measure what a model extracted and are shown, not gated.
ENGINE_CHECKS = frozenset({"speakers", "must_not_contain", "every_line_cited", "no_marks"})
# F3 amendment: code writes the overview as prose and cuts adverts by cue,
# whatever the model says.
ENGINE_CHECK_NAMES = frozenset(
    {
        "overview.prose_paragraphs_min",
        "overview.bullets_above_first_heading",
        "excluded_reasons[0]",
    }
)


def family(name: str) -> str:
    return name.split("[", 1)[0].split(".", 1)[0]


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
                results = [
                    r
                    for r in results
                    if family(r[0]) in ENGINE_CHECKS or r[0] in ENGINE_CHECK_NAMES
                ]
            passed = sum(1 for _n, ok, _s in results if ok)
            print(f"{meeting['id']}: {passed}/{len(results)} checks pass")
            gated = {name for name, _ok, _s in results}
            for name, ok, sprint in shown:
                owner = f"  ({sprint})" if sprint else ""
                codes = check_codes(name, checklist)
                owner += f"  [{','.join(codes)}]" if codes else ""
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
