"""Telemetry sprint 2: one job through the real worker path (``_process_one_measured`` →
``_process_one`` → ``decode_recording``) with stubbed models and a recording store, so every
stage's span, its required keys, the run status and the timing rules are checked end to end."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pytest

import telemetry
from asr_models import JobEnqueuePayload
from asr_models.output import Segment, TranscriptionMetadata, TranscriptionOutput, WordTiming
from asr_worker import processor, shadow
from asr_worker import vad as _vad
from asr_worker.chunks import LanguageGuess
from diarization import (
    UNKNOWN,
    DiarizationHints,
    DiarizationUnavailableError,
    OfflineDiarization,
    OfflineDiarizationConfig,
    SpeakerSegment,
)
from diarization.offline import _assign_display_names
from messaging import Message
from models import TranscriptionCancelledError
from telemetry import runs as t_runs
from telemetry import store as t_store
from telemetry.schema import STAGE_KEYS, ProcessingRun, RunContext, SpanRecord

TENANT = uuid4()
AUDIO_SECONDS = 60.0
SR = 16_000


# ── a store that keeps what would be written ──
class _Recorder(t_store.NullStore):
    def __init__(self) -> None:
        super().__init__()
        self.spans: list[SpanRecord] = []
        self.runs: dict[UUID, ProcessingRun] = {}
        self.finished: dict[UUID, dict[str, Any]] = {}
        self.attempts: dict[UUID, int] = {}

    def span(self, record: SpanRecord) -> None:
        self.spans.append(record)

    async def insert_run(self, run: ProcessingRun) -> None:
        self.runs[run.processing_run_id] = run

    async def begin(
        self, tenant_id: UUID, run_id: UUID, activity: Any, ctx: RunContext | None
    ) -> int:
        if run_id in self.finished:
            return 0  # the run is closed: a redelivery after it finished
        self.attempts[run_id] = self.attempts.get(run_id, 0) + 1
        return self.attempts[run_id]

    async def run_facts(self, tenant_id: UUID, run_id: UUID) -> Any:
        ends = [s.end_wall_utc for s in self.spans if s.end_wall_utc and s.status != "started"]
        return self.runs[run_id].submitted_at, AUDIO_SECONDS, ends

    async def update_run(
        self,
        tenant_id: UUID,
        run_id: UUID,
        fields: dict[str, Any],
        reasons: dict[str, str],
        cleared: list[str],
    ) -> None:
        self.finished[run_id] = fields

    def final(self) -> list[SpanRecord]:
        return [s for s in self.spans if s.status != "started"]

    def by_stage(self, stage: str) -> list[SpanRecord]:
        return [s for s in self.final() if s.stage == stage]


@pytest.fixture
def recorder() -> Iterator[_Recorder]:
    rec = _Recorder()
    t_runs._settings = t_runs.Settings(enabled=True)
    t_store.configure(rec)
    yield rec
    t_store.configure(None)


# ── fakes for the worker's world ──
class _Conn:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        if "SELECT status, cancel_requested" in sql:
            return {"status": self.row["status"], "cancel_requested": False}
        if "SELECT status, attempts, diarization_status" in sql:
            return {k: self.row[k] for k in ("status", "attempts", "diarization_status")}
        if "cancel_requested" in sql:
            return {"cancel_requested": False}
        return None

    async def fetchval(self, sql: str, *args: Any) -> Any:
        return False

    async def execute(self, sql: str, *args: Any) -> str:
        if "SET status='running'" in sql:
            self.row["status"], self.row["attempts"] = "running", self.row["attempts"] + 1
        elif "SET status='complete'" in sql:
            self.row["status"] = "complete"
            if args[4] is not None:
                self.row["diarization_status"] = "failed"
        elif "status = 'cancelled'" in sql or "status='cancelled'" in sql:
            self.row["status"] = "cancelled"
        return "UPDATE 1"


class _Store:
    def __init__(self, bucket: str, objects: dict[str, bytes] | None = None) -> None:
        self.bucket = bucket
        self.objects = objects or {}

    async def get(self, *, key: str, tenant_id: UUID, aad: bytes) -> bytes:
        return self.objects[key]

    async def put(self, *, key: str, plaintext: bytes, tenant_id: UUID, aad: bytes) -> None:
        self.objects[key] = plaintext


class _Audit:
    async def write_event(self, **kwargs: Any) -> None:
        return None


class _Redis:
    async def xadd(self, *a: Any, **k: Any) -> str:
        return "0-0"

    async def publish(self, *a: Any, **k: Any) -> int:
        return 0


def _seg(start_ms: int, end_ms: int, text: str = "we agreed on the budget") -> Segment:
    words = text.split()
    step = (end_ms - start_ms) // max(1, len(words))
    return Segment(
        text=text,
        start_ms=start_ms,
        end_ms=end_ms,
        avg_confidence=0.9,
        words=[
            WordTiming(
                text=w,
                start_ms=start_ms + i * step,
                end_ms=start_ms + (i + 1) * step,
                probability=0.9,
            )
            for i, w in enumerate(words)
        ],
    )


class _Engine:
    """The in-process engine's surface the LID planner uses."""

    def detect_language(self, pcm: np.ndarray, **_k: Any) -> LanguageGuess:
        return LanguageGuess("en", 0.97, {"en": 0.97, "de": 0.02})

    def _detect_chunk_language(self, pcm: np.ndarray) -> LanguageGuess:
        return self.detect_language(pcm)


