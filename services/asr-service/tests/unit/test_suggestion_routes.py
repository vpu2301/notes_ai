# ruff: noqa: F811 — the imported `rig` fixture is injected by name.
"""Name suggestion routes (result, dismiss, accept) and the re-label offer."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from asr_models import Segment, TranscriptionMetadata, TranscriptionOutput

from .test_speaker_edits import _TENANT_A, _TENANT_B, rig  # noqa: F401


def _intro_output(*, engine: str | None = "legacy-ecapa-ahc") -> TranscriptionOutput:
    from asr_models import DiarizationStats

    def s(speaker: str, start: int, end: int, text: str) -> Segment:
        return Segment(text=text, start_ms=start, end_ms=end, avg_confidence=0.9, speaker=speaker)

    stats = (
        DiarizationStats(
            engine=engine,
            engine_version="x",
            chunks=4,
            clusters_raw=2,
            clusters_after_merge=2,
            clusters_dropped=0,
            speakers=2,
            speech_seconds=10,
            unknown_share=0.0,
            seconds=1.0,
        )
        if engine
        else None
    )
    return TranscriptionOutput(
        language="en",
        segments=[
            s("SPEAKER_1", 0, 4000, "Okay, let's start."),
            s("SPEAKER_2", 14000, 16200, "Hi, this is Anna from Acme."),
            s("SPEAKER_1", 16300, 17000, "Welcome."),
        ],
        metadata=TranscriptionMetadata(
            model="tiny", vad_seconds_speech=10, infer_seconds=1, beam_size=5, diarization=stats
        ),
        speakers=["SPEAKER_1", "SPEAKER_2"],
    )


class _Redis:
    def __init__(self, *, fails: bool = False) -> None:
        self.data: dict[str, bytes] = {}
        self.fails = fails

    async def get(self, key: str) -> bytes | None:
        if self.fails:
            raise ConnectionError("redis down")
        return self.data.get(key)

    async def set(self, key: str, value: bytes, ex: int, nx: bool = False) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True


class _Audio:
    def __init__(self, exists: bool) -> None:
        self.present = exists
        self.calls = 0

    async def exists(self, *, key: str) -> bool:
        self.calls += 1
        return self.present


@pytest.fixture
def world(rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    from asr_service import deps
    from asr_service.routers import jobs

    rig.store.body = _intro_output().model_dump_json().encode()
    state = deps.get_state()
    state.redis = _Redis()
    state.audio_store = _Audio(exists=True)
    monkeypatch.setattr(jobs.settings, "name_suggestions_enabled", True)

    candidates: dict[UUID, list[str]] = {}
    dismissed: dict[UUID, list[tuple[str, str]]] = {}
    audio: dict[UUID, str] = {}

    async def name_candidates(conn: UUID, *, job_id: UUID) -> list[str]:
        return candidates.get(job_id, [])

    async def dismissed_suggestions(
        conn: UUID, *, job_id: UUID, result_rev: int | None = None
    ) -> list[tuple[str, str]]:
        return dismissed.get(job_id, [])

    async def dismiss_suggestion(conn: UUID, *, job_id: UUID, label: str, name: str) -> bool | None:
        if (conn, job_id) not in rig.repo.jobs:
            return None
        pairs = dismissed.setdefault(job_id, [])
        if (label, name) in pairs:
            return False
        pairs.append((label, name))
        return True

    async def audio_state(conn: UUID, *, job_id: UUID) -> Any:
        from asr_service.domain.repository import AudioState

        if (conn, job_id) not in rig.repo.jobs:
            return None
        row = rig.repo.jobs[(conn, job_id)]
        return AudioState(
            audio_id=job_id,
            audio_status=audio.get(job_id, "transcribed"),
            diarization_runs=int(row.get("diarization_runs", 0)),
            diarization_status=row.get("diarization_status"),
        )

    for name, fn in {
        "name_candidates": name_candidates,
        "dismissed_suggestions": dismissed_suggestions,
        "dismiss_suggestion": dismiss_suggestion,
        "audio_state": audio_state,
    }.items():
        monkeypatch.setattr(jobs.repository, name, fn)
    return SimpleNamespace(
        rig=rig, state=state, candidates=candidates, audio=audio, jobs=jobs, monkeypatch=monkeypatch
    )


def _result(w: SimpleNamespace, job: UUID) -> dict[str, Any]:
    return w.rig.client.get(f"/asr/jobs/{job}/result").json()


def test_a_self_introduction_matching_an_invitee_is_offered(world: SimpleNamespace) -> None:
    job = world.rig.repo.add_job(_TENANT_A)
    world.candidates[job] = ["Anna Keller", "Tom Berg"]

    [s] = _result(world, job)["name_suggestions"]

    assert (s["label"], s["name"], s["source"]) == ("SPEAKER_2", "Anna Keller", "self_introduction")
    assert s["quote"] == "Hi, this is Anna from Acme."
    assert (s["start_ms"], s["segment_indices"]) == (14000, [1])


def test_no_invitees_no_suggestions_and_off_means_absent(world: SimpleNamespace) -> None:
    job = world.rig.repo.add_job(_TENANT_A)

    assert _result(world, job)["name_suggestions"] == []
    world.monkeypatch.setattr(world.jobs.settings, "name_suggestions_enabled", False)
    world.candidates[job] = ["Anna Keller"]
    assert _result(world, job)["name_suggestions"] is None


def test_a_dismissed_suggestion_never_returns_and_dismiss_is_idempotent(
    world: SimpleNamespace,
) -> None:
    job = world.rig.repo.add_job(_TENANT_A)
    world.candidates[job] = ["Anna Keller"]
    body = {"label": "SPEAKER_2", "name": "Anna Keller"}

    first = world.rig.client.post(f"/asr/jobs/{job}/speakers/suggestions/dismiss", json=body)
    again = world.rig.client.post(f"/asr/jobs/{job}/speakers/suggestions/dismiss", json=body)

    assert (first.status_code, again.status_code) == (204, 204)
    assert _result(world, job)["name_suggestions"] == []
    dismissals = [e for e in world.rig.audit.events if e["kind"] == "asr.name_suggestion_dismissed"]
    assert [e["payload"] for e in dismissals] == [{"label": "SPEAKER_2"}]


def test_accepting_stores_the_source_and_audits_without_the_name(world: SimpleNamespace) -> None:
    job = world.rig.repo.add_job(_TENANT_A)
    world.candidates[job] = ["Anna Keller"]

    resp = world.rig.client.put(
        f"/asr/jobs/{job}/speakers",
        json={"names": {"SPEAKER_2": "Anna Keller"}, "sources": {"SPEAKER_2": "suggestion"}},
    )

    assert resp.status_code == 200
    result = _result(world, job)
    assert result["speaker_names"]["SPEAKER_2"] == "Anna Keller"
    assert result["speaker_name_sources"]["SPEAKER_2"] == "suggestion"
    assert result["name_suggestions"] == [], "a named speaker gets no suggestion"
    accepted = [e for e in world.rig.audit.events if e["kind"] == "asr.name_suggestion_accepted"]
    assert [e["payload"] for e in accepted] == [{"label": "SPEAKER_2"}]
    assert "Anna" not in json.dumps([e["payload"] for e in world.rig.audit.events])


def test_another_tenant_cannot_dismiss(world: SimpleNamespace) -> None:
    job = world.rig.repo.add_job(_TENANT_A)
    world.rig.current["tid"] = _TENANT_B

    resp = world.rig.client.post(
        f"/asr/jobs/{job}/speakers/suggestions/dismiss", json={"label": "SPEAKER_2", "name": "X"}
    )

    assert resp.status_code == 404


# ── Re-label offer ────────────────────────────────────────────────────


def test_an_older_engine_with_audio_is_offered_a_relabel_and_the_check_is_cached(
    world: SimpleNamespace,
) -> None:
    world.monkeypatch.setattr(world.jobs.settings, "current_diar_engine", "pyannote-community-1")
    job = world.rig.repo.add_job(_TENANT_A)

    assert _result(world, job)["relabel_available"] is True
    assert _result(world, job)["relabel_available"] is True
    assert world.state.audio_store.calls == 1, "second read served from the 10-min cache"
    assert any(k.endswith(f":asr:audio_exists:{job}") for k in world.state.redis.data)


@pytest.mark.parametrize(
    "case",
    ["current_engine", "audio_gone", "audio_row_deleted", "redis_down", "runs_spent", "running"],
)
def test_no_relabel_offer_when_it_cannot_or_need_not_run(world: SimpleNamespace, case: str) -> None:
    world.monkeypatch.setattr(world.jobs.settings, "current_diar_engine", "pyannote-community-1")
    job = world.rig.repo.add_job(_TENANT_A)
    if case == "current_engine":
        world.rig.store.body = (
            _intro_output(engine="pyannote-community-1").model_dump_json().encode()
        )
    elif case == "audio_gone":
        world.state.audio_store.present = False
    elif case == "audio_row_deleted":
        world.audio[job] = "deleted"
    elif case == "runs_spent":
        world.rig.repo.jobs[(_TENANT_A, job)]["diarization_runs"] = 5
    elif case == "running":
        world.rig.repo.jobs[(_TENANT_A, job)]["diarization_status"] = "queued"
    else:
        world.state.redis.fails = True

    assert _result(world, job)["relabel_available"] is False


def test_a_pre_sprint_28_diarized_transcript_is_offered_a_relabel(world: SimpleNamespace) -> None:
    world.rig.store.body = _intro_output(engine=None).model_dump_json().encode()
    job = world.rig.repo.add_job(_TENANT_A)

    assert _result(world, job)["relabel_available"] is True


def test_offered_is_counted_once_per_suggestion_not_per_page_load(world: SimpleNamespace) -> None:
    job = world.rig.repo.add_job(_TENANT_A)
    world.candidates[job] = ["Anna Keller"]

    for _ in range(3):
        _result(world, job)
    world.rig.client.get(f"/asr/jobs/{job}/result", headers={"X-MDX-Read-Purpose": "note_build"})

    offered_keys = [k for k in world.state.redis.data if ":suggestion_offered:" in k]
    assert len(offered_keys) == 1
