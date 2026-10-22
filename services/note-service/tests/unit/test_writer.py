"""Sprint P1 — the writer: prompts and windows, the Markdown parser (nothing lost), and
the job storing the model's text byte for byte."""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from models import ErrorKind, ProviderError
from note_models import NoteStatus
from note_service.domain import note_apply, note_markdown, prompts, writer
from note_service.domain.transcript import Turn
from note_service.jobs import generate_note

TENANT = UUID("22222222-2222-2222-2222-222222222222")


def _turns(minutes: int, *, turn_s: int = 30, speakers: int = 2) -> list[Turn]:
    out: list[Turn] = []
    n = 0
    while n * turn_s * 1000 < minutes * 60_000:
        start = n * turn_s * 1000
        out.append(
            Turn(
                index=n,
                speaker_label=f"SPEAKER_{n % speakers}",
                speaker_name=("Anna Keller", "Prof. Thomas Jäger")[n % speakers],
                text=f"Turn {n} says something about item {n} at minute {start // 60000}.",
                start_ms=start,
                end_ms=start + turn_s * 1000 - 1000,
                line=n,
            )
        )
        n += 1
    return out


@dataclass
class _Result:
    text: str
    input_tokens: int = 100
    output_tokens: int = 50
    latency_ms: int = 10
    backend: str = "scripted"
    model_id: str = "scripted-1"


class Scripted:
    """Answers in order; records every prompt."""

    def __init__(self, answers: list[Any]) -> None:
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []
        self.backend_name = "scripted"

    async def complete(self, prompt: str, schema: Any = None, **kw: Any) -> _Result:
        self.calls.append({"prompt": prompt, **kw})
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return _Result(text=answer)


# ── Prompts and windows ─────────────────────────────────────────────


def test_a_five_minute_interview_is_one_window_at_the_floor_with_the_texts_verbatim() -> None:
    turns = _turns(5)
    assert len(writer.windows(turns)) == 1
    assert writer.target_words(writer.speech_minutes(turns)) == 150
    template = writer.template_text("interview", "de")
    system, user = writer.build_prompt(
        turns,
        instruction_text="Schreibe für den CFO. Kurz.",
        template=template,
        template_name="interview",
        language="de",
        recording_date=date(2026, 10, 20),
    )
    # P2a: the system text is one sentence; the rules are the instructions text.
    assert system == prompts.WRITER["de"].format(language="Deutsch")
    assert "Schreibe für den CFO. Kurz." in user and writer.default_instructions() not in user
    assert template in user and "## Fragen und Antworten" in template
    assert "[00:00] Anna Keller: Turn 0" in user and "Transkript (5 Minuten, 2 Sprechende)" in user


def test_without_a_saved_text_the_prompt_carries_the_default_rules_filled_in() -> None:
    system, user = writer.build_prompt(
        _turns(2),
        instruction_text="  ",
        template="## Overview",
        template_name="meeting",
        language="en",
        recording_date=None,
    )
    default = writer.default_instructions()
    assert "{{words}}" in default and "{{date}}" in default and "{{language}}" in default
    expected = (
        default.replace("{{words}}", "150")
        .replace("{{date}}", "unknown")
        .replace("{{language}}", "English")
    )
    assert user.startswith(expected + "\n\nTemplate (meeting):\n## Overview")
    assert "{{" not in user
    # The old fixed rules paragraph is gone from the system text: one sentence only.
    assert system == prompts.WRITER["en"].format(language="English")
    assert "End every bullet" not in system


def test_a_saved_text_replaces_the_default_whole_and_placeholders_are_optional() -> None:
    plain = "Write for the CFO. Short."
    _, user = writer.build_prompt(
        _turns(2),
        instruction_text=plain,
        template="## Overview",
        template_name="meeting",
        language="en",
        recording_date=date(2026, 10, 20),
    )
    assert user.startswith(plain + "\n\nTemplate (meeting):")
    assert "End every bullet" not in user
    with_holes = "About {{words}} words, dated {{date}}, in {{language}}."
    _, user = writer.build_prompt(
        _turns(2),
        instruction_text=with_holes,
        template="## Overview",
        template_name="meeting",
        language="de",
        recording_date=date(2026, 10, 20),
    )
    assert user.startswith("About 150 words, dated 2026-10-20, in Deutsch.")


