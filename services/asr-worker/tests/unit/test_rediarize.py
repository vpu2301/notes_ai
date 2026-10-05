"""The ``rediarize`` task (Sprint 29 B-5): new speaker labels, no ASR pass.

The database is a single in-memory job row behind a fake connection that
understands the handful of statements the task issues; stores are dicts.
What is held here:

* the transcript is re-labelled from the stored words — the ASR engine is
  never touched — and lands under a new ``.r{rev}`` key;
* duplicate delivery is a no-op, a redelivery after a crash finishes with
  one revision bump;
* a failure fails the RE-RUN, never the job or its current labels;
* names follow a speaker only on a clear, one-to-one majority.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pytest

from asr_models import JobEnqueuePayload, JobErrorKind
from asr_models.output import Segment, TranscriptionMetadata, TranscriptionOutput, WordTiming
from asr_worker import processor
from asr_worker.processor import (
    _NonRetryableError,
    _RetryableError,
    carry_over_mapping,
    revision_key,
)
from diarization import (
    DiarizationHints,
    OfflineDiarization,
    OfflineDiarizationConfig,
    SpeakerSegment,
)
from storage import ObjectNotFoundError

TENANT = uuid4()
JOB = uuid4()
AUDIO = uuid4()
BUCKET = "mdx-transcripts"
ORIGINAL_KEY = f"{TENANT}/{JOB}.json.enc"
REQUEST = uuid4()


# ── Fakes ─────────────────────────────────────────────────────────────


class _Conn:
    def __init__(self, row: dict[str, Any], fail_swap: list[bool]) -> None:
        self.row = row
        self._fail_swap = fail_swap

    def transaction(self) -> contextlib.AbstractAsyncContextManager[None]:
        return contextlib.nullcontext()  # type: ignore[return-value]

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        r = self.row
        if "SET diarization_status='running'" in sql:
            if (
                r["status"] == "complete"
                and r["diarization_status"] in ("queued", "running")
                and r["diarization_rev"] == args[1]
                and r["diarization_request_id"] == args[2]
            ):
                r["diarization_status"] = "running"
                return {
                    "result_storage_uri": r["result_storage_uri"],
                    "capture_context": r.get("capture_context", "{}"),
                }
            return None
        if "FOR UPDATE" in sql:
            return dict(r)
        if "SET diarization_status='failed'" in sql:
            if (
                r["diarization_status"] in ("queued", "running")
                and r["diarization_request_id"] == args[2]
            ):
                r["diarization_status"] = "failed"
                r["diarization_error"] = args[1]
                return {"id": JOB}
            return None
        raise AssertionError(f"unexpected fetchrow: {sql}")

    async def execute(self, sql: str, *args: Any) -> str:
        r = self.row
        if "SET previous_result_storage_uri = result_storage_uri" in sql:
            if self._fail_swap and self._fail_swap.pop(0):
                raise ConnectionError("db went away")
            r["previous_result_storage_uri"] = r["result_storage_uri"]
            r["previous_speaker_names"] = r["speaker_names"]
            r["result_storage_uri"] = args[1]
            r["diarization_rev"] = args[2]
            r["diarization_status"] = "complete"
            r["diarization_error"] = None
            r["metadata"] = json.loads(args[3])
            r["speaker_names"] = json.loads(args[4])
            r["speaker_name_sources"] = json.loads(args[5])
            return "UPDATE 1"
        raise AssertionError(f"unexpected execute: {sql}")


class _Store:
    def __init__(self, bucket: str) -> None:
        self.bucket = bucket
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.deleted: list[str] = []

    async def get(self, *, key: str, tenant_id: UUID, aad: bytes) -> bytes:
        if key not in self.objects:
            raise ObjectNotFoundError(bucket=self.bucket, key=key)
        return self.objects[key]

    async def put(self, *, key: str, plaintext: bytes, tenant_id: UUID, aad: bytes) -> None:
        self.objects[key] = plaintext
        self.puts.append(key)

    async def delete(self, *, key: str) -> None:
        self.objects.pop(key, None)
        self.deleted.append(key)


class _Audit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def write_event(self, **kw: Any) -> None:
        self.events.append((kw["kind"], kw["payload"]))


class _NoAsr:
    """The Whisper engine. A re-run that touches it has failed its one job."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"rediarize touched the ASR engine ({name})")