class _Provider:
    """An in-process provider: transcribes all but the last run (so coverage re-decodes it)."""

    is_loaded = True
    model_name = "large-v3"
    warmup_seconds = 4.2

    def __init__(self, *, cancel: bool = False) -> None:
        self.engine = _Engine()
        self._cancel = cancel

    async def transcribe_runs(self, pcm: np.ndarray, runs: Any, **_k: Any) -> TranscriptionOutput:
        if self._cancel:
            raise TranscriptionCancelledError
        await asyncio.sleep(0.05)
        segs = [_seg(r.start_ms, r.end_ms) for r in list(runs)[:-1]]
        return TranscriptionOutput(
            language="en",
            segments=segs,
            metadata=TranscriptionMetadata(
                model="large-v3", vad_seconds_speech=1.0, infer_seconds=0.05, beam_size=5
            ),
        )

    async def transcribe(self, pcm: np.ndarray, **kwargs: Any) -> TranscriptionOutput:
        assert kwargs.get("second_pass")
        return TranscriptionOutput(
            language="en",
            segments=[_seg(0, int(len(pcm) / 16), "and the delivery date is friday next week")],
            metadata=TranscriptionMetadata(
                model="large-v3", vad_seconds_speech=1.0, infer_seconds=0.01, beam_size=5
            ),
        )