def test_the_default_rules_file_is_part_of_the_fingerprint(monkeypatch) -> None:  # noqa: ANN001
    before = prompts.fingerprint()
    original = writer.default_instructions
    monkeypatch.setattr(writer, "default_instructions", lambda: original() + "\nMore.")
    assert prompts.fingerprint() == before  # the hash reads the file, not the function
    folder = (
        __import__("importlib").resources.files("note_service.domain").joinpath("writer_templates")
    )
    assert folder.joinpath(writer.DEFAULT_INSTRUCTIONS).is_file()


def test_a_seventy_minute_transcript_is_three_windows_with_continuations_and_one_merge() -> None:
    turns = _turns(70)
    chunks = writer.windows(turns)
    assert len(chunks) == 3
    assert [c[0].index for c in chunks] == [0, 50, 100]  # cut at turn boundaries
    assert all(c[-1].end_ms - c[0].start_ms <= 25 * 60_000 for c in chunks)
    provider = Scripted(["# A\n\n## Overview\n- one [00:10]", "# A\n\n## Overview\n- two [30:10]",
                         "# A\n\n## Overview\n- three [55:10]", "# Final\n\n## Overview\n- all [00:10, 30:10]"])  # fmt: skip
    import asyncio

    out = asyncio.run(
        writer.write(
            turns,
            provider=provider,
            language="en",
            recording_date=None,
            instruction_text=None,
            template_name="meeting",
        )
    )
    assert len(provider.calls) == 4
    assert "The note so far:\n# A\n\n## Overview\n- one [00:10]" in provider.calls[1]["prompt"]
    assert "Continue the note" in provider.calls[2]["prompt"]
    merge = provider.calls[3]["prompt"]
    assert "Write the single final note" in merge and "--- part 3 of 3 ---" in merge
    assert out.text == "# Final\n\n## Overview\n- all [00:10, 30:10]"
    assert out.stats["windows"] == 3 and out.stats["calls"] == 4
    assert out.stats["tokens_in"] == 400 and out.stats["merge_failed"] is False
    assert out.stats["target_words"] == 1_500


def test_a_failed_merge_stores_the_parts_in_order_behind_one_status_line() -> None:
    import asyncio

    down = ProviderError(ErrorKind.UNAVAILABLE, "down", backend="s")
    provider = Scripted(["part one", "part two", down, down])
    out = asyncio.run(
        writer.write(
            _turns(40),
            provider=provider,
            language="en",
            recording_date=None,
            instruction_text=None,
            template_name="meeting",
        )
    )
    assert out.stats["merge_failed"] is True
    assert out.text == "(merge failed — parts in order)\n\npart one\n\npart two"


def test_cached_parts_are_not_written_again() -> None:
    import asyncio

    provider = Scripted(["part three", "final"])
    seen: list[list[str]] = []

    async def on_part(parts: list[str]) -> None:
        seen.append(parts)

    out = asyncio.run(
        writer.write(
            _turns(70),
            provider=provider,
            language="en",
            recording_date=None,
            instruction_text=None,
            template_name="meeting",
            done_parts=["part one", "part two"],
            on_part=on_part,
        )
    )
    assert out.parts == ["part one", "part two", "part three"] and out.text == "final"
    assert seen == [["part one", "part two", "part three"]]


def test_the_template_follows_the_authors_type_then_their_choice_else_auto() -> None:
    assert writer.template_name_for("client", "meeting_notes", False) == "client_call"
    assert writer.template_name_for("auto", "sales_call_uk", True) == "client_call"
    assert writer.template_name_for(None, "sales_call", False) == "auto"
    assert writer.template_name_for("auto", None, False) == "auto"
    for name in (*writer.TEMPLATES, writer.AUTO):
        for lang in prompts.LANGUAGES:
            assert len(writer.template_text(name, lang).splitlines()) <= 15, (name, lang)


def test_a_workspace_override_replaces_the_built_in_and_the_note_template_wins() -> None:
    override = "## Agenda\n*Only the agenda.*"
    assert writer.template_text("meeting", "en", override) == override
    assert writer.template_text("meeting", "en", "  ") == writer.template_text("meeting", "en")
    assert (
        writer.template_name_for("client", "sales_call", True, note_template="interview")
        == "interview"
    )
    assert writer.template_name_for("client", None, False, note_template="auto") == "client_call"
    assert prompts.fingerprint() != ""


# ── The parser ──────────────────────────────────────────────────────

