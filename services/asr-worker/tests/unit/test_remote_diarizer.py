"""Shape B (ADR-0052): a diarizer on another host must never cost a user their transcript;
an in-process one failing is a broken deployment and fails loudly. Whole path on fakes."""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pytest

from asr_models import JobEnqueuePayload
from asr_models.output import Segment, TranscriptionMetadata, TranscriptionOutput, WordTiming
from asr_worker import processor
from asr_worker.processor import _NonRetryableError, _RetryableError
from diarization import (
    UNKNOWN,
    DiarizationHints,
    DiarizationUnavailableError,
    OfflineDiarization,
    OfflineDiarizationConfig,
    SpeakerSegment,
    from_payload,
    to_payload,
)
from diarization.offline import _assign_display_names

TENANT = uuid4()
JOB = uuid4()
AUDIO = uuid4()


@pytest.fixture(autouse=True)
def _speech_everywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zeros that stand for speech: VAD says so, so the gates leave the text alone."""
    from asr_worker import vad as _vad

    def runs(pcm: np.ndarray, **_kw: Any) -> _vad.SpeechRuns:
        return _vad.SpeechRuns(runs=[_vad.SpeechSegment(0, max(1, int(len(pcm) / 16)))])

    monkeypatch.setattr(_vad, "speech_runs", runs)


class _Conn:
    """One job row; remembers every statement so the test can read the
    completion UPDATE back."""

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.statements: list[tuple[str, tuple[Any, ...]]] = []

    def transaction(self) -> contextlib.AbstractAsyncContextManager[None]:
        return contextlib.nullcontext()  # type: ignore[return-value]

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        self.statements.append((sql, args))
        if "SELECT status, cancel_requested" in sql:
            return {"status": self.row["status"], "cancel_requested": False}
        if "cancel_requested" in sql:
            return {"cancel_requested": False}
        return None

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.statements.append((sql, args))
        return False

    async def execute(self, sql: str, *args: Any) -> str:
        self.statements.append((sql, args))
        if "SET status='complete'" in sql:
            self.row["status"] = "complete"
            self.row["result_storage_uri"] = args[1]
            self.row["metadata"] = json.loads(args[2])
            # Mirrors the CASE in the statement under test.
            if args[4] is not None:
                self.row["diarization_status"] = "failed"
                self.row["diarization_error"] = args[4]
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
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


class _Redis:
    async def xadd(self, *args: Any, **kwargs: Any) -> str:
        return "0-0"

    async def publish(self, *args: Any, **kwargs: Any) -> int:
        return 0


class _Asr:
    is_loaded = True

    async def transcribe(self, pcm: np.ndarray, **kwargs: Any) -> TranscriptionOutput:
        return TranscriptionOutput(
            language="en",
            segments=[
                Segment(
                    text="hello there",
                    start_ms=0,
                    end_ms=1_000,
                    avg_confidence=0.9,
                    words=[WordTiming(text="hello", start_ms=0, end_ms=500, probability=0.9)],
                ),
                Segment(text="hi", start_ms=1_200, end_ms=2_000, avg_confidence=0.9),
            ],
            metadata=TranscriptionMetadata(
                model="tiny", vad_seconds_speech=2.0, infer_seconds=0.5, beam_size=5
            ),
        )


class _RemoteDiarizer:
    """The endpoint is down (or refuses this recording)."""

    engine = "http:hf_eu_diar"
    engine_version = "pyannote-community-1"
    remote = True

    def __init__(self, *, fail_on: str) -> None:
        self._fail_on = fail_on
        self.diarize_calls = 0

    async def ensure_loaded(self) -> None:
        if self._fail_on == "load":
            raise DiarizationUnavailableError("http:hf_eu_diar is unreachable: ConnectError")

    def diarize(self, pcm: np.ndarray, rate: int, *, hints: DiarizationHints) -> OfflineDiarization:
        self.diarize_calls += 1
        if self._fail_on == "call":
            raise DiarizationUnavailableError("failed after 3 attempts: ReadTimeout")
        # Through the REAL payload; an unattributed span must not become a speaker.
        segments = [
            SpeakerSegment(start_ms=0, end_ms=1_100, label="A", confidence=1.0),
            SpeakerSegment(start_ms=1_100, end_ms=1_200, label=UNKNOWN, confidence=0.0),
            SpeakerSegment(start_ms=1_200, end_ms=2_000, label="B", confidence=1.0),
        ]
        made = OfflineDiarization(
            segments=segments,
            display_names=_assign_display_names(segments),
            duration_ms=2_000,
            config=OfflineDiarizationConfig(),
            engine="pyannote-community-1",
            engine_version=self.engine_version,
            hints=hints,
        )
        return from_payload(
            to_payload(made, model_id=self.engine_version, seconds=0.2),
            hints=hints,
            config=OfflineDiarizationConfig(),
        )


class _LocalDiarizer(_RemoteDiarizer):
    engine = "pyannote-community-1"
    remote = False


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Any:
    row: dict[str, Any] = {
        "status": "queued",
        "diarization_status": None,
        "diarization_error": None,
    }
    conn = _Conn(row)

    @contextlib.asynccontextmanager
    async def tenant_connection(_pool: object, tenant: UUID) -> AsyncIterator[_Conn]:
        assert tenant == TENANT
        yield conn

    async def decode(_bytes: bytes, **_kw: Any) -> np.ndarray:
        return np.zeros(16_000 * 2, dtype=np.float32)

    monkeypatch.setattr(processor, "tenant_connection", tenant_connection)
    monkeypatch.setattr(processor, "decode_to_pcm", decode)

    def build(diarizer: Any) -> Any:
        return type(
            "S",
            (),
            {
                "app_pool": object(),
                "audio_store": _Store("mdx-audio", {f"{TENANT}/{AUDIO}.enc": b"audio"}),
                "transcript_store": _Store("mdx-transcripts"),
                "audit_writer": _Audit(),
                "engine": _Asr(),
                "diarizer": diarizer,
                "shadow_diarizer": None,
                # A fake Redis keeps the fire-and-forget notification out of the way.
                "redis": _Redis(),
            },
        )()

    return type("W", (), {"row": row, "conn": conn, "build": staticmethod(build)})()


def _payload() -> JobEnqueuePayload:
    return JobEnqueuePayload(
        job_id=JOB,
        tenant_id=TENANT,
        audio_id=AUDIO,
        language="en",
        diarize=True,
        requester_sub=uuid4(),
    )


@pytest.mark.parametrize("fail_on", ["load", "call"])
async def test_a_dead_endpoint_still_delivers_the_transcript(world: Any, fail_on: str) -> None:
    state = world.build(_RemoteDiarizer(fail_on=fail_on))

    await processor._process_one(state, _message())

    assert world.row["status"] == "complete", "the words were transcribed; they are not lost"
    assert world.row["diarization_status"] == "failed"
    assert world.row["diarization_error"] in ("diarization_unavailable", "diarization_failed")
    stored = json.loads(next(iter(state.transcript_store.objects.values())))
    assert [s.get("speaker") for s in stored["segments"]] == [None, None]
    assert stored["metadata"]["diarization"] is None, "no stats for a run that never happened"


@pytest.mark.parametrize("fail_on", ["load", "call"])
async def test_the_same_outage_in_process_fails_the_job(world: Any, fail_on: str) -> None:
    """An in-process engine that cannot load or crashes fails the job loudly."""
    state = world.build(_LocalDiarizer(fail_on=fail_on))

    with pytest.raises((_RetryableError, _NonRetryableError)):
        await processor._process_one(state, _message())

    assert world.row["status"] != "complete"


async def test_a_working_endpoint_labels_the_transcript_as_usual(world: Any) -> None:
    diarizer = _RemoteDiarizer(fail_on="")
    state = world.build(diarizer)

    await processor._process_one(state, _message())

    assert diarizer.diarize_calls == 1
    assert world.row["status"] == "complete"
    assert world.row["diarization_status"] is None, "nothing failed, nothing to re-run"
    stored = json.loads(next(iter(state.transcript_store.objects.values())))
    assert stored["segments"][0]["speaker"] == "SPEAKER_1"
    assert stored["metadata"]["diarization"]["engine"] == "pyannote-community-1", (
        "the transcript names the engine that produced the labels, not the "
        "transport — otherwise moving the same engine onto an endpoint would "
        "make every existing transcript look out of date and offer a re-label"
    )
    assert stored["speakers"] == ["SPEAKER_1", "SPEAKER_2"], (
        "unattributed evidence is not a speaker, remote or not"
    )


def _message() -> Any:
    return type("M", (), {"value": _payload().model_dump_json().encode()})()


async def test_a_dead_endpoint_is_not_retried_through_the_mono_fallback(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mono fallback is for channel-analysis bugs, not for a dead endpoint."""
    diarizer = _RemoteDiarizer(fail_on="call")
    state = world.build(diarizer)
    stereo = np.zeros((16_000 * 2, 2), dtype=np.int16)

    async def decode(_bytes: bytes, layout: str) -> Any:
        return stereo, np.zeros(16_000 * 2, dtype=np.float32)

    monkeypatch.setattr(processor, "_decode_capture", decode)

    await processor._process_one(state, _message())

    assert diarizer.diarize_calls <= 1, "the mono path re-sent the audio to a dead endpoint"
    assert world.row["status"] == "complete"
    assert world.row["diarization_status"] == "failed"
