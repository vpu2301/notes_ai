#!/usr/bin/env python3
"""Regression checklists for the document engine: run the pipeline arm on every corpus
meeting with an ``<id>.assertions.json`` and check the findings as data.

    make eval-notes-assert BACKEND=dev_mac CORPUS=eval/notes/v2

Output is check names, indices, taxonomy codes and PASS/FAIL, never the string a check
looks for. Exit 1 when any check fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REPO, Paced, load_registry  # noqa: E402
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


_SPEAKER_LEADS = ("es sprechen", "with", "говорять")


def speaker_clause(lines: list[dict[str, Any]]) -> str:
    """Paragraph 1's list of who speaks (SQ3 T2): from its lead to the
    sentence's end."""
    for ln in lines:
        if ln.get("kind") not in ("framing", "presenter"):
            continue
        folded = _fold(ln["text"])
        for lead in _SPEAKER_LEADS:
            at = folded.find(lead + " ")
            if at >= 0:
                rest = ln["text"][at:]
                end = re.search(r"\.(?:\s|$)(?![^(]*\))", rest)
                return rest[: end.start()] if end else rest
    return ""


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
    titles = [str(s.get("title") or "") for s in produced.get("sections") or []]
    everything = "\n".join([*(ln["text"] for ln in lines), *titles, produced.get("title") or ""])
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

    # B1: no section heading shaped like this (a timestamp, a bare name).
    # B4: a row of the claims table — who, words of the claim, the speaker's verdict.
    claim_rows = [ln for ln in produced.get("lines", []) if ln.get("kind") == "claim"]
    for i, want in enumerate(checklist.get("claims_row", [])):
        found = any(
            any(_has(ln["text"], t) for t in want.get("claim", []))
            and (not want.get("who") or _has(ln["text"], want["who"]))
            and (not want.get("verdict") or any(_has(ln["text"], v) for v in want["verdict"]))
            for ln in claim_rows
        )
        add(f"claims_row[{i}]", found, "claims_row")
    for i, pattern in enumerate(checklist.get("headings_must_not_match", [])):
        add(
            f"headings_must_not_match[{i}]",
            not any(re.search(pattern, t.strip()) for t in titles if t.strip()),
            "headings_must_not_match",
        )

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

    # Statements, not quotes.
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
    # Figures with values and qualifiers, the presenter line, the contact line.
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
        # The presenter is named in paragraph 1 from the verified fields; every one must be there.
        want = checklist["presenter_line"].split(":", 1)[-1]
        name, _, rest = want.partition(",")
        fields = [name.strip(), *re.split(r"[(),]", rest)]
        framing = " ".join(ln["text"] for ln in lines if ln.get("kind") in ("framing", "presenter"))
        add(
            "presenter_line",
            all(_has(framing, f.strip()) for f in fields if f.strip()),
            "presenter_line",
        )
    if checklist.get("contact_line"):
        add("contact_line", any(ln.get("kind") == "next_step" for ln in lines), "contact_line")
    # Adverts cut, the guest line, chapters, the overview as prose.
    stats = produced.get("stats") or {}
    for i, reason in enumerate(checklist.get("excluded_reasons", [])):
        reasons = {r[2] for r in stats.get("excluded_ranges") or [] if len(r) > 2}
        add(f"excluded_reasons[{i}]", reason in reasons, "excluded_reasons")
    if "guest_line" in checklist:
        # The guest is named once among who speaks in paragraph 1, not merely mentioned.
        add("guest_line", _has(speaker_clause(lines), checklist["guest_line"]), "guest_line")
    headed = [
        s
        for s in produced.get("sections") or []
        if s.get("role") == "topics" and (s.get("title") or "").strip()
    ]
    if "chapters_min" in checklist:
        add("chapters_min", len(headed) >= int(checklist["chapters_min"]), "chapters_min")
    if "overview" in checklist:
        add_overview(checklist["overview"], produced, add)
    # At most this many lint findings per taxonomy code.
    if checklist.get("lint") and meeting is not None:
        from notes_scoring import lint_produced

        linted = lint_produced(meeting, produced)
        found = (linted.get("unresolved") or {}) if linted is not None else None
        for code, limit in sorted(checklist["lint"].items()):
            add(f"lint[{code}]", found is not None and found.get(code, 0) <= int(limit), "lint")
    # Multilingual evidence: a claim kept whole, cited to its original, never dropped for its language.
    for i, groups in enumerate(checklist.get("same_line", [])):
        add(
            f"same_line[{i}]",
            any(all(any(_has(ln["text"], m) for m in group) for group in groups) for ln in lines),
            "same_line",
        )
    facts_by_id = {f.get("item_key"): f for f in produced.get("facts") or []}
    for i, want in enumerate(checklist.get("source_cited", [])):
        add(
            f"source_cited[{i}]",
            any(
                any(_has(ln["text"], m) for m in want["match"])
                and any(
                    (facts_by_id.get(fid) or {}).get("source_language") == want["language"]
                    for fid in ln.get("fact_ids") or []
                )
                for ln in lines
            ),
            "source_cited",
        )
    framing = " ".join(ln["text"] for ln in lines if ln.get("kind") in ("framing", "presenter"))
    for i, forbidden in enumerate(checklist.get("framing_must_not_contain", [])):
        add(f"framing_must_not_contain[{i}]", not _has(framing, forbidden), "framing")
    for i, group in enumerate(checklist.get("framing_must_contain_any", [])):
        add(f"framing_must_contain_any[{i}]", any(_has(framing, alt) for alt in group), "framing")
    for prop in checklist.get("propositions", []):
        # An important proposition: every group's alternatives in ONE written line.
        add(
            f"proposition[{prop['id']}]",
            any(
                all(any(_has(ln["text"], alt) for alt in group) for group in prop["all"])
                for ln in content
            ),
            "propositions",
        )
    if checklist.get("no_grammar_corrections"):
        # F2-02: an article, an ending or capitals is never offered as a name correction.
        from note_service.domain.meeting_doc import entities

        grammar = [
            (c[0], c[1])
            for f in produced.get("facts") or []
            for c in f.get("corrections") or []
            if not entities.is_correction(str(c[0]), str(c[1]))
        ]
        add("no_grammar_corrections", not grammar, "corrections")
    for i, want in enumerate(checklist.get("count_max", [])):
        hits = sum(1 for ln in lines if any(_has(ln["text"], m) for m in want["match"]))
        add(f"count_max[{i}]", hits <= int(want["max"]), "count_max")
    if "excluded_language_ms_max" in checklist:
        add(
            "excluded_language_ms_max",
            int(stats.get("excluded_language_ms") or 0)
            <= int(checklist["excluded_language_ms_max"]),
            "excluded_language_ms_max",
        )
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