NOTE = """# Council adopts the budget 2027 with a 3 % levy

Template: public_meeting

## Overview
The council met on Monday with eleven members present. It adopted the 2027 budget.

## Votes
| Item | Result | Ayes/Nays |
|---|---|---|
| CB 26-0412 budget | adopted | 11-0 [41:02] |
| CB 26-0417 levy | failed | 5-6 [52:10] |

## Agenda items
### Budget
- Torres: the levy funds 231 new units [12:34]
- The finance director expects a shortfall of $4.2m in 2028 [12:50, 41:02]
  - Sub-point as said [13:00]

### Claims
| Who | Claim | What the speaker said | Time |
|---|---|---|---|
| Resident | the shelter is unsafe | disputed by Torres | [20:00] |

> A quoted block nobody asked for
1. A numbered line

## Next steps
- Second reading on Tuesday [99:00]
"""


def _parse(text: str = NOTE) -> note_markdown.ParsedNote:
    return note_markdown.parse(text, _turns(60))


def test_parse_reads_title_template_sections_bullets_tables_and_unknown_syntax() -> None:
    note = _parse()
    assert note.title == "Council adopts the budget 2027 with a 3 % levy"
    assert note.template_name == "public_meeting"
    assert [s.heading for s in note.sections] == [
        "Overview", "Votes", "Agenda items", "Budget", "Claims", "Next steps"
    ]  # fmt: skip
    assert [s.level for s in note.sections] == [2, 2, 2, 3, 3, 2]
    assert [s.key for s in note.sections] == [
        "gen:overview", "gen:votes", "gen:agenda-items", "gen:agenda-items-budget",
        "gen:agenda-items-claims", "gen:next-steps",
    ]  # fmt: skip
    kinds = [(s.heading, i.kind) for s, i in note.items]
    assert kinds == [
        ("Overview", "paragraph"),
        ("Votes", "vote"),
        ("Votes", "vote"),
        ("Budget", "bullet"),
        ("Budget", "bullet"),
        ("Budget", "bullet"),
        ("Claims", "claim"),
        ("Claims", "paragraph"),
        ("Next steps", "bullet"),
    ]
    items = [i for _s, i in note.items]
    assert items[3].text == "Torres: the levy funds 231 new units" and items[3].cites == [25]
    assert items[4].cites == [25, 82] and items[4].text.endswith("in 2028")
    assert items[1].table_row == {
        "header": ["Item", "Result", "Ayes/Nays"],
        "cells": ["CB 26-0412 budget", "adopted", "11-0 [41:02]"],
    }
    assert items[1].cites == [82] and items[6].cites == [40]
    assert items[7].text == "> A quoted block nobody asked for\n1. A numbered line"
    # 99:00 is past the end of a 60-minute recording: nothing cited, counted.
    assert items[8].cites == [] and items[8].cite_nearest is False and note.bad_cites == 1
    assert note.unstructured is False


def test_nothing_is_lost_word_count_round_trip() -> None:
    note = _parse()

    def words(text: str) -> list[str]:
        body, _times = note_markdown.split_cites(text)
        return [
            w
            for w in body.replace("|", " ").split()
            if not note_markdown._TIME.fullmatch(w.strip("[],"))
        ]

    source: list[str] = []
    for ln in NOTE.splitlines():
        if not ln.strip() or ln.startswith("#") or ln.startswith("Template:"):
            continue
        if note_markdown._TABLE_RULE.match(ln) or ln.lstrip().startswith(("| Item", "| Who")):
            continue
        source += words(ln.lstrip("-* ").strip())
    stored = [w for _s, i in note.items for w in words(i.text)]
    assert stored == source


def test_a_time_in_a_gap_cites_the_nearest_turn_and_is_flagged() -> None:
    turns = [
        Turn(index=0, speaker_label="S1", speaker_name=None, text="a", start_ms=0, end_ms=10_000, line=0),
        Turn(index=1, speaker_label="S1", speaker_name=None, text="b", start_ms=60_000, end_ms=70_000, line=1),
    ]  # fmt: skip
    note = note_markdown.parse(
        "# T\n\n## S\n- in the gap [00:40]\n- inside [00:05]\n- late [01:30]", turns
    )
    items = [i for _s, i in note.items]
    assert items[0].cites == [1] and items[0].cite_nearest is True
    assert items[1].cites == [0] and items[1].cite_nearest is False
    assert items[2].cites == [] and note.bad_cites == 1


