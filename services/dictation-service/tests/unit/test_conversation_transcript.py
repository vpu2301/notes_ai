"""Sprint-14 persisted-transcript shape contract (``_transcript_to_jsonb``).

Two promises live here:

* **Dictation is byte-compatible with pre-sprint-14.** The segment and
  word key sets are pinned EXACTLY — a new key would silently break every
  existing consumer of ``dictation_sessions.transcript``.
* **Conversation is honest.** It adds ids + speaker proposals, and a
  ``UNKNOWN``/null speaker survives into persistence rather than being
  papered over into a party.

Pure: no DB, no models — the diarization stream is a stub and the
speaker naming is the real (pure) state object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from dictation_service.diarization.mapping import SpeakerNaming
from dictation_service.session.finalize import _transcript_to_jsonb
from dictation_service.session.manager import SessionContext

SEGMENT_KEYS = {"text", "start_ms", "end_ms", "avg_confidence", "words", "voice_command"}
WORD_KEYS = {"text", "start_ms", "end_ms", "probability"}
CONVERSATION_EXTRA_SEGMENT_KEYS = {"id", "speaker", "speaker_confidence", "speaker_name"}
CONVERSATION_EXTRA_WORD_KEYS = {"speaker", "speaker_confidence"}


@dataclass
class _Word:
    text: str
    start_ms: int
    end_ms: int
    probability: float


@dataclass
class _Segment:
    text: str
    start_ms: int
    end_ms: int
    avg_confidence: float
    words: list[_Word] = field(default_factory=list)


class _StubDiarization:
    """Attribution by exact (start_ms, end_ms) with a default fallback."""

    def __init__(
        self,
        table: dict[tuple[int, int], tuple[str | None, float | None]],
        default: tuple[str | None, float | None] = (None, None),
    ) -> None:
        self._table = table
        self._default = default
        self.segments: list[Any] = []

    def attribute(self, start_ms: int, end_ms: int) -> tuple[str | None, float | None]:
        return self._table.get((start_ms, end_ms), self._default)


def _segments() -> list[_Segment]:
    return [
        _Segment(
            text="доброго дня",
            start_ms=0,
            end_ms=1_000,
            avg_confidence=0.91,
            words=[
                _Word("доброго", 0, 500, 0.93),
                _Word("дня", 500, 1_000, 0.89),
            ],
        ),
        _Segment(
            text="болить голова",
            start_ms=1_000,
            end_ms=2_000,
            avg_confidence=0.84,
            words=[
                _Word("болить", 1_000, 1_500, 0.85),
                _Word("голова", 1_500, 2_000, 0.83),
            ],
        ),
    ]


def _ctx(
    *,
    mode: str = "dictation",
    diarization: Any | None = None,
    speaker_naming: Any | None = None,
) -> SessionContext:
    ctx = SessionContext(
        session_id=uuid4(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        language="uk",
        vocabulary_hint="",
        target_kind="generic",
        template_id=None,
        mode=mode,
        diarization=diarization,
        speaker_naming=speaker_naming,
    )
    ctx.finalized_segments = list(_segments())
    return ctx


# ── Dictation: the frozen pre-sprint-14 shape ────────────────────────


def test_dictation_segment_shape_is_unchanged() -> None:
    docs = _transcript_to_jsonb(_ctx())

    assert len(docs) == 2
    for doc in docs:
        assert set(doc) == SEGMENT_KEYS
        assert doc["voice_command"] is None
        for word in doc["words"]:
            assert set(word) == WORD_KEYS

    assert docs[0]["text"] == "доброго дня"
    assert docs[0]["start_ms"] == 0
    assert docs[0]["end_ms"] == 1_000
    assert docs[0]["avg_confidence"] == 0.91
    assert [w["text"] for w in docs[0]["words"]] == ["доброго", "дня"]


def test_dictation_with_a_diarizer_attached_still_has_no_speaker_keys() -> None:
    # mode is the switch, not the presence of a stream.
    ctx = _ctx(diarization=_StubDiarization({}, default=("S1", 0.9)))
    docs = _transcript_to_jsonb(ctx)
    assert all(set(doc) == SEGMENT_KEYS for doc in docs)


# ── Conversation: ids + speaker proposals ────────────────────────────


def _conversation_ctx(
    table: dict[tuple[int, int], tuple[str | None, float | None]],
    *,
    names: dict[str, str] | None = None,
    naming: bool = True,
) -> SessionContext:
    speaker_naming: SpeakerNaming | None = None
    if naming:
        speaker_naming = SpeakerNaming()
        if names:
            speaker_naming.set_names(names)
    return _ctx(
        mode="conversation",
        diarization=_StubDiarization(table),
        speaker_naming=speaker_naming,
    )


def test_conversation_adds_ids_speakers_and_names() -> None:
    ctx = _conversation_ctx(
        {
            (0, 1_000): ("S1", 0.9),
            (0, 500): ("S1", 0.9),
            (500, 1_000): ("S1", 0.88),
            (1_000, 2_000): ("S2", 0.77),
            (1_000, 1_500): ("S2", 0.76),
            (1_500, 2_000): ("S2", 0.79),
        },
        names={"S1": "Alice", "S2": "Bob"},
    )

    docs = _transcript_to_jsonb(ctx)

    assert all(set(doc) == SEGMENT_KEYS | CONVERSATION_EXTRA_SEGMENT_KEYS for doc in docs)
    for doc in docs:
        for word in doc["words"]:
            assert set(word) == WORD_KEYS | CONVERSATION_EXTRA_WORD_KEYS

    assert docs[0]["speaker"] == "S1"
    assert docs[0]["speaker_confidence"] == 0.9
    assert docs[0]["speaker_name"] == "Alice"
    assert docs[1]["speaker"] == "S2"
    assert docs[1]["speaker_name"] == "Bob"

    assert [w["speaker"] for w in docs[0]["words"]] == ["S1", "S1"]
    assert [w["speaker_confidence"] for w in docs[1]["words"]] == [0.76, 0.79]


def test_segment_ids_are_unique_uuids() -> None:
    ctx = _conversation_ctx({}, names={"S1": "Alice"})
    docs = _transcript_to_jsonb(ctx)

    ids = [doc["id"] for doc in docs]
    assert len(set(ids)) == len(ids) == 2
    for value in ids:
        assert isinstance(value, str)
        assert str(UUID(value)) == value  # canonical UUID string


def test_unknown_and_null_speakers_survive_into_persistence() -> None:
    ctx = _conversation_ctx(
        {
            (0, 1_000): ("UNKNOWN", 0.2),
            (0, 500): ("UNKNOWN", 0.2),
            (500, 1_000): (None, None),
            # segment 2 and its words fall through to the (None, None) default
        },
        names={"S1": "Alice", "S2": "Bob"},
    )

    docs = _transcript_to_jsonb(ctx)

    assert docs[0]["speaker"] == "UNKNOWN"
    assert docs[0]["speaker_confidence"] == 0.2
    assert docs[0]["speaker_name"] is None  # never guessed into a participant
    assert docs[0]["words"][1]["speaker"] is None
    assert docs[0]["words"][1]["speaker_confidence"] is None

    assert docs[1]["speaker"] is None
    assert docs[1]["speaker_confidence"] is None
    assert docs[1]["speaker_name"] is None


def test_unnamed_speakers_get_the_neutral_defaults() -> None:
    ctx = _conversation_ctx({(0, 1_000): ("S1", 0.9)})

    docs = _transcript_to_jsonb(ctx)

    assert docs[0]["speaker"] == "S1"
    assert docs[0]["speaker_name"] == "SPEAKER_1"
    assert "id" in docs[0]


def test_no_naming_state_emits_speakers_without_names() -> None:
    ctx = _conversation_ctx({(0, 1_000): ("S1", 0.9)}, naming=False)

    docs = _transcript_to_jsonb(ctx)

    assert docs[0]["speaker"] == "S1"
    assert docs[0]["speaker_name"] is None