class _Diarizer:
    engine = "fake"
    engine_version = "1"

    def __init__(self, timeline: list[tuple[int, int, str]]) -> None:
        self.timeline = timeline
        self.hints: list[DiarizationHints] = []

    @property
    def ready(self) -> bool:
        return True

    @property
    def last_error(self) -> str | None:
        return None

    async def ensure_loaded(self) -> None:
        return None

    def diarize(self, pcm: np.ndarray, rate: int, *, hints: DiarizationHints) -> OfflineDiarization:
        self.hints.append(hints)
        segments = [SpeakerSegment(a, b, label, 1.0) for a, b, label in self.timeline]
        names: dict[str, str] = {}
        for s in segments:
            names.setdefault(s.label, f"SPEAKER_{len(names) + 1}")
        return OfflineDiarization(
            segments=segments,
            display_names=names,
            duration_ms=self.timeline[-1][1],
            config=OfflineDiarizationConfig(),
            engine=self.engine,
            engine_version=self.engine_version,
            hints=hints,
        )


def _words(start_s: int, end_s: int) -> list[WordTiming]:
    return [
        WordTiming(text=f"w{t}", start_ms=t * 1000, end_ms=t * 1000 + 900, probability=0.9)
        for t in range(start_s, end_s)
    ]


def _transcript() -> TranscriptionOutput:
    """Two labelled speakers over 0–10 s and 10–20 s."""

    def seg(speaker: str, a: int, b: int) -> Segment:
        words = _words(a, b)
        return Segment(
            text=" ".join(w.text for w in words),
            start_ms=a * 1000,
            end_ms=b * 1000,
            words=words,
            avg_confidence=0.9,
            speaker=speaker,
        )

    return TranscriptionOutput(
        language="en",
        segments=[seg("SPEAKER_1", 0, 10), seg("SPEAKER_2", 10, 20)],
        metadata=TranscriptionMetadata(
            model="tiny", vad_seconds_speech=20.0, infer_seconds=1.0, beam_size=5
        ),
        speakers=["SPEAKER_1", "SPEAKER_2"],
    )


class _World:
    def __init__(self, timeline: list[tuple[int, int, str]], monkeypatch: pytest.MonkeyPatch):
        self.row: dict[str, Any] = {
            "status": "complete",
            "diarization_status": "queued",
            "diarization_rev": 1,
            "diarization_error": None,
            "diarization_request_id": REQUEST,
            "result_storage_uri": f"minio://{BUCKET}/{ORIGINAL_KEY}",
            "previous_result_storage_uri": None,
            "speaker_names": json.dumps({"SPEAKER_1": "Anna"}),
            "previous_speaker_names": None,
            "metadata": {},
        }
        self.fail_swap: list[bool] = []
        self.transcripts = _Store(BUCKET)
        self.transcripts.objects[ORIGINAL_KEY] = _transcript().model_dump_json().encode()
        self.audio = _Store("mdx-audio")
        self.audio.objects[f"{TENANT}/{AUDIO}.enc"] = b"fake-audio"
        self.audit = _Audit()
        self.diarizer = _Diarizer(timeline)
        self.state = type(
            "S",
            (),
            {
                "app_pool": object(),
                "audio_store": self.audio,
                "transcript_store": self.transcripts,
                "audit_writer": self.audit,
                "diarizer": self.diarizer,
                "shadow_diarizer": None,
                "engine": _NoAsr(),
            },
        )()

        @contextlib.asynccontextmanager
        async def tenant_connection(_pool: object, tenant: UUID) -> AsyncIterator[_Conn]:
            assert tenant == TENANT, "every read and write runs under the job's tenant"
            yield _Conn(self.row, self.fail_swap)

        async def decode(_bytes: bytes, **_kw: Any) -> np.ndarray:
            return np.zeros(16_000 * 20, dtype=np.float32)

        monkeypatch.setattr(processor, "tenant_connection", tenant_connection)
        monkeypatch.setattr(processor, "decode_to_pcm", decode)

    def payload(self, **kw: Any) -> JobEnqueuePayload:
        fields: dict[str, Any] = {
            "job_id": JOB,
            "tenant_id": TENANT,
            "audio_id": AUDIO,
            "language": "en",
            "diarize": True,
            "requester_sub": uuid4(),
            "task": "rediarize",
            "target_rev": 2,
            "rediarize_id": REQUEST,
        }
        fields.update(kw)
        return JobEnqueuePayload(**fields)

    def stored(self, key: str) -> TranscriptionOutput:
        return TranscriptionOutput.model_validate_json(self.transcripts.objects[key])