def test_a_code_fence_around_the_note_is_structure_not_a_title() -> None:
    note = note_markdown.parse(
        "```markdown\n# Title\nTemplate: broadcast\n\n## S\n- a [00:05]\n```\n", _turns(1)
    )
    assert note.title == "Title" and note.template_name == "broadcast"
    assert [i.text for _s, i in note.items] == ["a"]


@pytest.mark.parametrize(
    ("line", "heading"),
    [
        ("**ÜBERBLICK**", "ÜBERBLICK"),
        ("**Überblick:**", "Überblick"),
        ("**Überblick**:", "Überblick"),
        ("__Mitwirkende__", "Mitwirkende"),
    ],
)
def test_a_bold_only_line_is_a_level_2_heading(line: str, heading: str) -> None:
    note = note_markdown.parse(f"# T\n\n{line}\n- a bullet\n", [])
    assert [(s.heading, s.level) for s in note.sections] == [(heading, 2)]
    assert [(i.kind, i.text) for _s, i in note.items] == [("bullet", "a bullet")]


def test_bold_inside_a_line_and_hash_headings_are_unchanged() -> None:
    note = note_markdown.parse("# T\n\n## Überblick\nDas ist **wichtig** hier\n", [])
    assert [(s.heading, s.level) for s in note.sections] == [("Überblick", 2)]
    assert [(i.kind, i.text) for _s, i in note.items] == [("paragraph", "Das ist **wichtig** hier")]


def test_a_note_without_headings_is_one_section_called_note() -> None:
    note = note_markdown.parse("Just a title\n\nA paragraph the model wrote.\n\n- and a bullet", [])
    assert note.title == "Just a title" and note.unstructured is True
    assert [s.heading for s in note.sections] == ["Note"]
    assert [i.kind for _s, i in note.items] == ["paragraph", "bullet"]


def test_item_rows_carry_the_cited_turn_as_evidence_in_order() -> None:
    turns = _turns(60)
    rows = generate_note.item_rows(_parse(), turns)
    assert [r["position"] for r in rows] == list(range(9))
    assert rows[3]["quote"] == turns[25].text and rows[3]["start_ms"] == turns[25].start_ms
    assert rows[3]["cites"] == ["turn:25"] and rows[3]["speaker_name"] == turns[25].speaker_name
    assert rows[8]["quote"] == "" and rows[8]["start_ms"] == 0 and rows[8]["cites"] == []
    assert rows[1]["table_row"]["cells"][1] == "adopted" and rows[1]["kind"] == "vote"
    assert len({r["item_key"] for r in rows}) == len(rows)


def test_two_owner_lines_that_differ_only_in_their_due_part_both_get_a_row() -> None:
    md = (
        "# T\n\n## S\n"
        "- Councilmember Gilmour: Missed filing deadline due to timing of the declaration. [00:05]\n"
        "- Councilmember Gilmour: Missed filing deadline due to emergency declaration timing. [00:10]\n"
    )
    rows = generate_note.item_rows(note_markdown.parse(md, _turns(1)), _turns(1))
    assert len(rows) == 2 and len({r["item_key"] for r in rows}) == 2


# ── The job ─────────────────────────────────────────────────────────


class _Store:
    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.objects: dict[str, bytes] = {}
        self.snapshot = snapshot
        self.deleted: list[str] = []

    async def get(self, *, key: str, tenant_id: UUID, aad: bytes) -> bytes:
        if key.endswith(generate_note.PARTS_SUFFIX):
            if key not in self.objects:
                raise KeyError(key)
            return self.objects[key]
        return json.dumps(self.snapshot).encode("utf-8")

    async def put(self, *, key: str, plaintext: bytes, tenant_id: UUID, aad: bytes) -> None:
        self.objects[key] = plaintext

    async def delete(self, *, key: str) -> None:
        self.deleted.append(key)


def _result(minutes: int) -> dict[str, Any]:
    turns = _turns(minutes)
    return {
        "language": "en",
        "speaker_names": {"SPEAKER_0": "Anna Keller", "SPEAKER_1": "Prof. Thomas Jäger"},
        "turns": [
            {"speaker": t.speaker_label, "name": t.speaker_name, "start_ms": t.start_ms,
             "end_ms": t.end_ms, "paragraphs": [t.text]}
            for t in turns
        ],
    }  # fmt: skip


