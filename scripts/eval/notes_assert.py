#!/usr/bin/env python3
"""Regression checklists and the global writer assertions, as data.

    make eval-notes-assert NOTE_IDS=<uuid>,<uuid>     # stored notes' newest generations

Sprint R0 removed the pipeline arm that produced a document to check; ``check()`` and
``global_checks()`` stay as metrics and Sprint P3 rewires the live path to the notes the
writer (P1) stores. Output is check names, indices, taxonomy codes and PASS/FAIL, never
the string a check looks for. Exit 1 when any check fails.
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
import _normalize  # noqa: E402
import _textrules  # noqa: E402
from _common import REPO  # noqa: E402
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


_HOLDER_SUFFIX = re.compile(
    r"—\s*(?:laut|according to|за словами)\s+([^—.]+?)\s*[.!?]?\s*$", re.IGNORECASE
)
_IMPERSONAL = re.compile(
    r"^\s*(?:it is claimed|it was claimed|es wird behauptet|es wurde behauptet|стверджується)\b",
    re.IGNORECASE,
)


def global_checks(produced: dict[str, Any]) -> list[tuple[str, bool]]:
    """A2's writer contract on every fixture: no two consecutive sentences with the same
    holder suffix, no sentence opening impersonally, and an opening paragraph that is
    never a bare type label."""
    lines = [ln for ln in produced.get("lines", []) if (ln.get("text") or "").strip()]
    sentences: list[str] = []
    for ln in lines:
        if ln.get("kind") in ("summary", "framing", "bullet", "key_point"):
            sentences.extend(p.strip() for p in re.split(r"(?<=[.!?])\s+", ln["text"]) if p.strip())
    repeated = False
    previous: str | None = None
    for sentence in sentences:
        m = _HOLDER_SUFFIX.search(sentence)
        holder = m.group(1).strip().casefold() if m else None
        if holder and holder == previous:
            repeated = True
        previous = holder
    impersonal = any(_IMPERSONAL.match(re.sub(r"^\s*[-•*]\s*", "", s)) for s in sentences)
    labels = {
        v.casefold().rstrip(".")
        for table in _textrules.TYPE_LABELS.values()
        for v in table.values()
    }
    first = next((ln["text"] for ln in lines if ln.get("kind") == "framing"), "")
    bare = first.strip().rstrip(".").casefold() in labels if first.strip() else False
    return [
        ("no_repeated_holder_suffix", not repeated),
        ("no_impersonal_claim", not impersonal),
        ("p1_not_label", not bare),
        ("holder_named_per_run", holder_named_per_run(produced)),
        ("overview_first", overview_first(produced)),
    ]


_CLAIM_TYPES = frozenset(
    {"opinion", "prediction", "estimate", "proposal", "allegation", "statement",
     "reported", "unproven", "refuted"}
)  # fmt: skip


def holder_named_per_run(produced: dict[str, Any]) -> bool:
    """A2 T5 (deterministic): a line resting on a claim-type fact with a holder names that
    holder (its last word), or an earlier line of the same section already did — the run.
    Read from the item rows' ``fact_ids`` (cites) and the facts' ``attributed_to``."""
    facts = {f.get("item_key"): f for f in produced.get("facts") or []}
    if not facts or (produced.get("stats") or {}).get("attribution_implicit"):
        # Review step 3: one speaker or a memo — everything is theirs, no name is due.
        return True
    named_in: dict[str, set[str]] = {}
    for ln in produced.get("lines", []):
        text = _fold(ln.get("text") or "")
        if not text or ln.get("kind") in ("heading", "note", "claim"):
            continue
        section = str(ln.get("section_key") or "")
        seen = named_in.setdefault(section, set())
        for fid in ln.get("fact_ids") or []:
            fact = facts.get(fid)
            if not fact or (fact.get("certainty") or "") not in _CLAIM_TYPES:
                continue
            # "Bernd Walzmann, Finanzminister": the name is what a line carries, not the role.
            holder = _fold((fact.get("attributed_to") or "").split(",")[0])
            if not holder:
                continue
            last = holder.split()[-1]
            if last in text or holder in text:
                seen.add(last)
            elif last not in seen:
                return False
    return True


def overview_first(produced: dict[str, Any]) -> bool:
    """A2 T5: the first non-empty rendered section is the overview (role ``summary``); a
    transcript section never precedes it."""
    for section in produced.get("sections") or []:
        text = str(section.get("text") or "")
        has_lines = any((ln.get("text") or "").strip() for ln in section.get("lines") or [])
        if not text.strip() and not has_lines:
            continue
        return section.get("role") == "summary"
    return True


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
    # Review step 2: one normaliser with every scorer (reporting clauses and holder
    # suffixes fold away; compounds match by suffix).
    language = produced.get("language") or (meeting or {}).get("language") or "en"
    holders = frozenset(
        h
        for h in (
            *(checklist.get("speakers") or {}).values(),
            *(f.get("attributed_to") or "" for f in produced.get("facts") or []),
        )
        if h and str(h).strip()
    )

    def _has(text: str, needle: str) -> bool:
        return _normalize.contains(text, needle, language, holders=holders)

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
    # A2: three checks on every fixture, whatever the checklist says — the writer contract.
    for name, held in global_checks(produced):
        add(f"global.{name}", held, "global")
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
    # The presenter line, the contact line.
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
        from note_service.domain import entities

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
    type_labels = _textrules.TYPE_LABELS

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
        label = (type_labels.get(language) or type_labels["en"]).get(kind, "")
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


def family(name: str) -> str:
    return name.split("[", 1)[0].split(".", 1)[0]


DEFAULT_STORE_DSN = "postgresql://postgres:postgres@localhost:5432/notes"
_STORED_KIND = {"summary_sentence": "summary", "topic_bullet": "bullet", "framing": "framing"}


def _stored_lines(sections: list[dict[str, Any]], rows: list[Any]) -> list[dict[str, Any]]:
    """The rendered sections split into lines the global checks read, each line joined
    to its stored row (citations, kind) by text; a transcript or typed section has none."""
    by_text = {str(r["text"]).strip(): r for r in rows if r["cites"]}
    out: list[dict[str, Any]] = []
    for section in sections:
        first_paragraph = section.get("role") == "summary"
        for raw in str(section.get("text") or "").splitlines():
            text = raw.strip()
            if not text:
                continue
            if text.startswith("#"):
                out.append(
                    {
                        "section_key": section["section_key"],
                        "kind": "heading",
                        "text": text.lstrip("# "),
                        "fact_ids": [],
                    }
                )
                continue
            if text.startswith("|"):
                kind = "claim"
            elif text[:2] in ("- ", "* ", "• "):
                kind = "bullet"
            elif first_paragraph:
                kind, first_paragraph = "framing", False
            else:
                kind = "summary"
            content = re.sub(r"^[-*•]\s*", "", text)
            row = by_text.get(content) or by_text.get(content[:500])
            if row is not None:
                kind = _STORED_KIND.get(str(row["kind"]), kind)
            out.append(
                {
                    "section_key": section["section_key"],
                    "kind": kind,
                    "text": content,
                    "fact_ids": list(row["cites"]) if row is not None else [],
                }
            )
    return out


async def produced_from_store(dsn: str, note_id: str) -> dict[str, Any] | None:
    """Task 4 step 7: a stored note's newest generation in the shape the global checks
    read — sections and lines from the current version, facts and citations from the
    generated items, numbers from the generation's stats. Content stays in this
    process; only pass/fail leaves it."""
    import asyncpg

    sys.path.insert(0, str(REPO / "services" / "note-service" / "src"))
    from note_service.domain import roles
    from template_models import TemplateDefinition

    conn = await asyncpg.connect(dsn)
    try:
        gen = await conn.fetchrow(
            """SELECT id, stats FROM note_generations
               WHERE note_id = $1 AND status IN ('complete', 'partial')
               ORDER BY created_at DESC LIMIT 1""",
            note_id,
        )
        if gen is None:
            return None
        rows = await conn.fetch(
            """SELECT item_key, kind, section_key, text, cites, certainty, attributed_to, flags
               FROM note_generated_items WHERE note_id = $1 AND generation_id = $2""",
            note_id,
            gen["id"],
        )
        version = await conn.fetchrow(
            """SELECT v.content_jsonb, t.schema_jsonb FROM notes n
               JOIN note_versions v ON v.id = n.current_version_id
               LEFT JOIN templates t ON t.id = n.template_id WHERE n.id = $1""",
            note_id,
        )
    finally:
        await conn.close()
    if version is None:
        return None
    content = version["content_jsonb"]
    content = json.loads(content) if isinstance(content, str) else content
    schema = version["schema_jsonb"]
    schema = json.loads(schema) if isinstance(schema, str) else schema
    role_map: dict[str, str] = {}
    if schema:
        try:
            role_map = {
                k: str(v)
                for k, v in roles.role_map(TemplateDefinition.model_validate(schema)).items()
            }
        except Exception:  # noqa: BLE001 — an unreadable template leaves the roles unknown
            role_map = {}
    sections = [
        {
            "section_key": str(sec.get("section_key") or ""),
            "title": sec.get("title"),
            "role": role_map.get(str(sec.get("section_key") or "")),
            "text": sec.get("text") or "",
            "lines": [],
        }
        for sec in content.get("sections") or []
    ]
    stats = gen["stats"]
    stats = json.loads(stats) if isinstance(stats, str) else (stats or {})
    return {
        "sections": sections,
        "lines": _stored_lines(sections, rows),
        # Every stored row is a written line with its citations; a cited fact's certainty
        # and holder are what the row recorded for it (one holder when its facts agree).
        "facts": [
            {
                "item_key": cite,
                "certainty": r["certainty"],
                "attributed_to": r["attributed_to"],
                "flags": list(r["flags"] or []),
            }
            for r in rows
            for cite in (r["cites"] or [])
        ],
        "stats": stats,
    }


async def check_stored(dsn: str, note_ids: tuple[str, ...]) -> int:
    """The global assertions on stored notes; prints pass/fail per assertion per note."""
    failed = 0
    for note_id in note_ids:
        produced = await produced_from_store(dsn, note_id)
        if produced is None:
            print(f"{note_id[:8]}: no complete generation")
            failed += 1
            continue
        results = global_checks(produced)
        print(
            f"{note_id[:8]}: {sum(ok for _n, ok in results)}/{len(results)} global assertions"
            f" ({len(produced['lines'])} lines, {len(produced['facts'])} facts)"
        )
        for name, ok in results:
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")
            failed += 0 if ok else 1
    return 1 if failed else 0


def main(*_args: Any, **_kwargs: Any) -> int:
    """The live path (produce a note, then check it) returns with Sprint P3, reading the
    notes the writer stores. Until then only ``--note-ids`` runs."""
    print(
        "notes_assert: the live path was removed with the old writing path (Sprint R0);"
        " use --note-ids on stored notes, or wait for Sprint P3",
        file=sys.stderr,
    )
    return 3


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--note-ids",
        default="",
        help="run the global assertions on these stored notes' newest generations"
        " (no model call; content never leaves the process)",
    )
    ap.add_argument("--dsn", default=DEFAULT_STORE_DSN, help="with --note-ids: the notes DB")
    args = ap.parse_args()
    if args.note_ids:
        sys.exit(
            asyncio.run(
                check_stored(
                    args.dsn, tuple(i.strip() for i in args.note_ids.split(",") if i.strip())
                )
            )
        )
    sys.exit(main())