# The deterministic stand-in model CI runs: a check that passes there fails
# only when the ENGINE changed.
SCRIPTED = "scripted"
# What the engine guarantees whatever a model says; other checks are shown, not gated.
ENGINE_CHECKS = frozenset({"speakers", "must_not_contain", "every_line_cited", "no_marks"})
ENGINE_CHECK_NAMES = frozenset(
    {
        "overview.prose_paragraphs_min",
        "overview.bullets_above_first_heading",
        "excluded_reasons[0]",
        # Decided by code: a language-only exclusion is the engine's, not the model's.
        "excluded_language_ms_max",
    }
)


def family(name: str) -> str:
    return name.split("[", 1)[0].split(".", 1)[0]


def _scripted_provider() -> Any:
    tests = REPO / "services" / "note-service" / "tests" / "unit"
    sys.path.insert(0, str(tests))
    from meeting_doc_fakes import ScriptedProvider

    return ScriptedProvider()


# Release targets (docs/development/ai-notes-quality/stabilization/README.md): acceptance
# targets, not measured performance.
TARGET_SUPPORTED: Final = 0.95
TARGET_RECALL: Final = 0.90
TARGET_DUPLICATES: Final = 0.05
# Check families whose failure is a critical distortion, never averaged away.
CRITICAL_FAMILIES: Final = frozenset(
    {"must_not_contain", "same_line", "source_cited", "framing_must_not_contain",
     "framing_must_contain_any", "no_grammar_corrections", "hedged_must_keep"}
)  # fmt: skip
DUPLICATE_JACCARD: Final = 0.8


def _tokens(text: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"\w+", _fold(text)) if len(w) > 2)


def duplicate_bullets(lines: list[dict[str, Any]]) -> tuple[int, int]:
    """``(bullets repeating an earlier bullet, bullets)``: Jaccard >= 0.8 on content words."""
    bullets = [
        _tokens(ln["text"])
        for ln in lines
        if ln.get("kind") in ("bullet", "key_point") and ln.get("text")
    ]
    repeats = sum(
        1
        for i, b in enumerate(bullets)
        if b and any(len(b & a) / len(b | a) >= DUPLICATE_JACCARD for a in bullets[:i] if a)
    )
    return repeats, len(bullets)