def _rig(
    monkeypatch: pytest.MonkeyPatch,
    provider: Any,
    minutes: int = 5,
    *,
    template: str | None = None,
    override: str | None = None,
    instructions: str | None = None,
) -> SimpleNamespace:
    generation_id, note_id = uuid4(), uuid4()
    marks: list[dict[str, Any]] = []
    stored: list[list[dict[str, Any]]] = []
    gen = SimpleNamespace(
        id=generation_id, status="queued", snapshot_key=f"{TENANT}/generation/{note_id}/{generation_id}.json",
        requested_by=uuid4(),
    )  # fmt: skip
    note = SimpleNamespace(
        id=note_id,
        status=NoteStatus.DRAFT,
        template_source=None,
        created_at=None,
        template=template,
    )
    store = _Store(_result(minutes))

    async def _override(conn: Any, *, tenant_id: UUID, name: str, language: str) -> Any:
        return SimpleNamespace(markdown=override) if override else None

    async def _instructions(
        conn: Any, deps: Any, tenant_id: UUID, note_id: UUID, family: Any
    ) -> str | None:
        return instructions

    monkeypatch.setattr(generate_note.templates_repo, "fetch", _override)
    monkeypatch.setattr(generate_note, "_instructions_text", _instructions)

    @contextlib.asynccontextmanager
    async def _conn(pool: Any, tenant_id: UUID):  # noqa: ANN202
        yield SimpleNamespace(fetchval=_fetchval)

    async def _fetchval(query: str, *args: Any) -> Any:
        return "meeting_notes"

    async def _fetch(conn: Any, *, generation_id: UUID) -> Any:
        return gen

    async def _fetch_note(conn: Any, *, note_id: UUID) -> Any:
        return note

    async def _meeting(conn: Any, *, note_id: UUID) -> Any:
        return None

    async def _mark(conn: Any, **kw: Any) -> None:
        marks.append(kw)

    async def _replace(conn: Any, *, rows: list[dict[str, Any]], **kw: Any) -> int:
        stored.append(rows)
        return len(rows)

    async def _supersede(conn: Any, **kw: Any) -> None:
        return None

    async def _clear(conn: Any, *, generation_id: UUID) -> str:
        return gen.snapshot_key

    applied: list[dict[str, Any]] = []

    async def _apply(conn: Any, **kw: Any) -> Any:
        # P3: the note's sections and title; the plan itself is tested on its own.
        applied.append(kw)
        return note_apply.Outcome(
            version_number=2,
            written_sections=[sec.key for sec in kw["parsed"].sections],
            section_hashes={sec.key: "h" for sec in kw["parsed"].sections},
            title_written=bool(kw["parsed"].title),
        )

    checks: list[dict[str, Any]] = []

    async def _set_checks(conn: Any, **kw: Any) -> int:
        checks.append(kw)
        return len(kw["unsupported"])

    monkeypatch.setattr(generate_note.note_apply, "apply", _apply)
    monkeypatch.setattr(generate_note.gen_repo, "set_checks", _set_checks)
    monkeypatch.setattr(generate_note, "tenant_connection", _conn)
    monkeypatch.setattr(generate_note.gen_repo, "fetch", _fetch)
    monkeypatch.setattr(generate_note.repo, "fetch_note", _fetch_note)
    monkeypatch.setattr(generate_note.meetings, "fetch", _meeting)
    monkeypatch.setattr(generate_note.gen_repo, "mark", _mark)
    monkeypatch.setattr(generate_note.gen_repo, "replace_lines", _replace)
    monkeypatch.setattr(generate_note.gen_repo, "supersede_previous", _supersede)
    monkeypatch.setattr(generate_note.gen_repo, "clear_snapshot", _clear)

    async def provider_for(workspace_id: str) -> Any:
        return provider

    deps = generate_note.GenerationDeps(
        app_pool=object(), transcripts_store=store, provider_for=provider_for
    )
    return SimpleNamespace(
        deps=deps, marks=marks, stored=stored, store=store, applied=applied, checks=checks,
        payload={"generation_id": str(generation_id), "note_id": str(note_id)},
    )  # fmt: skip


CASSETTE = "# Handala and the Iran deal\n\nTemplate: interview\n\n## Overview\n- Welchering says the 2022 deal is dead [00:10]\n\n## Positions and assessments\n- Boniat: it will fail [00:40]\n"


