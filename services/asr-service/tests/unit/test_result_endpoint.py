"""Behavioural tests for ``GET /asr/jobs/{id}/result``.

Real handler, auth overridden, DB/store/NLP boundaries stubbed.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from asr_models import (
    JobStatus,
    Segment,
    TranscriptionJobView,
    TranscriptionMetadata,
    TranscriptionOutput,
    WordTiming,
)
from auth import Claims
from storage import ObjectNotFoundError

_TENANT = uuid4()


def _member_claims() -> Claims:
    return Claims(
        sub=uuid4(),
        tid=_TENANT,
        roles=["member"],
        sid="test-session",
        iss="https://test/issuer",
        aud="mdx",
        exp=9_999_999_999,
        iat=1_700_000_000,
    )


def _job_view(status: JobStatus) -> TranscriptionJobView:
    return TranscriptionJobView(
        id=uuid4(),
        tenant_id=_TENANT,
        audio_id=uuid4(),
        requester_sub=uuid4(),
        language="uk",
        model="large-v3",
        status=status,
        queued_at="2026-05-20T00:00:00Z",
    )


def _output() -> TranscriptionOutput:
    return TranscriptionOutput(
        language="uk",
        segments=[
            Segment(
                text="скарги на кашель крапка",
                start_ms=0,
                end_ms=2600,
                words=[
                    WordTiming(text="скарги", start_ms=0, end_ms=700, probability=0.97),
                    WordTiming(text="на", start_ms=700, end_ms=800, probability=0.99),
                    WordTiming(text="кашель", start_ms=800, end_ms=1500, probability=0.88),
                    WordTiming(text="крапка", start_ms=2000, end_ms=2600, probability=0.96),
                ],
                avg_confidence=0.95,
            ),
            Segment(
                text="крапка",
                start_ms=3000,
                end_ms=3500,
                words=[WordTiming(text="крапка", start_ms=3000, end_ms=3500, probability=0.97)],
                avg_confidence=0.97,
            ),
        ],
        metadata=TranscriptionMetadata(
            model="large-v3",
            vad_seconds_speech=3.5,
            infer_seconds=0.4,
            beam_size=5,
        ),
    )


class _FakeTranscriptStore:
    def __init__(self) -> None:
        self.body: bytes | None = _output().model_dump_json().encode("utf-8")
        self.calls: list[dict[str, object]] = []

    async def get(self, *, key: str, tenant_id: UUID, aad: bytes | None = None) -> bytes:
        self.calls.append({"key": key, "tenant_id": tenant_id, "aad": aad})
        if self.body is None:
            raise ObjectNotFoundError(bucket="mdx-transcripts", key=key)
        return self.body


class _FakeNlpClient:
    """Mimics the enriched batch response for the two-segment fixture."""

    def __init__(self) -> None:
        self.response: dict[str, Any] | None = {
            "pipeline_version": "nlp-v1.0.0",
            "segments": [
                {
                    "text": "Скарги на кашель.",
                    "confidence_spans": [{"start_char": 10, "end_char": 16, "level": "moderate"}],
                },
                {"text": ".", "confidence_spans": []},
            ],
        }
        self.calls: list[dict[str, Any]] = []

    async def process_segments(self, **kwargs: Any) -> dict[str, Any] | None:
        self.calls.append(kwargs)
        return self.response


class _FakeAuditWriter:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def write_event(self, **kwargs: object) -> None:
        self.events.append(kwargs)


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from asr_service import deps
    from asr_service.main import create_app
    from asr_service.routers import jobs

    store = _FakeTranscriptStore()
    audit = _FakeAuditWriter()
    nlp = _FakeNlpClient()
    fake_state = SimpleNamespace(
        app_pool=object(),
        transcript_store=store,
        audit_writer=audit,
        nlp_client=nlp,
    )
    deps.install_state(fake_state)  # type: ignore[arg-type]

    @contextlib.asynccontextmanager
    async def _fake_tenant_conn(pool, tenant_id):  # noqa: ANN001
        yield None

    monkeypatch.setattr(jobs, "tenant_connection", _fake_tenant_conn)

    async def _no_edits(conn, *, job_id, result_rev):  # noqa: ANN001
        return []

    monkeypatch.setattr(jobs.repository, "list_speaker_edits", _no_edits)

    async def _original_artifact(conn, *, job_id):  # noqa: ANN001
        return None  # never re-labelled → the original key

    monkeypatch.setattr(jobs.repository, "result_uri", _original_artifact)

    async def _job_and_uri(conn, *, job_id):  # noqa: ANN001
        # Delegates at call time to whichever get_job a test installed.
        view = await jobs.repository.get_job(conn, job_id=job_id)
        return None if view is None else (view, None)

    monkeypatch.setattr(jobs.repository, "get_job_and_result_uri", _job_and_uri)

    async def _no_candidates(conn, *, job_id):  # noqa: ANN001
        return []

    async def _first_read(conn, *, job_id):  # noqa: ANN001
        return True

    monkeypatch.setattr(jobs.repository, "name_candidates", _no_candidates)

    async def _no_sources(conn, *, job_id):  # noqa: ANN001
        return {}

    monkeypatch.setattr(jobs.repository, "name_sources", _no_sources)

    async def _sources(conn, *, job_id, names, sources):  # noqa: ANN001
        return dict(sources)

    monkeypatch.setattr(jobs.repository, "update_name_sources", _sources)
    monkeypatch.setattr(jobs.repository, "mark_result_read", _first_read)

    app = create_app()
    app.dependency_overrides[deps.current_user] = _member_claims
    return SimpleNamespace(client=TestClient(app), store=store, audit=audit, nlp=nlp)


def test_result_409_when_not_complete(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asr_service.routers import jobs

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return _job_view(JobStatus.RUNNING)

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)

    resp = rig.client.get(f"/asr/jobs/{uuid4()}/result")
    assert resp.status_code == 409
    # The shared handler renders RFC 9457 problem+json; the dict detail is
    # surfaced in the body (matching the POST validation/rate-limit siblings).
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert "urn:mdx:asr:result:not-ready" in resp.text
    assert "running" in resp.text


def test_result_409_on_a_failed_job_carries_the_failure_vocabulary(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A poller learns in one response that the transcript is not coming."""
    from asr_service.routers import jobs

    view = _job_view(JobStatus.FAILED).model_copy(update={"error_kind": "corrupt_audio"})

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return view

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)

    resp = rig.client.get(f"/asr/jobs/{uuid4()}/result")
    assert resp.status_code == 409
    body = resp.json()
    assert body["job_status"] == "failed"
    assert body["error_kind"] == "corrupt_audio"
    assert body["error_stage"] == "decode"
    assert body["error_retryable"] is False
    assert "decoded" in body["error_message"]