class Report:
    """The release-target summary over every run, each figure with its denominator."""

    def __init__(self) -> None:
        self.runs = 0
        self.critical: list[str] = []
        self.weight_covered = 0.0
        self.weight_total = 0.0
        self.final = Counter[str]()
        self.duplicates = [0, 0]
        self.seconds = 0.0
        self.tokens = 0
        self.fallbacks = 0
        self.incomplete = 0

    def add(
        self,
        label: str,
        checklist: dict[str, Any],
        results: list[tuple[str, bool, str]],
        produced: dict[str, Any],
    ) -> None:
        self.runs += 1
        for name, ok, _sprint in results:
            if not ok and family(name) in CRITICAL_FAMILIES:
                self.critical.append(f"{label}: {name}")
        weights = {p["id"]: float(p.get("weight", 1)) for p in checklist.get("propositions", [])}
        for name, ok, _sprint in results:
            if name.startswith("proposition["):
                key = name[len("proposition[") : -1]
                self.weight_total += weights.get(key, 1.0)
                self.weight_covered += weights.get(key, 1.0) if ok else 0.0
        stats = produced.get("stats") or {}
        final = stats.get("final_check") or {}
        if final.get("ran"):
            self.final.update(
                {
                    k: int(v)
                    for k, v in final.items()
                    if isinstance(v, int) and not isinstance(v, bool)
                }
            )
        repeats, bullets = duplicate_bullets(produced.get("lines") or [])
        self.duplicates[0] += repeats
        self.duplicates[1] += bullets
        self.seconds += float(produced.get("seconds") or 0)
        self.tokens += int(produced.get("input_tokens") or 0) + int(
            produced.get("output_tokens") or 0
        )
        self.fallbacks += int(bool(stats.get("summary_fallback") or stats.get("topics_fallback")))
        self.incomplete += int(bool(stats.get("incomplete")))

    def print(self) -> None:
        def pct(a: float, b: float) -> str:
            return f"{a / b:.0%} ({a:g}/{b:g})" if b else "not measured (0)"

        f = self.final
        checked = (
            f["supported"]
            + f["repaired"]
            + f["contradicted"]
            + f["insufficient_evidence"]
            + f["undecided"]
        )
        print(f"\n== release targets over {self.runs} runs (acceptance targets, not a claim) ==")
        print(f"critical sentinel failures: {len(self.critical)} (target 0)")
        for line in self.critical:
            print(f"  {line}")
        print(
            f"final claims: {f['claims']} asserted; {f['fact_text']} verbatim verified facts; "
            f"{checked} checked by meaning, of which supported or repaired "
            f"{pct(f['supported'] + f['repaired'], checked)} (target {TARGET_SUPPORTED:.0%}); "
            f"restored to their fact {f['restored']}; held for review {f['unverified']}"
        )
        print(
            f"weighted important-proposition recall: {pct(self.weight_covered, self.weight_total)} "
            f"(target {TARGET_RECALL:.0%}; only cases with annotated propositions)"
        )
        print(f"duplicate bullets: {pct(*self.duplicates)} (target <= {TARGET_DUPLICATES:.0%})")
        print(
            f"runs incomplete: {self.incomplete}/{self.runs}; with a composition fallback: "
            f"{self.fallbacks}/{self.runs}; time {self.seconds:.0f}s; tokens {self.tokens}"
        )