# Three people this time: Anna keeps 0–10 s (her first 8 s), a new voice
# takes 8–10 s, the second speaker keeps 10–20 s.
_THREE = [(0, 8000, "a"), (8000, 10_000, "c"), (10_000, 20_000, "b")]


async def test_rerun_relabels_from_stored_words_without_asr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(_THREE, monkeypatch)

    await processor._rediarize_one(world.state, world.payload(num_speakers=3))

    new_key = revision_key(TENANT, JOB, 2)
    assert world.transcripts.puts == [new_key]
    result = world.stored(new_key)
    assert result.speakers == ["SPEAKER_1", "SPEAKER_2", "SPEAKER_3"]
    # Same words, same order — only who said them changed.
    before = [w.text for s in _transcript().segments for w in s.words]
    assert [w.text for s in result.segments for w in s.words] == before
    assert world.row["diarization_rev"] == 2
    assert world.row["diarization_status"] == "complete"
    assert world.row["result_storage_uri"] == f"minio://{BUCKET}/{new_key}"
    assert world.row["previous_result_storage_uri"] == f"minio://{BUCKET}/{ORIGINAL_KEY}"
    assert ORIGINAL_KEY in world.transcripts.objects, "the previous revision is kept for undo"
    # Anna kept 80 % of her speech on the new SPEAKER_1 → her name followed.
    assert world.row["speaker_names"] == {"SPEAKER_1": "Anna"}
    assert world.row["metadata"]["diarization"]["hint_num_speakers"] == 3
    assert world.diarizer.hints == [DiarizationHints(num_speakers=3)]
    kind, audit = world.audit.events[-1]
    assert kind == "asr.rediarize_completed"
    assert audit == {"speakers_before": 2, "speakers_after": 3, "engine": "fake"}


async def test_duplicate_delivery_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _World(_THREE, monkeypatch)
    await processor._rediarize_one(world.state, world.payload())

    await processor._rediarize_one(world.state, world.payload())

    assert world.transcripts.puts == [revision_key(TENANT, JOB, 2)]
    assert world.row["diarization_rev"] == 2


