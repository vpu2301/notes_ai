"""0057 — a meeting note names itself, and never over a person's title.

The generation job's title step against an in-memory note row. The row
mirrors the one SQL rule that matters (`append_version`): a title change
that does not say where it came from is a person renaming the note.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from note_models import NoteContent, NoteSection, NoteStatus
from note_service.domain import note_title
from note_service.jobs import generate_note

TENANT = UUID("22222222-2222-2222-2222-222222222222")
NOTE_ID = UUID("33333333-3333-3333-3333-333333333333")
AUTHOR = UUID("11111111-1111-1111-1111-111111111111")
PLACEHOLDER = "Meeting notes — 2026-09-22"

ROADMAP = (
    "Okay so let's start. Today we need to agree on the fourth quarter product roadmap. "
    "The biggest item is the HubSpot integration, customers keep asking for it. "
    "Engineering thinks the integration needs six weeks, so the mobile redesign moves "
    "to January. Pricing changes for the enterprise plan also land this quarter."
)


def _result(text: str, language: str = "en") -> dict:
    return {"language": language, "segments": [{"speaker": "S1", "text": text}]}


class _Store:
    """One note: its row and its versions."""

    def __init__(self, *, source: str | None = note_title.DEFAULT) -> None:
        self.title = PLACEHOLDER
        self.source = source
        self.generated_at: datetime | None = None
        self.versions = [self._content(PLACEHOLDER)]
        self.appends: list[dict] = []

    @staticmethod
    def _content(title: str) -> NoteContent:
        return NoteContent(
            template_id=uuid4(),
            template_schema_version=1,
            title=title,
            sections=[NoteSection(section_key="discussion", text="")],
        )

    def row(self) -> SimpleNamespace:
        return SimpleNamespace(
            status=NoteStatus.DRAFT,
            current_version_id=len(self.versions),
            current_version_number=len(self.versions),
            title=self.title,
        )

    def append(self, content: NoteContent, title_source: str | None) -> None:
        # The CASE in `notes_repository.append_version`.
        if title_source is not None:
            self.source = title_source
            if title_source == note_title.AI:
                self.generated_at = datetime.now(UTC)
        elif content.title != self.title:
            self.source = note_title.USER
        self.title = content.title
        self.versions.append(content)

    def rename(self, title: str) -> None:
        """A person renaming the note from any client (PUT /draft)."""
        self.append(self.versions[-1].model_copy(update={"title": title}), None)


class _Provider:
    def __init__(
        self,
        answer: str = '{"title": "Q4 Product Roadmap"}',
        *,
        fail: bool = False,
        before_answer=None,
    ) -> None:  # noqa: ANN001
        self.answer = answer
        self.fail = fail
        self.before_answer = before_answer
        self.calls: list[dict] = []

    async def complete(self, prompt, schema=None, *, max_tokens, temperature=0.0, system=None):  # noqa: ANN001, ANN201
        self.calls.append({"prompt": prompt, "system": system})
        if self.before_answer:
            self.before_answer()
        await asyncio.sleep(0)
        if self.fail:
            raise ConnectionError("connection refused")
        return SimpleNamespace(text=self.answer)


@pytest.fixture
def store(monkeypatch) -> _Store:  # noqa: ANN001
    store = _Store()

    async def _fetchval(query, *args):  # noqa: ANN001, ANN002, ANN202
        assert "title_source" in query
        return store.source

    conn = SimpleNamespace(fetchval=_fetchval)

    @contextlib.asynccontextmanager
    async def _tenant_conn(pool, tenant_id):  # noqa: ANN001, ANN202
        yield conn

    async def _lock(conn, *, note_id):  # noqa: ANN001, ANN202
        return store.row()

    async def _fetch_version(conn, *, version_id):  # noqa: ANN001, ANN202
        return SimpleNamespace(content=store.versions[version_id - 1])

    async def _append(conn, **kwargs):  # noqa: ANN001, ANN003, ANN202
        assert kwargs["expected_version"] == len(store.versions)
        store.appends.append(kwargs)
        store.append(kwargs["new_content"], kwargs.get("title_source"))
        return uuid4(), len(store.versions)

    monkeypatch.setattr(generate_note, "tenant_connection", _tenant_conn)
    monkeypatch.setattr(note_title.repo, "lock_note_for_update", _lock)
    monkeypatch.setattr(note_title.repo, "fetch_version", _fetch_version)
    monkeypatch.setattr(note_title.repo, "append_version", _append)
    return store


async def _name(provider: _Provider, result: dict, language: str = "en") -> None:
    deps = generate_note.GenerationDeps(
        app_pool=object(), transcripts_store=object(), provider_for=None
    )
    await generate_note._name_note(
        deps,
        TENANT,
        note_id=NOTE_ID,
        generation_id=uuid4(),
        requested_by=AUTHOR,
        result=result,
        provider=provider,
        language=language,
    )


# ── The job step ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_a_meaningful_transcript_names_the_note(store: _Store) -> None:
    provider = _Provider()
    await _name(provider, _result(ROADMAP))

    assert store.title == "Q4 Product Roadmap"
    assert store.source == note_title.AI
    assert store.generated_at is not None
    # The name is on the row every list reads AND in the version the
    # editor loads, so a reload on any device shows the same title.
    assert store.versions[-1].title == "Q4 Product Roadmap"
    (append,) = store.appends
    assert append["extra_metadata"]["step"] == "title"
    # Only the title moved; the sections are the ones that were there.
    assert store.versions[-1].sections == store.versions[0].sections


@pytest.mark.anyio
async def test_no_meaningful_speech_keeps_the_placeholder(store: _Store) -> None:
    provider = _Provider()
    await _name(provider, _result("Hello? Can you hear me? Testing, one two three. Okay."))

    assert provider.calls == []  # not even asked
    assert store.title == PLACEHOLDER
    assert store.source == note_title.DEFAULT


@pytest.mark.anyio
async def test_the_model_saying_there_is_no_topic_keeps_the_placeholder(store: _Store) -> None:
    await _name(_Provider('{"title": ""}'), _result(ROADMAP))
    assert store.title == PLACEHOLDER
    assert store.source == note_title.DEFAULT


@pytest.mark.anyio
async def test_a_short_recording_is_named_from_what_there_is(store: _Store) -> None:
    short = "We should move the Pincer telephony platform to the new SIP provider before March."
    # Words the recording says: a title naming what was never said is not
    # written (Q6), so "Migration" over "move" would keep the placeholder.
    provider = _Provider('{"title": "Pincer Telephony Platform Move"}')
    await _name(provider, _result(short))
    assert len(provider.calls) == 1
    assert store.title == "Pincer Telephony Platform Move"


@pytest.mark.anyio
async def test_a_rename_while_the_model_answers_wins(store: _Store) -> None:
    provider = _Provider(before_answer=lambda: store.rename("Roadmap with Anna"))
    await _name(provider, _result(ROADMAP))

    assert len(provider.calls) == 1
    assert store.title == "Roadmap with Anna"
    assert store.source == note_title.USER
    assert all(a.get("title_source") is None for a in store.appends)


@pytest.mark.anyio
async def test_a_rename_after_the_ai_title_is_never_undone(store: _Store) -> None:
    await _name(_Provider(), _result(ROADMAP))
    store.rename("My own title")
    assert store.source == note_title.USER

    later = _Provider('{"title": "Something Else"}')
    await _name(later, _result(ROADMAP))  # a regenerate, a retried job
    assert later.calls == []
    assert store.title == "My own title"


@pytest.mark.anyio
async def test_a_title_the_author_typed_at_start_is_left_alone(store: _Store) -> None:
    store.source = note_title.USER
    provider = _Provider()
    await _name(provider, _result(ROADMAP))
    assert provider.calls == []
    assert store.title == PLACEHOLDER


@pytest.mark.anyio
async def test_notes_older_than_the_feature_are_never_renamed(store: _Store) -> None:
    store.source = None  # a row from before migration 0057
    provider = _Provider()
    await _name(provider, _result(ROADMAP))
    assert provider.calls == []
    assert store.title == PLACEHOLDER


@pytest.mark.anyio
async def test_duplicate_runs_write_the_title_once(store: _Store) -> None:
    """The same job delivered twice, at the same time: both may ask the
    model, only one writes."""
    first = _Provider('{"title": "Q4 Product Roadmap"}')
    second = _Provider('{"title": "Fourth Quarter Roadmap"}')
    await asyncio.gather(_name(first, _result(ROADMAP)), _name(second, _result(ROADMAP)))

    assert len(store.appends) == 1
    assert store.source == note_title.AI
    # And a third, later delivery does not even ask.
    third = _Provider()
    await _name(third, _result(ROADMAP))
    assert third.calls == []
    assert len(store.appends) == 1


@pytest.mark.anyio
async def test_a_failing_model_costs_nothing(store: _Store) -> None:
    await _name(_Provider(fail=True), _result(ROADMAP))  # does not raise
    assert store.title == PLACEHOLDER
    assert store.source == note_title.DEFAULT
    assert store.appends == []


@pytest.mark.anyio
async def test_a_broken_database_costs_nothing(store: _Store, monkeypatch) -> None:  # noqa: ANN001
    async def _boom(conn, **kwargs):  # noqa: ANN001, ANN003, ANN202
        raise RuntimeError("pool closed")

    monkeypatch.setattr(note_title.repo, "append_version", _boom)
    await _name(_Provider(), _result(ROADMAP))  # does not raise
    assert store.title == PLACEHOLDER


@pytest.mark.anyio
async def test_the_title_is_asked_for_in_the_spoken_language(store: _Store) -> None:
    german = (
        "Wir müssen heute die Planung der neuen Telefonie-Plattform abschließen. Der "
        "Anbieter liefert die Schnittstelle im März, danach testen wir mit zwei Kunden."
    )
    provider = _Provider('{"title": "Planung der neuen Telefonie-Plattform"}')
    await _name(provider, _result(german, "de"), language="de")

    (call,) = provider.calls
    assert "German" in call["system"]
    assert store.title == "Planung der neuen Telefonie-Plattform"


# ── The pure parts ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('"Q4 Sales Performance Review"', "Q4 Sales Performance Review"),
        ("Title: Weekly Engineering Sync.", "Weekly Engineering Sync"),
        ("«План запуску нового продукту»", "План запуску нового продукту"),
        ("NONE", ""),
        ("  ", ""),
        ("...", ""),
        (" ".join(f"w{i}" for i in range(15)), " ".join(f"w{i}" for i in range(10))),
    ],
)
def test_clean(raw: str, expected: str) -> None:
    assert note_title.clean(raw) == expected


def test_a_prose_answer_is_still_read() -> None:
    assert note_title._answer_text(SimpleNamespace(text="HubSpot Customer Workflow")) == (
        "HubSpot Customer Workflow"
    )
    assert note_title._answer_text(json.dumps({"title": "X Y"})) == "X Y"


def test_a_long_meeting_is_sampled_across_its_whole_length() -> None:
    words = [f"w{i}" for i in range(10_000)]
    text = note_title.sample(_result(" ".join(words)), budget=900)
    kept = text.replace("…", "").split()
    assert len(kept) == 900
    assert "w0" in kept  # the start
    assert "w5000" in kept or any(4500 < int(w[1:]) < 5500 for w in kept)  # the middle
    assert "w9999" in kept  # the end


def test_filler_does_not_count_as_content() -> None:
    assert note_title.meaningful_word_count(_result("Hi, hello, can you hear me? Yeah. Okay.")) == 0
    assert note_title.meaningful_word_count(_result(ROADMAP)) >= note_title.MIN_MEANINGFUL_WORDS


# ── Summary Engine v2 guards (Q6): same rules as the document's lines ──


@pytest.mark.anyio
async def test_a_title_copied_from_a_prompt_example_is_not_written(store: _Store) -> None:
    await _name(_Provider('{"title": "Lantern edition won\'t be ready"}'), _result(ROADMAP))
    assert store.title == PLACEHOLDER
    assert store.source == note_title.DEFAULT


@pytest.mark.anyio
async def test_a_title_naming_what_was_never_said_is_not_written(store: _Store) -> None:
    await _name(_Provider('{"title": "Berlin Roadmap Review"}'), _result(ROADMAP))
    assert store.title == PLACEHOLDER
    assert store.source == note_title.DEFAULT


@pytest.mark.anyio
async def test_a_good_title_still_lands_as_ai(store: _Store) -> None:
    await _name(_Provider('{"title": "HubSpot Integration Roadmap"}'), _result(ROADMAP))
    assert store.title == "HubSpot Integration Roadmap"
    assert store.source == note_title.AI


@pytest.mark.parametrize(
    ("title", "reason"),
    [
        ("Q4 Product Roadmap", None),
        # A title-cased topic word is not a name when the transcript says its stem.
        ("Enterprise Pricing Changes", None),
        ("HubSpot Integration", None),
        ("Walzmann Interview", "unsupported"),  # first word checked too
        ("Lantern edition won't be ready", "example"),
    ],
)
def test_unsupported(title: str, reason: str | None) -> None:
    assert note_title.unsupported(title, _result(ROADMAP)) == reason
