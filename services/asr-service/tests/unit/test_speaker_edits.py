"""Speaker edit overlay: pure folding + merge/undo routes.

Routes run against an in-memory repository that scopes rows by tenant the
way RLS does, so cross-tenant calls see nothing.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from asr_models import (
    EnrichedSegment,
    JobStatus,
    Segment,
    TranscriptionJobView,
    TranscriptionMetadata,
    TranscriptionOutput,
    WordTiming,
)
from asr_service.domain.speaker_edits import (
    SpeakerEdit,
    apply_edits,
    apply_to_roster,
    speaker_stats,
)
from auth import Claims

_TENANT_A = uuid4()
_TENANT_B = uuid4()


def _edit(seq: int, frm: str, to: str) -> SpeakerEdit:
    return SpeakerEdit(uuid4(), "merge", frm, to, [], 1, seq, datetime.now(UTC))


def _seg(speaker: str | None, start: int, end: int) -> EnrichedSegment:
    return EnrichedSegment(
        text="x", raw_text="x", start_ms=start, end_ms=end, avg_confidence=0.9, speaker=speaker
    )


# ── Pure fold ─────────────────────────────────────────────────────────


def test_merge_chains_resolve_to_the_final_target() -> None:
    segs = [_seg("SPEAKER_1", 0, 1), _seg("SPEAKER_2", 1, 2), _seg("SPEAKER_3", 2, 3)]
    edits = [_edit(1, "SPEAKER_3", "SPEAKER_2"), _edit(2, "SPEAKER_2", "SPEAKER_1")]

    out = apply_edits(segs, edits)

    assert [s.speaker for s in out] == ["SPEAKER_1"] * 3
    assert apply_to_roster(["SPEAKER_1", "SPEAKER_2", "SPEAKER_3"], edits) == ["SPEAKER_1"]
    assert [s.speaker for s in segs] == ["SPEAKER_1", "SPEAKER_2", "SPEAKER_3"]  # untouched


def test_speaker_stats_use_word_spans_and_count_turns() -> None:
    worded = _seg("SPEAKER_1", 0, 5000).model_copy(
        update={"words": [WordTiming(text="a", start_ms=0, end_ms=1000, probability=0.9)]}
    )
    segs = [
        worded,
        _seg("SPEAKER_2", 5000, 8000),
        _seg(None, 8000, 9000),
        _seg("SPEAKER_1", 9000, 10000),
    ]

    stats = speaker_stats(segs, ["SPEAKER_1", "SPEAKER_2"])

    assert [(s.label, s.speech_ms, s.turns) for s in stats] == [
        ("SPEAKER_1", 2000, 2),
        ("SPEAKER_2", 3000, 1),
    ]
    assert stats[0].share == 0.4


# ── Routes ────────────────────────────────────────────────────────────


def _output() -> TranscriptionOutput:
    def s(speaker: str, start: int, end: int, text: str) -> Segment:
        return Segment(text=text, start_ms=start, end_ms=end, avg_confidence=0.9, speaker=speaker)

    return TranscriptionOutput(
        language="en",
        segments=[
            s("SPEAKER_1", 0, 4000, "Hello there."),
            s("SPEAKER_2", 4000, 8000, "Hi."),
            s("SPEAKER_3", 8000, 9000, "Yes."),
            s("SPEAKER_1", 9000, 12000, "Good."),
        ],
        metadata=TranscriptionMetadata(
            model="tiny", vad_seconds_speech=12.0, infer_seconds=1.0, beam_size=5
        ),
        speakers=["SPEAKER_1", "SPEAKER_2", "SPEAKER_3"],
    )


class _Repo:
    """In-memory stand-in for the repository; ``conn`` is the tenant id."""

    def __init__(self) -> None:
        self.jobs: dict[tuple[UUID, UUID], dict[str, Any]] = {}
        self.edits: list[dict[str, Any]] = []

    def add_job(self, tenant: UUID, status: JobStatus = JobStatus.COMPLETE) -> UUID:
        job_id = uuid4()
        self.jobs[(tenant, job_id)] = {
            "id": job_id,
            "tenant_id": tenant,
            "status": status.value,
            "diarization_rev": 1,
            "speaker_names": {},
        }
        return job_id

    async def get_job(self, conn: UUID, *, job_id: UUID) -> TranscriptionJobView | None:
        row = self.jobs.get((conn, job_id))
        if row is None:
            return None
        return TranscriptionJobView(
            id=job_id,
            tenant_id=conn,
            audio_id=uuid4(),
            requester_sub=uuid4(),
            language="en",
            model="tiny",
            status=JobStatus(row["status"]),
            queued_at=datetime.now(UTC),
            speaker_names=row["speaker_names"],
        )

    async def result_uri(self, conn: UUID, *, job_id: UUID) -> str | None:
        return None  # never re-labelled → the original key

    async def all_edit_labels(self, conn: UUID, *, job_id: UUID) -> list[str]:
        return [
            label
            for e in self._mine(conn, job_id)
            for label in (e["edit"].from_label, e["edit"].to_label)
            if label
        ]

    async def name_sources(self, conn: UUID, *, job_id: UUID) -> dict[str, str]:
        row = self.jobs.get((conn, job_id)) or {}
        return dict(row.get("speaker_name_sources", {}))

    async def update_name_sources(
        self, conn: UUID, *, job_id: UUID, names: dict[str, str], sources: dict[str, str]
    ) -> dict[str, str]:
        from asr_service.domain.repository import merge_name_sources

        row = self.jobs[(conn, job_id)]
        row["speaker_name_sources"] = merge_name_sources(
            dict(row.get("speaker_name_sources", {})), names=names, sources=sources
        )
        return row["speaker_name_sources"]

    async def name_candidates(self, conn: UUID, *, job_id: UUID) -> list[str]:
        return []

    async def mark_result_read(self, conn: UUID, *, job_id: UUID) -> bool:
        return True

    async def has_corrections(self, conn: UUID, *, job_id: UUID) -> bool:
        return bool(self._mine(conn, job_id))

    async def get_job_and_result_uri(self, conn: UUID, *, job_id: UUID) -> Any:
        view = await self.get_job(conn, job_id=job_id)
        return None if view is None else (view, None)

    async def lock_job_for_edit(self, conn: UUID, *, job_id: UUID) -> dict[str, Any] | None:
        return self.jobs.get((conn, job_id))

    def _mine(self, conn: UUID, job_id: UUID) -> list[dict[str, Any]]:
        return [
            e for e in self.edits if e["tenant"] == conn and e["edit"].id and e["job"] == job_id
        ]

    async def list_speaker_edits(
        self, conn: UUID, *, job_id: UUID, result_rev: int
    ) -> list[SpeakerEdit]:
        return [
            e["edit"]
            for e in self._mine(conn, job_id)
            if not e["reverted"] and e["edit"].result_rev == result_rev
        ]

    async def insert_speaker_edit(self, conn: UUID, **kw: Any) -> SpeakerEdit:
        seq = len(self._mine(conn, kw["job_id"])) + 1
        edit = SpeakerEdit(
            uuid4(),
            kw["kind"],
            kw["from_label"],
            kw["to_label"],
            list(kw.get("segment_indices") or []),
            kw["result_rev"],
            seq,
            datetime.now(UTC),
            creates_label=bool(kw.get("creates_label")),
        )
        self.edits.append(
            {"tenant": kw["tenant_id"], "job": kw["job_id"], "edit": edit, "reverted": False}
        )
        return edit

    async def get_speaker_edit(self, conn: UUID, *, job_id: UUID, edit_id: UUID) -> Any:
        for e in self._mine(conn, job_id):
            if e["edit"].id == edit_id:
                return e["edit"], e["reverted"]
        return None

    async def revert_live_edits(self, conn: UUID, *, job_id: UUID, result_rev: int) -> int:
        live = [e for e in self._mine(conn, job_id) if not e["reverted"]]
        for e in live:
            e["reverted"] = True
        return len(live)

    async def revert_speaker_edit(self, conn: UUID, *, edit_id: UUID) -> None:
        for e in self.edits:
            if e["edit"].id == edit_id:
                e["reverted"] = True

    async def set_speaker_names(
        self, conn: UUID, *, job_id: UUID, names: dict[str, str]
    ) -> dict[str, str] | None:
        row = self.jobs.get((conn, job_id))
        if row is None:
            return None
        row["speaker_names"] = dict(names)
        return row["speaker_names"]


class _Store:
    def __init__(self) -> None:
        self.body = _output().model_dump_json().encode()

    async def get(self, *, key: str, tenant_id: UUID, aad: bytes | None = None) -> bytes:
        return self.body


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    monkeypatch.setenv("NLP_ENRICH_ENABLED", "false")

    from asr_service import deps
    from asr_service.main import create_app
    from asr_service.routers import jobs

    repo = _Repo()
    store = _Store()
    audit = _Audit()
    deps.install_state(
        SimpleNamespace(
            app_pool=object(), transcript_store=store, audit_writer=audit, nlp_client=None
        )  # type: ignore[arg-type]
    )

    @contextlib.asynccontextmanager
    async def _tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield tenant_id

    monkeypatch.setattr(jobs, "tenant_connection", _tenant_conn)
    monkeypatch.setattr(jobs.settings, "nlp_enrich_enabled", False, raising=False)
    for name in (
        "get_job",
        "result_uri",
        "get_job_and_result_uri",
        "name_candidates",
        "mark_result_read",
        "has_corrections",
        "revert_live_edits",
        "all_edit_labels",
        "name_sources",
        "update_name_sources",
        "lock_job_for_edit",
        "list_speaker_edits",
        "insert_speaker_edit",
        "get_speaker_edit",
        "revert_speaker_edit",
        "set_speaker_names",
    ):
        monkeypatch.setattr(jobs.repository, name, getattr(repo, name))

    current = {"tid": _TENANT_A}

    def _claims() -> Claims:
        return Claims(
            sub=uuid4(),
            tid=current["tid"],
            roles=["member"],
            sid="s",
            iss="https://t",
            aud="mdx",
            exp=9_999_999_999,
            iat=1_700_000_000,
        )

    app = create_app()
    app.dependency_overrides[deps.current_user] = _claims
    return SimpleNamespace(
        client=TestClient(app), repo=repo, store=store, audit=audit, current=current
    )


def _merge(
    rig: SimpleNamespace, job_id: UUID, frm: str = "SPEAKER_3", into: str = "SPEAKER_1"
) -> Any:
    return rig.client.post(f"/asr/jobs/{job_id}/speakers/merge", json={"from": frm, "into": into})


def test_merge_then_result_agree_everywhere(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)
    before = rig.store.body

    resp = _merge(rig, job)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["speakers"] == ["SPEAKER_1", "SPEAKER_2"]
    assert [s["label"] for s in body["speaker_stats"]] == ["SPEAKER_1", "SPEAKER_2"]
    result = rig.client.get(f"/asr/jobs/{job}/result").json()
    assert result["speakers"] == ["SPEAKER_1", "SPEAKER_2"]
    assert "SPEAKER_3" not in {t["speaker"] for t in result["turns"]}
    assert "SPEAKER_3" not in {s["label"] for s in result["speaker_stats"]}
    # SPEAKER_3's "Yes." now sits between two SPEAKER_1 segments → one turn.
    assert [t["speaker"] for t in result["turns"]] == ["SPEAKER_1", "SPEAKER_2", "SPEAKER_1"]
    assert result["edits"][0]["from_label"] == "SPEAKER_3"
    assert result["result_rev"] == 1
    assert rig.store.body == before  # the artifact is never rewritten
    merged = [e for e in rig.audit.events if e["kind"] == "asr.speakers_merged"]
    assert [e["payload"] for e in merged] == [
        {"from_label": "SPEAKER_3", "into_label": "SPEAKER_1"}
    ]


def test_merge_copies_a_custom_name_to_an_unnamed_target_and_undo_takes_it_back(
    rig: SimpleNamespace,
) -> None:
    job = rig.repo.add_job(_TENANT_A)
    rig.repo.jobs[(_TENANT_A, job)]["speaker_names"] = {"SPEAKER_3": "Anna"}

    body = _merge(rig, job).json()
    assert body["speaker_names"]["SPEAKER_1"] == "Anna"

    assert rig.client.delete(f"/asr/jobs/{job}/speakers/edits/{body['edit_id']}").status_code == 204
    assert rig.repo.jobs[(_TENANT_A, job)]["speaker_names"] == {"SPEAKER_3": "Anna"}
    # No name ever reaches the audit trail.
    assert "Anna" not in repr(rig.audit.events)


@pytest.mark.parametrize(
    ("frm", "into", "code"),
    [("SPEAKER_9", "SPEAKER_1", "unknown_label"), ("SPEAKER_1", "SPEAKER_1", "same_label")],
)
def test_merge_rejects_bad_labels(rig: SimpleNamespace, frm: str, into: str, code: str) -> None:
    job = rig.repo.add_job(_TENANT_A)
    resp = _merge(rig, job, frm, into)
    assert resp.status_code == 422
    assert resp.json()["code"] == code
    assert rig.repo.edits == []


def test_merge_on_a_running_job_is_409(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A, JobStatus.RUNNING)
    resp = _merge(rig, job)
    assert resp.status_code == 409
    assert resp.json()["code"] == "job_not_complete"


def test_repeated_merge_is_idempotent(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)
    first = _merge(rig, job).json()
    second = _merge(rig, job)
    assert second.status_code == 200
    assert second.json()["edit_id"] == first["edit_id"]
    assert len(rig.repo.edits) == 1


def test_undo_restores_and_only_the_latest_edit_can_be_undone(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)
    first = _merge(rig, job, "SPEAKER_3", "SPEAKER_2").json()["edit_id"]
    second = _merge(rig, job, "SPEAKER_2", "SPEAKER_1").json()["edit_id"]

    older = rig.client.delete(f"/asr/jobs/{job}/speakers/edits/{first}")
    assert older.status_code == 409
    assert older.json()["code"] == "edit_not_latest"

    assert rig.client.delete(f"/asr/jobs/{job}/speakers/edits/{second}").status_code == 204
    assert rig.client.delete(f"/asr/jobs/{job}/speakers/edits/{first}").status_code == 204
    result = rig.client.get(f"/asr/jobs/{job}/result").json()
    assert result["speakers"] == ["SPEAKER_1", "SPEAKER_2", "SPEAKER_3"]
    assert result["edits"] == []
    reverted = [e for e in rig.audit.events if e["kind"] == "asr.speaker_edit_reverted"]
    assert [e["payload"] for e in reverted] == [{"kind": "merge"}, {"kind": "merge"}]


def test_other_tenant_gets_404_and_writes_nothing(rig: SimpleNamespace) -> None:
    job = rig.repo.add_job(_TENANT_A)
    edit_id = _merge(rig, job).json()["edit_id"]

    rig.current["tid"] = _TENANT_B
    assert _merge(rig, job, "SPEAKER_2", "SPEAKER_1").status_code == 404
    assert rig.client.delete(f"/asr/jobs/{job}/speakers/edits/{edit_id}").status_code == 404
    assert len(rig.repo.edits) == 1
    assert rig.repo.edits[0]["reverted"] is False