def test_result_404_when_missing(rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    from asr_service.routers import jobs

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return None

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)

    resp = rig.client.get(f"/asr/jobs/{uuid4()}/result")
    assert resp.status_code == 404


def test_result_200_nlp_enriched(rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    from asr_service.routers import jobs

    view = _job_view(JobStatus.COMPLETE)

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return view

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)

    job_id = uuid4()
    resp = rig.client.get(
        f"/asr/jobs/{job_id}/result", headers={"Authorization": "Bearer user-token"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == str(job_id)
    assert body["nlp_applied"] is True
    assert body["nlp_pipeline_version"] == "nlp-v1.0.0"

    # The standalone «крапка» segment (NLP → ".") merged into the previous
    # one without doubling the period; its end_ms extends the merged segment.
    assert len(body["segments"]) == 1
    seg = body["segments"][0]
    assert seg["text"] == "Скарги на кашель."
    assert seg["raw_text"] == "скарги на кашель крапка"
    assert seg["end_ms"] == 3500
    assert seg["confidence_spans"] == [{"start_char": 10, "end_char": 16, "level": "moderate"}]
    assert seg["words"][0]["text"] == "скарги"

    # The caller's bearer was forwarded verbatim to nlp-service, with
    # words converted to seconds.
    (call,) = rig.nlp.calls
    assert call["authorization"] == "Bearer user-token"
    assert call["language"] == "uk"
    assert call["segments"][0]["words"][0]["start_s"] == 0.0
    assert call["segments"][0]["words"][3]["probability"] == 0.96

    # Decrypt went through the envelope path with the job's key + AAD.
    (store_call,) = rig.store.calls
    assert store_call["key"] == f"{_TENANT}/{job_id}.json.enc"
    assert store_call["aad"] == job_id.bytes

    # Plaintext transcript reads are audited.
    (event,) = rig.audit.events
    assert event["kind"] == "asr.transcript_accessed"
    assert event["target_id"] == str(job_id)


def test_result_200_raw_fallback_when_nlp_down(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asr_service.routers import jobs

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return _job_view(JobStatus.COMPLETE)

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)
    rig.nlp.response = None  # nlp-service unreachable

    resp = rig.client.get(f"/asr/jobs/{uuid4()}/result")
    assert resp.status_code == 200
    body = resp.json()
    assert body["nlp_applied"] is False
    assert body["nlp_pipeline_version"] is None
    assert len(body["segments"]) == 2
    assert body["segments"][0]["text"] == "скарги на кашель крапка"  # raw, untouched
    assert body["segments"][0]["text"] == body["segments"][0]["raw_text"]


def test_result_410_when_ciphertext_erased(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asr_service.routers import jobs

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return _job_view(JobStatus.COMPLETE)

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)
    rig.store.body = None  # object deleted by retention TTL / erasure engine

    resp = rig.client.get(f"/asr/jobs/{uuid4()}/result")
    assert resp.status_code == 410
    assert "urn:mdx:asr:result:erased" in resp.text
    assert rig.audit.events == []  # nothing served → nothing audited


def test_result_503_when_object_store_not_configured(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty ``S3_ENDPOINT``: 503 with a code, not a 500 and not the 410; nothing audited."""
    from asr_service import deps
    from asr_service.routers import jobs
    from storage import EncryptedObjectStore, S3Client

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return _job_view(JobStatus.COMPLETE)

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)
    unconfigured = EncryptedObjectStore(
        s3=S3Client(endpoint_url="", access_key="", secret_key=""),
        bucket="mdx-transcripts",
        envelope=object(),  # type: ignore[arg-type]  — never reached: the S3 call fails first
    )
    deps.install_state(
        SimpleNamespace(  # type: ignore[arg-type]
            app_pool=object(),
            transcript_store=unconfigured,
            audit_writer=rig.audit,
            nlp_client=rig.nlp,
        )
    )

    resp = rig.client.get(f"/asr/jobs/{uuid4()}/result")
    assert resp.status_code == 503, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["code"] == "object_store_not_configured"
    assert body["type"] == "urn:mdx:storage:not-configured"
    assert "S3_ENDPOINT" in body["detail"]
    assert rig.audit.events == []


# ── Speaker structure survives enrichment (Ambient Capture) ─────────


def _diarized_output() -> TranscriptionOutput:
    base = _output()
    return base.model_copy(
        update={
            "segments": [
                base.segments[0].model_copy(update={"speaker": "SPEAKER_1"}),
                base.segments[1].model_copy(update={"speaker": "SPEAKER_1"}),
                Segment(
                    text="так",
                    start_ms=4000,
                    end_ms=4400,
                    words=[WordTiming(text="так", start_ms=4000, end_ms=4400, probability=0.9)],
                    avg_confidence=0.9,
                    speaker="SPEAKER_2",
                ),
            ],
            "speakers": ["SPEAKER_1", "SPEAKER_2"],
        }
    )


def test_result_keeps_speakers_through_nlp_enrichment(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The enriched view must keep every segment's ``speaker`` and the roster."""
    from asr_service.routers import jobs

    rig.store.body = _diarized_output().model_dump_json().encode("utf-8")
    rig.nlp.response["segments"].append({"text": "Так.", "confidence_spans": []})
    view = _job_view(JobStatus.COMPLETE).model_copy(
        update={"speaker_names": {"SPEAKER_2": "Olena"}}
    )

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return view

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)

    resp = rig.client.get(f"/asr/jobs/{uuid4()}/result", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["nlp_applied"] is True
    assert [s["speaker"] for s in body["segments"]] == ["SPEAKER_1", "SPEAKER_2"]
    assert body["speakers"] == ["SPEAKER_1", "SPEAKER_2"]
    # Display names: the person's name where given, the neutral default elsewhere.
    assert body["speaker_names"] == {"SPEAKER_1": "Speaker 1", "SPEAKER_2": "Olena"}
    # And the structure clients render.
    assert [(t["speaker"], t["name"], t["paragraphs"]) for t in body["turns"]] == [
        ("SPEAKER_1", "Speaker 1", ["Скарги на кашель."]),
        ("SPEAKER_2", "Olena", ["Так."]),
    ]
    # Artifact segment 1 (punctuation only) folded into 0: the first turn stands for both.
    assert body["turns"][0]["segment_indices"] == [0, 1]
    assert body["turns"][1]["segment_indices"] == [2]
    assert [s["artifact_indices"] for s in body["segments"]] == [[0, 1], [2]]
    assert [s["artifact_index"] for s in body["segments"]] == [0, 2]


def test_result_keeps_speakers_when_nlp_is_down(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asr_service.routers import jobs

    rig.store.body = _diarized_output().model_dump_json().encode("utf-8")
    rig.nlp.response = None

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return _job_view(JobStatus.COMPLETE)

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)

    body = rig.client.get(f"/asr/jobs/{uuid4()}/result").json()
    assert body["nlp_applied"] is False
    assert [s["speaker"] for s in body["segments"]] == ["SPEAKER_1", "SPEAKER_1", "SPEAKER_2"]
    assert body["speaker_names"] == {"SPEAKER_1": "Speaker 1", "SPEAKER_2": "Speaker 2"}
    assert [t["speaker"] for t in body["turns"]] == ["SPEAKER_1", "SPEAKER_2"]


def test_undiarized_result_is_one_unattributed_turn(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asr_service.routers import jobs

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return _job_view(JobStatus.COMPLETE)

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)

    body = rig.client.get(f"/asr/jobs/{uuid4()}/result").json()
    assert body["speakers"] == []
    assert body["speaker_names"] == {}
    assert len(body["turns"]) == 1
    assert body["turns"][0]["speaker"] is None
    assert body["turns"][0]["name"] is None


# ── PUT /asr/jobs/{id}/speakers ─────────────────────────────────────


def test_put_speakers_stores_cleaned_names_and_audits(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asr_service.routers import jobs

    stored: dict[str, object] = {}

    async def _set(conn, *, job_id, names):  # noqa: ANN001
        stored["job_id"] = job_id
        stored["names"] = names
        return names

    monkeypatch.setattr(jobs.repository, "set_speaker_names", _set)

    job_id = uuid4()
    resp = rig.client.put(
        f"/asr/jobs/{job_id}/speakers",
        json={"names": {"SPEAKER_1": "  Mark   Ivanov ", "SPEAKER_2": "   "}},
    )
    assert resp.status_code == 200, resp.text
    # Whitespace collapsed; an empty name clears the label back to default.
    assert resp.json() == {"job_id": str(job_id), "speaker_names": {"SPEAKER_1": "Mark Ivanov"}}
    assert stored == {"job_id": job_id, "names": {"SPEAKER_1": "Mark Ivanov"}}
    (event,) = [e for e in rig.audit.events if e["kind"] == "asr.speakers_named"]
    assert event["target_id"] == str(job_id)
    assert event["payload"] == {"labels": ["SPEAKER_1"]}  # labels only, never the names


def test_put_speakers_rejects_non_labels(rig: SimpleNamespace) -> None:
    resp = rig.client.put(f"/asr/jobs/{uuid4()}/speakers", json={"names": {"Mark": "Olena"}})
    assert resp.status_code == 422


def test_put_speakers_404_for_unknown_job(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asr_service.routers import jobs

    async def _set(conn, *, job_id, names):  # noqa: ANN001
        return None

    monkeypatch.setattr(jobs.repository, "set_speaker_names", _set)
    resp = rig.client.put(f"/asr/jobs/{uuid4()}/speakers", json={"names": {"SPEAKER_1": "A"}})
    assert resp.status_code == 404


def test_limits_say_what_one_upload_may_be(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The clients read this before recording, so they can warn before the
    cap rather than be refused after it."""
    from asr_service.config import settings

    monkeypatch.setattr(settings, "max_duration_seconds", 5400)
    monkeypatch.setattr(settings, "max_upload_mb", 250)
    resp = rig.client.get("/asr/limits")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"max_duration_seconds": 5400, "max_upload_mb": 250}


# ── A conversation stays verbatim ───────────────────────────────────


def _serve(rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, *, diarized: bool) -> None:
    from asr_service.routers import jobs

    if diarized:
        rig.store.body = _diarized_output().model_dump_json().encode("utf-8")
        rig.nlp.response["segments"].append({"text": "Так.", "confidence_spans": []})
    view = _job_view(JobStatus.COMPLETE)

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return view

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)


def test_a_diarized_result_skips_every_rewriting_stage(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(rig, monkeypatch, diarized=True)
    assert rig.client.get(f"/asr/jobs/{uuid4()}/result").status_code == 200
    (call,) = rig.nlp.calls
    assert call["stages_disabled"] == sorted(
        [
            "voice_commands",
            "punctuation",
            "number_norm",
            "date_norm",
            "abbreviation",
            "field_extraction",
        ]
    )


def test_a_dictation_result_keeps_its_stages(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(rig, monkeypatch, diarized=False)
    assert rig.client.get(f"/asr/jobs/{uuid4()}/result").status_code == 200
    (call,) = rig.nlp.calls
    assert call["stages_disabled"] is None


def test_relative_dates_are_anchored_on_the_recording_day(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not the reader's today: "heute" in a recording from 2026-05-20
    means 2026-05-20 on every later read."""
    from datetime import date

    for diarized in (True, False):
        rig.nlp.calls.clear()
        _serve(rig, monkeypatch, diarized=diarized)
        assert rig.client.get(f"/asr/jobs/{uuid4()}/result").status_code == 200
        (call,) = rig.nlp.calls
        assert call["reference_date"] == date(2026, 5, 20)


def test_the_batch_client_posts_stages_sorted_and_only_when_set() -> None:
    import asyncio
    from datetime import date

    import httpx

    from asr_service.integrations.nlp_client import NlpBatchClient

    sent: list[dict] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        import json

        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"segments": []})

    client = NlpBatchClient.__new__(NlpBatchClient)
    client._client = httpx.AsyncClient(  # type: ignore[attr-defined]
        base_url="http://nlp", transport=httpx.MockTransport(_handler)
    )
    asyncio.run(
        client.process_segments(
            tenant_id=uuid4(),
            segments=[],
            language="de",
            reference_date=date(2026, 9, 22),
            stages_disabled=["date_norm", "punctuation", "date_norm"],
        )
    )
    asyncio.run(client.process_segments(tenant_id=uuid4(), segments=[], language="de"))
    assert sent[0]["stages_disabled"] == ["date_norm", "punctuation"]
    assert sent[0]["reference_date"] == "2026-09-22"
    assert "stages_disabled" not in sent[1]


# ── A passage in another language is labelled, not enriched ───────────────


def test_an_other_language_segment_keeps_its_raw_text_and_labels_its_turn(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asr_models import Diagnostics, EchoSpan
    from asr_service.routers import jobs

    output = _output()
    # The second segment was decoded as Ukrainian inside an English recording.
    output = output.model_copy(
        update={
            "language": "en",
            "segments": [
                output.segments[0].model_copy(update={"text": "we looked at the flybridge"}),
                output.segments[1].model_copy(update={"text": "Що це таке?", "language": "uk"}),
            ],
            "diagnostics": Diagnostics(
                prompt_echo=[EchoSpan(start_ms=0, end_ms=900, words=3)], other_language_chunks=1
            ),
        }
    )
    rig.store.body = output.model_dump_json().encode("utf-8")
    view = _job_view(JobStatus.COMPLETE)

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return view

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)
    resp = rig.client.get(f"/asr/jobs/{uuid4()}/result", headers={"Authorization": "Bearer t"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["nlp_applied"] is True
    # The fake NLP answers its fixed rendering for the first segment and
    # "." for the second; the Ukrainian segment is served raw instead and
    # never merged into the English one.
    assert [s["text"] for s in body["segments"]] == ["Скарги на кашель.", "Що це таке?"]
    assert [s["language"] for s in body["segments"]] == [None, "uk"]
    assert [t["language"] for t in body["turns"]] == [None, "uk"]
    expected = {
        "prompt_echo": [{"start_ms": 0, "end_ms": 900, "words": 3}],
        "prompt_echo_segments_dropped": 0,
        "other_language_chunks": 1,
        # An older artifact carries no coverage.
        "coverage": None,
        "second_pass": {"chunks": 0, "recovered_words": 0, "by_cause": {}},
        # Per-segment decoder numbers stay in the artifact.
        "segments": [],
    }
    # Later fields (drops, loops, …) must hold as-is.
    assert {k: body["diagnostics"][k] for k in expected} == expected
    assert body["coverage"] is None and body["capture"] is None


# ── The view says how much the post-processor shaped it ───────────────


def test_enrichment_is_full_partial_or_raw(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asr_service.routers import jobs

    view = _job_view(JobStatus.COMPLETE)

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return view

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)
    full = rig.client.get(f"/asr/jobs/{uuid4()}/result", headers={"Authorization": "Bearer t"})
    assert full.json()["enrichment"] == "full"

    # One segment's stage failed: that segment shows its raw text, the view says partial.
    rig.nlp.response["segments"][0]["warnings"] = [
        {"code": "stage_failed", "detail": "x", "stage": "punctuation"}
    ]
    partial = rig.client.get(f"/asr/jobs/{uuid4()}/result", headers={"Authorization": "Bearer t"})
    body = partial.json()
    assert body["enrichment"] == "partial" and body["nlp_applied"] is True
    # Raw text (the fake's "." segment still merges its period into it).
    assert body["segments"][0]["text"].rstrip(".") == body["segments"][0]["raw_text"]

    rig.nlp.response = None
    raw = rig.client.get(f"/asr/jobs/{uuid4()}/result", headers={"Authorization": "Bearer t"})
    assert raw.json()["enrichment"] == "raw" and raw.json()["nlp_applied"] is False


def test_a_diarized_result_tells_nlp_it_is_a_conversation(
    rig: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from asr_service.routers import jobs

    output = _output().model_copy(update={"speakers": ["SPEAKER_1"]})
    rig.store.body = output.model_dump_json().encode("utf-8")
    view = _job_view(JobStatus.COMPLETE)

    async def _get_job(conn, *, job_id):  # noqa: ANN001
        return view

    monkeypatch.setattr(jobs.repository, "get_job", _get_job)
    rig.client.get(f"/asr/jobs/{uuid4()}/result", headers={"Authorization": "Bearer t"})
    (call,) = rig.nlp.calls
    assert call["conversation"] is True and "punctuation" in call["stages_disabled"]