async def main(
    backend_name: str,
    corpus: Path,
    *,
    multilingual: bool = False,
    runs: int = 1,
    fidelity: bool = False,
    profile: Path | None = None,
    length: str = "standard",
    output_language: str | None = None,
    ids: tuple[str, ...] = (),
    force_fallbacks: bool = False,
) -> int:
    from notes_eval import EngineBlindError, run_pipeline

    if force_fallbacks:
        from note_service.domain.meeting_doc import pipeline as _pipeline

        _pipeline.FORCE_FALLBACKS = True

    instructions: dict[str, str] | None = None
    if profile is not None:
        # A profile's three stage texts, exactly as a pinned version sends them.
        from note_service.domain import prompt_profiles as profiles

        config = profiles.ProfileConfig.model_validate(
            json.loads(profile.read_text("utf-8"))["config"]
        )
        problems = profiles.validate(config, [])
        if problems:
            print(f"profile refused: {[p.as_dict() for p in problems]}", file=sys.stderr)
            return 3
        instructions = profiles.stage_overrides(config)

    from models import ProviderError, build_chat_provider

    if not corpus.is_dir():
        print(f"corpus not found: {corpus}", file=sys.stderr)
        return 3
    cases = [
        (path, checklist)
        for path in sorted(corpus.glob("*.json"))
        if not path.name.endswith(".assertions.json")
        and (not ids or any(path.name.startswith(i) for i in ids))
        and (checklist := checklist_for(path)) is not None
    ]
    if not cases:
        print(f"no checklists for the meetings in {corpus}", file=sys.stderr)
        return 3

    if backend_name == SCRIPTED:
        provider = _scripted_provider()
    else:
        resolved = load_registry().backend(backend_name, expect_kind="chat")
        provider = Paced(build_chat_provider(resolved))
    failures = 0
    report = Report()
    try:
        for path, checklist in cases:
            meeting = json.loads(path.read_text("utf-8"))
            gold = meeting.setdefault("gold", {})
            # The checklist's roster is what a person would have named.
            gold.setdefault("speakers", dict(checklist.get("speakers") or {}))
            for run in range(1, runs + 1):
                label = f"{meeting['id']}" + (f" run {run}/{runs}" if runs > 1 else "")
                try:
                    produced = await run_pipeline(
                        meeting,
                        provider,
                        multilingual=multilingual,
                        fidelity=fidelity,
                        instructions=instructions,
                        length=length,
                        output_language=output_language,
                    )
                except (ProviderError, EngineBlindError) as exc:
                    print(f"{label}: RUN FAILED ({type(exc).__name__})")
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
                stats = produced.get("stats") or {}
                print(
                    f"{label}: {passed}/{len(results)} checks pass"
                    f"  ({produced.get('seconds', 0):.0f}s, {produced.get('model_calls', 0)} calls,"
                    f" {produced.get('input_tokens', 0)}+{produced.get('output_tokens', 0)} tokens,"
                    f" meaning {stats.get('meaning_check') or {}})"
                )
                if (stats.get("final_check") or {}).get("ran"):
                    final = {
                        k: v
                        for k, v in stats["final_check"].items()
                        if k not in ("ran", "version", "unverified_sources")
                    }
                    print(f"  final check {final}")
                gated = {name for name, _ok, _s in results}
                for name, ok, sprint in shown:
                    owner = f"  ({sprint})" if sprint else ""
                    codes = check_codes(name, checklist)
                    owner += f"  [{','.join(codes)}]" if codes else ""
                    verdict = ("PASS" if ok else "FAIL") if name in gated else "----"
                    note = "" if name in gated else "  (needs a model)"
                    print(f"  {verdict}  {name}{owner}{note}")
                failures += len(results) - passed
                report.add(label, checklist, results, produced)
    finally:
        if hasattr(provider, "aclose"):
            await provider.aclose()
    report.print()
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backend", required=True)
    ap.add_argument("--corpus", type=Path, default=REPO / "tests" / "fixtures" / "eval" / "notes")
    ap.add_argument(
        "--multilingual", action="store_true", help="as with MDX_NOTE_MULTILINGUAL_EVIDENCE=true"
    )
    ap.add_argument("--runs", type=int, default=1, help="every meeting this many times")
    ap.add_argument("--fidelity", action="store_true", help="as with MDX_NOTE_FIDELITY=true")
    ap.add_argument("--profile", type=Path, default=None, help="profile JSON: its stage texts")
    ap.add_argument("--length", choices=("short", "standard", "detailed"), default="standard")
    ap.add_argument("--output-language", choices=("en", "de", "uk"), default=None)
    ap.add_argument("--ids", default="", help="comma-separated meeting id prefixes to run")
    ap.add_argument(
        "--force-fallbacks", action="store_true", help="B1: the fallbacks measured on their own"
    )
    args = ap.parse_args()
    sys.exit(
        asyncio.run(
            main(
                args.backend,
                args.corpus,
                multilingual=args.multilingual,
                runs=args.runs,
                fidelity=args.fidelity,
                profile=args.profile,
                length=args.length,
                output_language=args.output_language,
                ids=tuple(i.strip() for i in args.ids.split(",") if i.strip()),
                force_fallbacks=args.force_fallbacks,
            )
        )
    )