class _Diarizer:
    engine = "legacy-ecapa-ahc"
    engine_version = "ecapa-1"
    remote = False

    def __init__(self, *, fail: bool = False, remote: bool = False, delay: float = 0.0) -> None:
        self.loaded = False
        self._fail, self.remote, self._delay = fail, remote, delay

    async def ensure_loaded(self) -> None:
        await asyncio.sleep(0.01)
        self.loaded = True

    def diarize(self, pcm: np.ndarray, rate: int, *, hints: DiarizationHints) -> OfflineDiarization:
        time.sleep(self._delay)
        if self._fail:
            raise DiarizationUnavailableError("down")
        n = int(len(pcm) / 16)
        segments = [
            SpeakerSegment(start_ms=0, end_ms=n // 2, label="A", confidence=1.0),
            SpeakerSegment(start_ms=n // 2, end_ms=n // 2 + 1000, label=UNKNOWN, confidence=0.0),
            SpeakerSegment(start_ms=n // 2 + 1000, end_ms=n, label="B", confidence=1.0),
        ]
        return OfflineDiarization(
            segments=segments,
            display_names=_assign_display_names(segments),
            duration_ms=n,
            config=OfflineDiarizationConfig(),
            engine="legacy-ecapa-ahc",
            engine_version="ecapa-1",
            hints=hints,
        )


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Any:
    row: dict[str, Any] = {"status": "queued", "attempts": 0, "diarization_status": None}
    conn = _Conn(row)

    @contextlib.asynccontextmanager
    async def tenant_connection(_pool: object, tenant: UUID) -> AsyncIterator[_Conn]:
        yield conn

    async def decode(_bytes: bytes, **_k: Any) -> np.ndarray:
        return np.zeros(int(SR * AUDIO_SECONDS), dtype=np.float32)

    def speech_runs(pcm: np.ndarray, **_k: Any) -> _vad.SpeechRuns:
        # Three 20 s runs of "speech"; the provider leaves the last one empty.
        return _vad.SpeechRuns(
            runs=[_vad.SpeechSegment(i * 20_000, (i + 1) * 20_000) for i in range(3)]
        )

    monkeypatch.setattr(processor, "tenant_connection", tenant_connection)
    monkeypatch.setattr(processor, "decode_to_pcm", decode)
    monkeypatch.setattr(_vad, "speech_runs", speech_runs)
    monkeypatch.setattr(_vad, "_model", object())  # warm unless a test makes it cold
    monkeypatch.setattr(processor.settings, "asr_segment_lid_enabled", False)
    monkeypatch.setattr(processor.settings, "asr_second_pass_enabled", True)
    monkeypatch.setattr(processor.settings, "asr_vad_pad_ms", 0)

    def build(provider: Any = None, diarizer: Any = None, shadow_asr: Any = None) -> Any:
        audio = uuid4()
        return type("S", (), {
            "app_pool": object(),
            "audio_store": _Store("mdx-audio", {f"{TENANT}/{audio}.enc": b"audio-bytes"}),
            "transcript_store": _Store("mdx-transcripts"),
            "audit_writer": _Audit(),
            "engine": provider or _Provider(),
            "diarizer": diarizer or _Diarizer(),
            "shadow_diarizer": None,
            "shadow_asr": shadow_asr,
            "channel_segmenter": None,
            "redis": _Redis(),
            "audio_id": audio,
        })()  # fmt: skip

    return type("W", (), {"row": row, "build": staticmethod(build)})()


async def _run(state: Any, *, diarize: bool = True) -> tuple[telemetry.RunRef, JobEnqueuePayload]:
    job = uuid4()
    run = await telemetry.start_run(
        tenant_id=TENANT, recording_id=job, audio_duration_seconds=AUDIO_SECONDS
    )
    assert run is not None
    payload = JobEnqueuePayload(
        job_id=job, tenant_id=TENANT, audio_id=state.audio_id, language="auto", diarize=diarize,
        requester_sub=uuid4(), queue_depth_at_enqueue=3, **telemetry.inject(run),
    )  # fmt: skip
    msg = Message(
        topic="asr:jobs", key=None, value=payload.model_dump_json().encode(), headers={},
        timestamp_ms=int((datetime.now(UTC) - timedelta(milliseconds=120)).timestamp() * 1000),
    )  # fmt: skip
    await processor._process_one_measured(state, msg)
    return run, payload


EXPECTED = {
    "queue", "model_init", "audio_prep", "vad", "language_detection", "asr_primary",
    "asr_recovery", "diarization_load", "diarization_infer", "postprocess_align",
    "postprocess_attribute", "postprocess_cleanup", "persist", "other",
}  # fmt: skip


async def test_a_job_produces_a_span_for_every_worker_stage(
    recorder: _Recorder, world: Any
) -> None:
    run, _ = await _run(world.build())
    stages = {s.stage for s in recorder.final()}
    assert stages >= EXPECTED, EXPECTED - stages
    for s in recorder.final():
        for key in STAGE_KEYS.get(s.stage, ()):
            assert key in s.attributes, (s.stage, s.name, key)
            if s.attributes[key] is None:
                assert key in s.attributes.get("_reasons", {}), (s.stage, key)
    # Every span hangs under the job's root span (or is the root).
    root = next(s for s in recorder.final() if s.name == "worker_job")
    ids = {s.span_id for s in recorder.final()}
    assert all(s.parent_span_id in ids for s in recorder.final() if s is not root)
    assert recorder.finished[run.processing_run_id]["status"] == "succeeded"
    queue = recorder.by_stage("queue")[0]
    assert queue.attributes["queue_depth_at_enqueue"] == 3 and queue.clock_source == "wall"
    assert queue.attributes["queue_wait_seconds"] >= 0.1


async def test_chunks_and_language_calls_are_their_own_spans(
    recorder: _Recorder, world: Any
) -> None:
    await _run(world.build())
    primary = [s for s in recorder.by_stage("asr_primary") if s.name == "asr.transcribe_runs"]
    assert len(primary) == 1 and primary[0].attributes["chunk_count"] == 3
    assert primary[0].attributes["audio_processed_seconds"] == pytest.approx(60.0)
    lid = recorder.by_stage("language_detection")
    assert lid and all(s.attributes["call_count"] == 1 for s in lid)
    assert lid[0].attributes["detected"][0] == {"lang": "en", "confidence": 0.97}


async def test_recovery_has_a_trigger_and_audio_fed_exceeds_the_recording(
    recorder: _Recorder, world: Any
) -> None:
    run, _ = await _run(world.build())
    (rec,) = recorder.by_stage("asr_recovery")
    assert rec.attributes["trigger_reason"] == "decoder_empty"
    assert rec.attributes["recovered_words"] > 0
    fields = recorder.finished[run.processing_run_id]
    assert fields["asr_audio_processed_seconds"] > AUDIO_SECONDS  # primary 60 s + recovery 20 s


async def test_cold_then_warm_model_init(
    recorder: _Recorder, world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow_load() -> None:
        time.sleep(0.2)
        _vad._model = object()

    monkeypatch.setattr(_vad, "_model", None)
    monkeypatch.setattr(_vad, "_ensure_loaded", slow_load)
    await _run(world.build())
    world.row.update(status="queued", attempts=0)
    await _run(world.build())
    vad_inits = [s for s in recorder.by_stage("model_init") if s.name == "vad.model"]
    assert [s.attributes["state"] for s in vad_inits] == ["cold", "warm"]
    assert vad_inits[0].attributes["load_seconds"] >= 0.2
    # The cold load is not inside ASR's wall time.
    first_primary = next(
        s for s in recorder.by_stage("asr_primary") if s.name == "asr.transcribe_runs"
    )
    assert first_primary.attributes["wall_seconds"] < 0.2


async def test_shadow_asr_overlaps_diarization_and_wall_is_not_the_sum(
    recorder: _Recorder, world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run_shadow(*_a: Any, **_k: Any) -> None:
        await asyncio.sleep(0.3)

    async def bounded(task: Any) -> None:
        return await task

    monkeypatch.setattr(shadow, "sampled", lambda: True)
    monkeypatch.setattr(shadow, "run", run_shadow)
    monkeypatch.setattr(shadow, "bounded", bounded)
    run, _ = await _run(world.build(diarizer=_Diarizer(delay=0.3), shadow_asr=object()))
    (diar,) = recorder.by_stage("diarization_infer")
    shadow_span = next(s for s in recorder.final() if s.name == "asr.shadow")
    assert diar.is_parallel_with == [shadow_span.span_id]
    assert (
        diar.start_wall_utc < shadow_span.end_wall_utc
        and shadow_span.start_wall_utc < diar.end_wall_utc
    )
    total = sum(
        (s.end_monotonic_ns - s.start_monotonic_ns) / 1e9
        for s in recorder.final()
        if s.end_monotonic_ns
    )
    assert recorder.finished[run.processing_run_id]["processing_wall_seconds"] < total


async def test_a_remote_diarizer_failure_leaves_a_partial_run(
    recorder: _Recorder, world: Any
) -> None:
    run, _ = await _run(world.build(diarizer=_Diarizer(fail=True, remote=True)))
    (diar,) = recorder.by_stage("diarization_infer")
    assert diar.status == "error" and diar.error_category == "diarization"
    assert world.row["status"] == "complete"  # the transcript was persisted
    fields = recorder.finished[run.processing_run_id]
    assert (fields["status"], fields["error_category"]) == ("partial", "diarization")


async def test_cancellation_mid_asr_closes_the_spans_cancelled(
    recorder: _Recorder, world: Any
) -> None:
    run, _ = await _run(world.build(provider=_Provider(cancel=True)))
    primary = next(s for s in recorder.by_stage("asr_primary") if s.name == "asr.transcribe_runs")
    assert primary.status == "cancelled"
    root = next(s for s in recorder.final() if s.name == "worker_job")
    assert root.status == "cancelled"
    assert recorder.finished[run.processing_run_id]["status"] == "cancelled"


async def test_diarization_off_is_a_skipped_span(recorder: _Recorder, world: Any) -> None:
    await _run(world.build(), diarize=False)
    (diar,) = recorder.by_stage("diarization_infer")
    assert diar.status == "skipped" and diar.attributes["skip_reason"] == "not_requested"


async def test_a_retry_reuses_the_run_and_counts_the_attempt(
    recorder: _Recorder, world: Any
) -> None:
    from models import ErrorKind, ProviderError

    class _FlakyOnce(_Provider):
        calls = 0

        async def transcribe_runs(
            self, pcm: np.ndarray, runs: Any, **k: Any
        ) -> TranscriptionOutput:
            _FlakyOnce.calls += 1
            if _FlakyOnce.calls == 1:
                raise ProviderError(ErrorKind.UNAVAILABLE, "backend restarting", backend="inproc")
            return await super().transcribe_runs(pcm, runs, **k)

    state = world.build(provider=_FlakyOnce())
    with pytest.raises(processor._RetryableError):
        await _run(state)
    (run_id,) = recorder.runs
    assert run_id not in recorder.finished  # a retry follows: the run stays open
    payload_msg = next(iter(recorder.runs.values()))
    payload = JobEnqueuePayload(
        job_id=payload_msg.recording_id, tenant_id=TENANT, audio_id=state.audio_id, language="auto",
        diarize=True, requester_sub=uuid4(), processing_run_id=run_id,
    )  # fmt: skip
    msg = Message(
        topic="asr:jobs",
        key=None,
        value=payload.model_dump_json().encode(),
        headers={},
        timestamp_ms=0,
    )
    await processor._process_one_measured(state, msg)
    roots = [s for s in recorder.final() if s.name == "worker_job"]
    assert [(r.attempt, r.status) for r in roots] == [(1, "error"), (2, "ok")]
    assert recorder.attempts[run_id] == 2
    assert recorder.finished[run_id]["status"] == "succeeded"
    assert {s.processing_run_id for s in recorder.final()} == {run_id}


async def test_a_redelivery_after_the_run_finished_is_a_skipped_span(
    recorder: _Recorder, world: Any
) -> None:
    # A job longer than the reclaim idle time is handed out again while/after it runs (no heartbeat).
    state = world.build()
    run, payload = await _run(state)
    finished = dict(recorder.finished[run.processing_run_id])
    msg = Message(
        topic="asr:jobs",
        key=None,
        value=payload.model_dump_json().encode(),
        headers={},
        timestamp_ms=0,
    )
    await processor._process_one_measured(state, msg)
    roots = [s for s in recorder.final() if s.name == "worker_job"]
    assert [r.status for r in roots] == ["ok", "skipped"]
    assert roots[1].attributes["redelivered_after_finish"] is True
    assert recorder.finished[run.processing_run_id] == finished  # the run was not reopened
    assert recorder.by_stage("queue")[-1].attributes["redelivery"] is True


def test_a_rediarize_message_belongs_to_a_reprocess_run() -> None:
    # Sprint 5 (S2): a re-labelling is measured too, as a `reprocess` run of the recording.
    run_id = uuid4()
    payload = JobEnqueuePayload(
        job_id=uuid4(), tenant_id=uuid4(), audio_id=uuid4(), language="auto", diarize=True,
        task="rediarize", target_rev=2, rediarize_id=run_id, requester_sub=uuid4(),
        processing_run_id=run_id,
    )  # fmt: skip
    msg = Message(topic="asr:jobs", key=None, value=payload.model_dump_json().encode(),
                  headers={}, timestamp_ms=0)  # fmt: skip
    run, _ = processor._telemetry_run(msg)
    assert run is not None and run.kind == "reprocess" and run.processing_run_id == run_id


def test_a_failed_jobs_error_kind_picks_the_telemetry_category() -> None:
    # Sprint 5 (S6): a corrupt upload is an input failure, not an ASR one.
    assert processor._error_category("corrupt_audio") == "input"
    assert processor._error_category("no_speech") == "input"
    assert processor._error_category("storage_unavailable") == "storage"
    assert processor._error_category("diarization_failed") == "diarization"
    assert processor._error_category(None) == "unknown"
