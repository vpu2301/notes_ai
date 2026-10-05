"""Sprint TQ3 T2 — the overlay in the result view and the two routes.

The repository is an in-memory stand-in (the SQL and RLS are covered by
``tests/integration/test_corrections_db.py``); what is under test here is the
route logic: plan on first read, apply accepted rows, 404 for another
tenant's job, 409 on a stale rev, reject reverting, audit without text and
the artefact's bytes unchanged.
"""

from __future__ import annotations

import contextlib
import hashlib
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from asr_models import JobStatus, Segment, TranscriptionMetadata, TranscriptionOutput, WordTiming
from asr_service.domain import corrections

from .test_result_endpoint import _TENANT, _job_view
from .test_result_endpoint import rig as result_rig  # noqa: F401 — fixture

pytestmark = pytest.mark.overlay

LINES = [
    "und dann Handala und",
    "und dann Handala und",
    "und dann Handala und",
    "und dann Handala und",
    "und dann Handela und",
    "und dann Andala und",
]


def _seg(i: int, text: str) -> Segment:
    t = i * 10_000
    words = []
    for w in text.split():
        words.append(WordTiming(text=w, start_ms=t, end_ms=t + 300, probability=0.9))
        t += 400
    return Segment(text=text, start_ms=i * 10_000, end_ms=t, words=words, avg_confidence=0.9)


def _transcript() -> TranscriptionOutput:
    return TranscriptionOutput(
        language="de",
        segments=[_seg(i, line) for i, line in enumerate(LINES)],
        metadata=TranscriptionMetadata(
            model="t", vad_seconds_speech=0, infer_seconds=0, beam_size=1
        ),
    )


class _Store:
    """``transcript_corrections`` + the two job columns, for one tenant."""

    def __init__(self, owner: UUID) -> None:
        self.owner = owner
        self.status: str | None = None
        self.rev = 0
        self.rows: list[corrections.Row] = []