async def test_redelivery_after_a_crash_finishes_with_one_revision_bump(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(_THREE, monkeypatch)
    world.fail_swap = [True]  # artifact written, then the DB swap fails

    with pytest.raises(_RetryableError):
        await processor._rediarize_one(world.state, world.payload())
    assert world.row["diarization_rev"] == 1
    assert world.row["diarization_status"] == "running"

    await processor._rediarize_one(world.state, world.payload())

    key = revision_key(TENANT, JOB, 2)
    assert world.transcripts.puts == [key, key], "the same deterministic key, overwritten"
    assert world.row["diarization_rev"] == 2


async def test_missing_audio_fails_the_rerun_and_keeps_the_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(_THREE, monkeypatch)
    world.audio.objects.clear()

    with pytest.raises(_NonRetryableError):
        await processor._rediarize_one(world.state, world.payload())

    assert world.row["status"] == "complete"
    assert world.row["diarization_status"] == "failed"
    assert world.row["diarization_error"] == str(JobErrorKind.AUDIO_MISSING)
    assert world.row["result_storage_uri"] == f"minio://{BUCKET}/{ORIGINAL_KEY}"
    assert world.transcripts.puts == []
    assert world.audit.events[-1] == ("asr.rediarize_failed", {"error_kind": "audio_missing"})


async def test_a_diarizer_crash_is_terminal_for_the_rerun_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(_THREE, monkeypatch)

    def boom(*_a: Any, **_kw: Any) -> OfflineDiarization:
        raise RuntimeError("model choked")

    monkeypatch.setattr(world.diarizer, "diarize", boom)

    with pytest.raises(_NonRetryableError):
        await processor._rediarize_one(world.state, world.payload())
    assert world.row["diarization_error"] == str(JobErrorKind.DIARIZATION_FAILED)
    assert world.row["status"] == "complete"


async def test_a_stale_message_for_an_earlier_request_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review finding: an old message with the same target_rev must not act
    for the newer request (its hints would silently win)."""
    world = _World(_THREE, monkeypatch)

    await processor._rediarize_one(world.state, world.payload(rediarize_id=uuid4()))

    assert world.transcripts.puts == []
    assert world.row["diarization_status"] == "queued", "left for the real request"


async def test_a_stale_failure_cannot_fail_the_newer_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(_THREE, monkeypatch)

    await processor._mark_rediarize_failed(
        world.state, TENANT, JOB, request_id=uuid4(), kind="retry_exhausted"
    )

    assert world.row["diarization_status"] == "queued"
    assert world.audit.events == [], "a write that matched nothing is not audited"


async def test_a_later_run_deletes_the_revision_before_the_previous_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _World(_THREE, monkeypatch)
    await processor._rediarize_one(world.state, world.payload())
    world.row["diarization_status"] = "queued"
    world.row["diarization_request_id"] = second = uuid4()

    await processor._rediarize_one(world.state, world.payload(target_rev=3, rediarize_id=second))

    assert world.transcripts.deleted == [ORIGINAL_KEY]
    assert world.row["previous_result_storage_uri"].endswith(revision_key(TENANT, JOB, 2))
    assert set(world.transcripts.objects) == {
        revision_key(TENANT, JOB, 2),
        revision_key(TENANT, JOB, 3),
    }


async def test_a_rerun_for_an_older_revision_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _World(_THREE, monkeypatch)
    world.row["diarization_rev"] = 4  # an undo or another run moved on

    await processor._rediarize_one(world.state, world.payload(target_rev=2))

    assert world.transcripts.puts == []


# ── Name carry-over ───────────────────────────────────────────────────


def _labelled(spec: list[tuple[str, int, int]]) -> list[Segment]:
    return [
        Segment(
            text="x",
            start_ms=a * 1000,
            end_ms=b * 1000,
            words=_words(a, b),
            avg_confidence=0.9,
            speaker=label,
        )
        for label, a, b in spec
    ]


def test_a_name_follows_an_80_percent_majority() -> None:
    before = _labelled([("SPEAKER_1", 0, 10)])
    after = _labelled([("SPEAKER_1", 0, 8), ("SPEAKER_2", 8, 10)])

    assert carry_over_mapping(before, after) == {"SPEAKER_1": "SPEAKER_1"}


def test_a_50_50_split_carries_no_name() -> None:
    before = _labelled([("SPEAKER_1", 0, 10)])
    after = _labelled([("SPEAKER_1", 0, 5), ("SPEAKER_2", 5, 10)])

    assert carry_over_mapping(before, after) == {}


def test_two_old_speakers_merged_into_one_carry_neither_name() -> None:
    before = _labelled([("SPEAKER_1", 0, 10), ("SPEAKER_2", 10, 20)])
    after = _labelled([("SPEAKER_1", 0, 20)])

    assert carry_over_mapping(before, after) == {}


def test_a_renumbered_speaker_keeps_the_name() -> None:
    before = _labelled([("SPEAKER_2", 0, 10), ("SPEAKER_1", 10, 20)])
    after = _labelled([("SPEAKER_1", 0, 10), ("SPEAKER_2", 10, 20)])

    assert carry_over_mapping(before, after) == {"SPEAKER_2": "SPEAKER_1", "SPEAKER_1": "SPEAKER_2"}


def test_a_name_is_not_carried_onto_a_voice_that_is_mostly_someone_else() -> None:
    """Review finding: A keeps 90 % of itself on X, B puts 55 % on X — X is
    then ~40 % B, so A's name would be half a guess."""
    before = _labelled([("SPEAKER_1", 0, 10), ("SPEAKER_2", 10, 30)])
    after = _labelled(
        [("SPEAKER_1", 0, 9), ("SPEAKER_2", 9, 10), ("SPEAKER_1", 10, 21), ("SPEAKER_2", 21, 30)]
    )

    assert "SPEAKER_1" not in carry_over_mapping(before, after)


# ── Wire compatibility ────────────────────────────────────────────────


def test_an_old_payload_reads_as_transcribe() -> None:
    old = {
        "job_id": str(JOB),
        "tenant_id": str(TENANT),
        "audio_id": str(AUDIO),
        "language": "en",
        "requester_sub": str(uuid4()),
    }

    payload = JobEnqueuePayload.model_validate_json(json.dumps(old))

    assert payload.task == "transcribe"
    assert payload.num_speakers is None
    assert payload.target_rev is None