def test_the_job_stores_the_models_text_byte_for_byte_and_the_items_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    rig = _rig(monkeypatch, Scripted([CASSETTE]))
    out = asyncio.run(
        generate_note.handle_generate(rig.deps, tenant_id=TENANT, payload=rig.payload)
    )
    final = rig.marks[-1]
    assert final["status"] == "complete" and final["text"] == CASSETTE
    assert final["stats"]["words"] == len(CASSETTE.split())
    assert (
        final["stats"]["template"] == "interview"
        and final["stats"]["template_chosen"] == "interview"
    )
    assert final["stats"]["windows"] == 1 and final["stats"]["calls"] == 1
    assert final["stats"]["bad_cites"] == 0 and final["stats"]["unstructured"] is False
    assert final["stats"]["build"]["prompt_version"] == prompts.PROMPT_VERSION
    (rows,) = rig.stored
    assert [r["text"] for r in rows] == [
        "Welchering says the 2022 deal is dead",
        "Boniat: it will fail",
    ]
    assert out == {"items_stored": 2, "text_chars": len(CASSETTE)}
    # The snapshot and the window cache are gone once the generation committed.
    assert rig.store.deleted[-1].endswith(generate_note.PARTS_SUFFIX)


def test_a_provider_error_after_backoff_raises_for_the_job_retry_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    rig = _rig(monkeypatch, Scripted([ProviderError(ErrorKind.RATE_LIMITED, "429", backend="s")]))
    with pytest.raises(ProviderError):
        asyncio.run(generate_note.handle_generate(rig.deps, tenant_id=TENANT, payload=rig.payload))
    assert rig.stored == []
    assert all(m.get("status") != "complete" for m in rig.marks)
    # The generation row is settled by the runner's on_dead → mark_dead, not here.
    assert rig.marks[-1] == {
        "generation_id": rig.marks[-1]["generation_id"],
        "status": "running",
        "step": "write",
    }


def test_finished_windows_are_cached_and_reused_after_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    rig = _rig(
        monkeypatch,
        Scripted(["w1", ProviderError(ErrorKind.TIMEOUT, "t", backend="s")]),
        minutes=40,
    )
    with pytest.raises(ProviderError):
        asyncio.run(generate_note.handle_generate(rig.deps, tenant_id=TENANT, payload=rig.payload))
    cached = [k for k in rig.store.objects if k.endswith(generate_note.PARTS_SUFFIX)]
    assert cached and json.loads(rig.store.objects[cached[0]]) == ["w1"]
    # The retry gets the second window and the merge only.
    retry = Scripted(["w2", "# Merged\n\n## Overview\n- all [00:10]"])
    rig.deps.provider_for = lambda ws: _async(retry)
    asyncio.run(generate_note.handle_generate(rig.deps, tenant_id=TENANT, payload=rig.payload))
    assert len(retry.calls) == 2 and "The note so far:\nw1" in retry.calls[0]["prompt"]
    assert rig.marks[-1]["text"].startswith("# Merged")


def test_a_note_created_with_a_template_sends_it_and_records_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    provider = Scripted(["# T\n\n## Overview\n- a [00:10]"])
    rig = _rig(
        monkeypatch, provider, template="interview", instructions="Write for the CFO. Short."
    )
    asyncio.run(generate_note.handle_generate(rig.deps, tenant_id=TENANT, payload=rig.payload))
    prompt = provider.calls[0]["prompt"]
    assert "Template (interview):" in prompt and writer.template_text("interview", "en") in prompt
    # Acceptance 1: the instruction text reaches the prompt verbatim.
    assert "Write for the CFO. Short." in prompt
    stats = rig.marks[-1]["stats"]
    assert stats["template"] == "interview" and stats["template_requested"] == "interview"
    assert stats["template_source"] == "builtin"