@pytest.fixture
def world(result_rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:  # noqa: F811
    from asr_service.routers import corrections as routes
    from asr_service.routers import jobs

    owner = _TENANT
    store = _Store(owner)
    result_rig.store.body = _transcript().model_dump_json().encode("utf-8")
    current = {"tenant": owner}

    @contextlib.asynccontextmanager
    async def conn(pool: Any, tenant_id: UUID):  # noqa: ANN001
        current["tenant"] = tenant_id
        yield None

    monkeypatch.setattr(jobs, "tenant_connection", conn)
    monkeypatch.setattr(routes, "tenant_connection", conn)

    def mine() -> bool:
        return current["tenant"] == store.owner

    async def job_state(_c: Any, *, job_id: UUID) -> corrections.JobState | None:
        return corrections.JobState(store.status, store.rev, None) if mine() else None

    async def list_rows(_c: Any, *, job_id: UUID) -> list[corrections.Row]:
        return list(store.rows) if mine() else []

    async def glossary_terms(_c: Any) -> list[tuple[str, list[str]]]:
        return []

    async def store_plan(
        _c: Any, *, tenant_id: UUID, job_id: UUID, status: str, proposals: list
    ) -> bool:
        if store.status is not None:
            return False
        store.status, store.rev = status, store.rev + 1
        store.rows = [
            corrections.Row(
                uuid4(),
                p.from_forms,
                p.to_text,
                p.occurrences,
                p.source,
                p.confidence,
                p.status,
                None,
            )
            for p in proposals
        ]
        return True

    async def decide(
        _c: Any, *, job_id: UUID, correction_id: UUID, status: str, to_text: str | None,
        decided_by: UUID, expected_rev: int,
    ) -> tuple[corrections.Row, int] | None:  # fmt: skip
        if not mine():
            return None
        k = next((i for i, r in enumerate(store.rows) if r.id == correction_id), None)
        if k is None:
            return None
        if expected_rev != store.rev:
            raise corrections.StaleRevError
        store.rows[k] = replace(
            store.rows[k],
            status=status,
            to_text=to_text or store.rows[k].to_text,
            decided_by=decided_by,
        )
        store.rev += 1
        return store.rows[k], store.rev

    for name, fn in (
        ("job_state", job_state),
        ("list_rows", list_rows),
        ("glossary_terms", glossary_terms),
        ("store", store_plan),
        ("decide", decide),
    ):
        monkeypatch.setattr(corrections, name, fn)

    async def get_job(conn: Any, *, job_id: UUID):  # noqa: ANN001
        return _job_view(JobStatus.COMPLETE)

    monkeypatch.setattr(jobs.repository, "get_job", get_job)
    # The NLP stand-in answers for its own two-segment fixture; this one is raw.
    result_rig.nlp.response = None
    return SimpleNamespace(rig=result_rig, store=store, current=current)


def _texts(body: dict) -> list[str]:
    return [s["text"] for s in body["segments"]]


def test_the_first_read_unifies_and_every_read_applies(world: SimpleNamespace) -> None:
    before = hashlib.sha256(world.rig.store.body).hexdigest()
    body = world.rig.client.get(f"/asr/jobs/{uuid4()}/result").json()
    assert _texts(body) == ["und dann Handala und"] * 6
    (corr,) = body["entity_corrections"]
    assert (corr["to_text"], corr["status"], corr["occurrences_count"]) == (
        "Handala",
        "accepted",
        2,
    )
    assert body["corrections_rev"] == 1 and body["entity_unify"] is None
    assert hashlib.sha256(world.rig.store.body).hexdigest() == before, (
        "the artefact is never rewritten"
    )
    proposed = [
        e for e in world.rig.audit.events if e["kind"] == "asr.transcript_correction_proposed"
    ]
    assert len(proposed) == 1 and "Handala" not in str(proposed[0]["payload"])
    # A second read does not plan again.
    world.rig.client.get(f"/asr/jobs/{uuid4()}/result")
    assert (
        len(
            [e for e in world.rig.audit.events if e["kind"] == "asr.transcript_correction_proposed"]
        )
        == 1
    )


def test_reject_reverts_every_occurrence_on_the_next_read(world: SimpleNamespace) -> None:
    job = uuid4()
    body = world.rig.client.get(f"/asr/jobs/{job}/result").json()
    cid = body["entity_corrections"][0]["id"]
    resp = world.rig.client.put(
        f"/asr/jobs/{job}/corrections/{cid}", json={"status": "rejected", "corrections_rev": 1}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["corrections_rev"] == 2
    again = world.rig.client.get(f"/asr/jobs/{job}/result").json()
    assert _texts(again) == LINES
    assert again["entity_corrections"] == [], "a rejected correction is not offered again"
    event = [
        e for e in world.rig.audit.events if e["kind"] == "asr.transcript_correction_rejected"
    ][0]
    assert set(event["payload"]) == {"correction_id", "source", "occurrences", "edited"}
    assert "Handala" not in str(event["payload"]) and "Andala" not in str(event["payload"])


def test_a_stale_rev_is_a_409(world: SimpleNamespace) -> None:
    job = uuid4()
    cid = world.rig.client.get(f"/asr/jobs/{job}/result").json()["entity_corrections"][0]["id"]
    resp = world.rig.client.put(
        f"/asr/jobs/{job}/corrections/{cid}", json={"status": "rejected", "corrections_rev": 0}
    )
    assert resp.status_code == 409 and "stale_corrections_rev" in resp.text


def test_another_tenant_gets_404_on_both_routes(world: SimpleNamespace) -> None:
    job = uuid4()
    cid = world.rig.client.get(f"/asr/jobs/{job}/result").json()["entity_corrections"][0]["id"]
    world.store.owner = uuid4()  # the caller's tenant is no longer the job's
    assert world.rig.client.get(f"/asr/jobs/{job}/corrections").status_code == 404
    resp = world.rig.client.put(
        f"/asr/jobs/{job}/corrections/{cid}", json={"status": "accepted", "corrections_rev": 1}
    )
    assert resp.status_code == 404


@pytest.mark.parametrize("bad", ["<b>Handala</b>", "x" * 81, "Hand\u0007ala", "  "])
def test_an_edited_spelling_must_be_whole_words(world: SimpleNamespace, bad: str) -> None:
    job = uuid4()
    cid = world.rig.client.get(f"/asr/jobs/{job}/result").json()["entity_corrections"][0]["id"]
    resp = world.rig.client.put(
        f"/asr/jobs/{job}/corrections/{cid}",
        json={"status": "accepted", "to_text": bad, "corrections_rev": 1},
    )
    assert resp.status_code in (400, 422)


def test_the_list_route_shows_every_status(world: SimpleNamespace) -> None:
    job = uuid4()
    world.rig.client.get(f"/asr/jobs/{job}/result")
    body = world.rig.client.get(f"/asr/jobs/{job}/corrections").json()
    assert body["corrections_rev"] == 1
    assert [c["to_text"] for c in body["corrections"]] == ["Handala"]