def test_auto_stores_the_template_the_model_named(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    rig = _rig(monkeypatch, Scripted([CASSETTE]))
    asyncio.run(generate_note.handle_generate(rig.deps, tenant_id=TENANT, payload=rig.payload))
    stats = rig.marks[-1]["stats"]
    assert stats["template_requested"] == "auto" and stats["template"] == "interview"


def test_a_workspace_override_is_what_the_prompt_carries(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    provider = Scripted(["# T\n\n## Agenda\n- a [00:10]"])
    rig = _rig(monkeypatch, provider, template="meeting", override="## Agenda\n*Only the agenda.*")
    asyncio.run(generate_note.handle_generate(rig.deps, tenant_id=TENANT, payload=rig.payload))
    assert "## Agenda\n*Only the agenda.*" in provider.calls[0]["prompt"]
    assert writer.template_text("meeting", "en") not in provider.calls[0]["prompt"]
    assert rig.marks[-1]["stats"]["template_source"] == "workspace"


async def _async(value: Any) -> Any:
    return value


# ── P3: the note itself, the cited turns, the optional check ────────────────


def test_the_writers_sections_and_title_land_in_the_note_after_the_pad() -> None:
    from note_models import NoteContent, NoteSection

    parsed = note_markdown.parse(CASSETTE, _turns(1))
    content = NoteContent(
        template_id=uuid4(),
        template_schema_version=1,
        title="Untitled",
        sections=[
            NoteSection(section_key="user_notes", text="my own line"),
            NoteSection(section_key="gen:old-topic", text="- stale", title="Old topic"),
            NoteSection(section_key="decisions", text=""),
        ],
    )
    planned, outcome = note_apply.plan(content, parsed, title_source="default")
    assert [s.section_key for s in planned.sections] == [
        "user_notes", "gen:overview", "gen:positions-and-assessments", "decisions",
    ]  # fmt: skip
    assert planned.sections[0].text == "my own line"
    assert planned.sections[1].title == "Overview"
    # The cites stay on the items: the section carries the bullet's words only.
    assert planned.sections[1].text == "- Welchering says the 2022 deal is dead"
    assert planned.title == "Handala and the Iran deal" and outcome.title_written
    assert outcome.written_sections == ["gen:overview", "gen:positions-and-assessments"]
    assert set(outcome.section_hashes) == set(outcome.written_sections)
    # A person's title is never overwritten; a second identical plan changes nothing.
    again, kept = note_apply.plan(planned, parsed, title_source="user")
    assert again is planned and not kept.changed
    renamed, out2 = note_apply.plan(
        content.model_copy(update={"title": "Mine"}), parsed, title_source="user"
    )
    assert renamed.title == "Mine" and not out2.title_written


def test_a_table_is_one_pipe_table_in_its_section() -> None:
    md = (
        "# T\n\n## Votes\n| Item | Result | Ayes | Nays |\n|---|---|---|---|\n"
        "| 20-231 | adopted | 11 | 1 |\n| 20-486 | adopted | 12 | 0 |\n\nA closing line.\n"
    )
    parsed = note_markdown.parse(md, _turns(1))
    text = note_apply.section_text(parsed.sections[0])
    assert text.splitlines()[0] == "| Item | Result | Ayes | Nays |"
    assert text.splitlines()[1].startswith("|") and "---" in text.splitlines()[1]
    assert "| 20-486 | adopted | 12 | 0 |" in text and text.endswith("A closing line.")


def test_item_rows_carry_every_cited_turn_for_the_popover() -> None:
    turns = _turns(1)
    md = "# T\n\n## S\n- two turns [00:10, 00:40]\n- none at all\n"
    rows = generate_note.item_rows(note_markdown.parse(md, turns), turns)
    cited = rows[0]["payload"]["turns"]
    assert [f"turn:{t['turn']}" for t in cited] == rows[0]["cites"] and len(cited) == 2
    assert cited[0]["text"] and cited[0]["start_ms"] <= 10_000 <= cited[0]["end_ms"]
    assert rows[1]["payload"] is None and rows[1]["cites"] == []


def test_the_job_writes_the_note_and_skips_the_check_when_the_flag_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = _rig(monkeypatch, Scripted([CASSETTE]))
    asyncio.run(generate_note.handle_generate(rig.deps, tenant_id=TENANT, payload=rig.payload))
    assert len(rig.applied) == 1 and rig.applied[0]["parsed"].title == "Handala and the Iran deal"
    stats = rig.marks[-1]["stats"]
    assert stats["sections_written"] == 2 and stats["version_number"] == 2
    assert "check" not in stats and rig.checks == []


class _CheckingProvider(Scripted):
    """Answers the writer's call with the note, then the check call with one verdict."""

    def __init__(self, note: str, verdict: dict[str, Any]) -> None:
        super().__init__([note])
        self.verdict = verdict
        self.check_prompts: list[tuple[str, str]] = []

    async def complete(self, prompt: str, schema: Any = None, **kw: Any) -> Any:
        if schema is not None:
            self.check_prompts.append((kw.get("system", ""), prompt))
            return SimpleNamespace(
                text="", json=self.verdict, input_tokens=5, output_tokens=2,
                latency_ms=1, backend="fake", model_id="fake",
            )  # fmt: skip
        return await super().complete(prompt, schema, **kw)


def test_with_the_flag_on_the_check_marks_items_and_the_text_is_byte_identical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _CheckingProvider(CASSETTE, {"unsupported": [{"line": 2, "reason": "not said"}]})
    rig = _rig(monkeypatch, provider)
    rig.deps.check_enabled = True
    asyncio.run(generate_note.handle_generate(rig.deps, tenant_id=TENANT, payload=rig.payload))
    assert rig.marks[-1]["text"] == CASSETTE
    stats = rig.marks[-1]["stats"]
    assert stats["check"]["items"] == 2 and stats["check"]["unsupported"] == 1
    assert stats["check"]["calls"] == 1
    rows = rig.stored[-1]
    assert rig.checks == [
        {"generation_id": UUID(rig.payload["generation_id"]), "unsupported": {rows[1]["item_key"]: "not said"}}
    ]  # fmt: skip
    system, user = provider.check_prompts[0]
    assert user.startswith("Record:\n1. Welchering says") and "Transcript:" in user
    assert "never rewrite" in system
    assert [r["text"] for r in rows] == [
        "Welchering says the 2022 deal is dead",
        "Boniat: it will fail",
    ]


def test_the_checker_ignores_lines_it_cannot_place_and_a_failed_call() -> None:
    from note_service.domain import checker

    turns = _turns(1)
    rows = [
        {"position": 0, "text": "a", "cites": ["turn:0"]},
        {"position": 1, "text": "b", "cites": []},
        {"position": 2, "text": "c", "cites": ["turn:1"]},
        {"position": 3, "text": "d", "cites": ["turn:99"]},
    ]

    class _Bad:
        async def complete(self, *a: Any, **kw: Any) -> Any:
            raise RuntimeError("down")

    out = asyncio.run(checker.check(rows, turns, provider=_Bad(), language="en"))
    assert out.items == 2 and out.calls == 1 and out.failed_calls == 1 and out.unsupported == {}

    class _Odd:
        async def complete(self, *a: Any, **kw: Any) -> Any:
            return SimpleNamespace(
                json={"unsupported": [{"line": 9, "reason": "x"}, {"line": "2", "reason": "  why  "}, 3]},
                input_tokens=1, output_tokens=1,
            )  # fmt: skip

    out = asyncio.run(checker.check(rows, turns, provider=_Odd(), language="en"))
    assert out.unsupported == {2: "why"} and out.stats["unsupported"] == 1


def test_a_moment_shared_by_a_micro_turn_and_a_statement_cites_the_statement() -> None:
    turns = [
        Turn(index=0, speaker_label="A", speaker_name=None, text="The", start_ms=33_000, end_ms=33_400, line=0),
        Turn(index=1, speaker_label="B", speaker_name=None, text="confrontation we face has taken on a new quality",
             start_ms=33_000, end_ms=41_000, line=1),
    ]  # fmt: skip
    parsed = note_markdown.parse("# T\n\n## S\n- a new quality [00:33]\n", turns)
    assert parsed.items[0][1].cites == [1] and not parsed.items[0][1].cite_nearest


def test_a_long_cited_turn_is_cut_around_the_cited_moment() -> None:
    words = " ".join(f"w{i}" for i in range(2_000))  # ~10 000 chars, one ten-minute monologue
    turn = Turn(index=0, speaker_label="S", speaker_name="Anna", text=words, start_ms=0,
                end_ms=600_000, line=0)  # fmt: skip
    cut = generate_note.cited_turn(turn, [300_000])
    assert cut["excerpt"] is True and cut["at_ms"] == 300_000
    assert "w1000" in cut["text"] and "w10 " not in cut["text"] and "w1990" not in cut["text"]
    assert cut["text"].startswith("… ") and cut["text"].endswith(" …")
    assert len(cut["text"]) <= 2 * generate_note.TURN_TEXT_REACH + 8
    short = generate_note.cited_turn(Turn(index=1, speaker_label="S", speaker_name=None, text="short",
                                          start_ms=0, end_ms=1_000, line=1), [])  # fmt: skip
    assert short["text"] == "short" and "excerpt" not in short
