"""The transcript JSON schema.

Persisted as encrypted JSON in the transcripts bucket. The worker writes
it; the API returns a pre-signed URL to it; sprint 05's NLP postprocessor
consumes it. Stable by contract — additions are fine, breaking changes
need a wire-version bump and a migration story.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, NonNegativeFloat, NonNegativeInt

# Neutral diarization label: ``SPEAKER_1``.. — the only speaker identity
# the platform ever produces on its own (no name inference, ADR-0034).
SPEAKER_LABEL_PATTERN = r"^SPEAKER_[1-9][0-9]{0,2}$"


def default_speaker_name(label: str) -> str:
    """Human default for a neutral label: ``SPEAKER_2`` → ``Speaker 2``.

    Used wherever a label has not been named by a person yet (the
    transcript view, the note body). Anything that is not a neutral
    label passes through unchanged.
    """
    if label.startswith("SPEAKER_") and label[8:].isdigit():
        return f"Speaker {label[8:]}"
    return label


class WordTiming(BaseModel):
    text: str
    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    probability: float = Field(ge=0.0, le=1.0)


class Segment(BaseModel):
    text: str
    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    words: list[WordTiming] = Field(default_factory=list)
    avg_confidence: float = Field(ge=0.0, le=1.0)
    # Ambient Capture v1: neutral diarization label ("SPEAKER_1".."SPEAKER_N").
    # None when the job was not diarized, or when the diarizer could not
    # attribute this segment with confidence (never a guess).
    speaker: str | None = None
    # Sprint 30: part of this segment's label came from smoothing (a word
    # the diarizer could not place took its neighbours' speaker, or a
    # one-word island was folded). Turns built on it are marked uncertain.
    speaker_uncertain: bool = False
    # Sprint I2: the language THIS segment was decoded in when it is not the
    # recording's (a Ukrainian aside in an English recording is decoded as
    # Ukrainian and labelled, never translated). None = the recording's.
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")


class EchoSpan(BaseModel):
    """Words removed as prompt echo (Sprint I2 T3): where and how many,
    never which."""

    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    words: NonNegativeInt


# Sprint F1: why a stretch of speech has no transcript. ``no_audio`` is the
# time between the Record press and the first frame the client wrote — it
# precedes the file, so its range is in Record-press time and not seekable.
GapCause = Literal[
    "no_audio",
    "no_speech_detected",
    "decoder_empty",
    "prompt_echo",
    "other_language",
    # Sprint TQ2: the backend request for this run's group failed.
    "backend_error",
    "unknown",
]


class CoverageGap(BaseModel):
    """A stretch of speech the transcript does not cover (Sprint F1)."""

    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    cause: GapCause


class Coverage(BaseModel):
    """How much of the speech the transcript covers (Sprint F1, decision 1).

    ``speech_ms`` is what voice activity detection heard; ``transcribed_ms``
    is ``speech_ms`` minus every gap inside the file. A gap is a speech run
    of at least 3 s that no surviving word covers for half its length. The
    ``no_audio`` gap (capture latency) is reported but lies outside the file
    and therefore outside both totals. Offsets and counts only, never text.
    """

    speech_ms: NonNegativeInt = 0
    transcribed_ms: NonNegativeInt = 0
    first_speech_ms: NonNegativeInt | None = None
    first_segment_ms: NonNegativeInt | None = None
    gaps: list[CoverageGap] = Field(default_factory=list)
    # "stub" = Silero was not installed (dev CPU fallback): the whole file is
    # one speech run, so coverage is complete by construction.
    vad: Literal["silero", "stub"] = "silero"

    @property
    def share(self) -> float:
        return 1.0 if self.speech_ms == 0 else min(1.0, self.transcribed_ms / self.speech_ms)


class SecondPass(BaseModel):
    """Chunks decoded a second time, without the prompt (Sprint F1,
    decision 3): how many, how many words the second attempt brought back,
    and why each ran (``low_coverage`` | ``prompt_echo`` | ``decoder_empty``
    | ``timeout``)."""

    chunks: NonNegativeInt = 0
    recovered_words: NonNegativeInt = 0
    by_cause: dict[str, int] = Field(default_factory=dict)


class SegmentDiagnostics(BaseModel):
    """The decoder's own numbers for one segment it returned (Sprint TQ1 T5).

    Recorded for every segment the backend decoded, including ones a guard
    later dropped, so the non-speech gates (TQ2) can be tuned on what the
    decoder said about itself. A backend that does not report a number
    leaves it ``None`` (whisper.cpp omits some); nothing fails on its
    absence. Numbers and times only, never text.
    """

    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")
    no_speech_prob: float | None = None
    avg_logprob: float | None = None
    compression_ratio: float | None = None
    # True for a segment from the prompt-free second decode of a lost run.
    second_pass: bool = False


DropReason = Literal["no_speech", "loop", "low_confidence_nonspeech", "artefact"]


class DroppedSegment(BaseModel):
    """A decoded segment (or the tail of one) a quality gate removed —
    Sprint TQ2 T2/T3. Numbers and enum strings only."""

    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    reason: DropReason
    no_speech_prob: float | None = None
    avg_logprob: float | None = None
    compression_ratio: float | None = None
    # VAD speech share inside the segment, the condition that protects
    # real quiet speech.
    speech_share: float | None = None
    # ``<language>:<index>`` into asr_models/artefacts.yaml for reason
    # ``artefact``.
    artefact: str | None = Field(default=None, max_length=12)
    # Guards switched off (MDX_ASR_GATES_ENABLED=false): recorded, not removed.
    dry_run: bool = False


class KeptArtefact(BaseModel):
    """A known artefact phrase over audio VAD calls speech — kept, flagged
    (a real "Vielen Dank." at the end of a meeting survives)."""

    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    artefact: str = Field(max_length=12)


class LoopEvent(BaseModel):
    """A repetition loop (G2) and what the prompt-free second decode did."""

    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    outcome: Literal["recovered", "kept_truncated", "second_pass_failed", "second_pass_off"]


class BackendError(BaseModel):
    """A run group whose request failed (HTTP backends); its speech is a
    coverage gap with cause ``backend_error``, never silently empty."""

    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    kind: str = Field(max_length=32)
    # The run's planned language, so a retry decodes it in that language.
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")


class ShadowDiagnostics(BaseModel):
    """Sprint TQ4 T4: a candidate engine decoded the same audio after the
    primary; only how the two differed is kept — never the shadow's text."""

    backend: str = Field(max_length=32)
    # Why no comparison: "error" | "timeout" | "budget" | "unavailable".
    skipped: str | None = Field(default=None, max_length=16)
    words_primary: NonNegativeInt = 0
    words_shadow: NonNegativeInt = 0
    # Word edit distance between the two transcripts ÷ the primary's words
    # (the shadow's "WER" with the primary as reference — a disagreement
    # rate, not an error rate).
    word_disagreement: float | None = None
    # Distinct capitalised word forms: a proxy for how many spellings of
    # names each engine produced.
    name_forms_primary: NonNegativeInt = 0
    name_forms_shadow: NonNegativeInt = 0
    dropped_primary: NonNegativeInt = 0
    dropped_shadow: NonNegativeInt = 0
    rtf: float | None = None


NoiseKind = Literal["music", "silence", "noise"]


class NoiseRegion(BaseModel):
    """A stretch of ≥ 5 s with no VAD speech, marked instead of transcribed
    (Sprint TQ2 T4). Clients render an unknown ``kind`` as ``noise``."""

    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    kind: NoiseKind


class Diagnostics(BaseModel):
    """What the guards did to this transcript. Counts and timestamps only;
    lives in the stored artifact, not in a table."""

    prompt_echo: list[EchoSpan] = Field(default_factory=list)
    prompt_echo_segments_dropped: NonNegativeInt = 0
    other_language_chunks: NonNegativeInt = 0
    # Sprint F1. None on artifacts stored before coverage was measured.
    coverage: Coverage | None = None
    second_pass: SecondPass = Field(default_factory=SecondPass)
    # Sprint TQ1 T5: per decoded segment, in time order. Empty on artifacts
    # stored before it was recorded.
    segments: list[SegmentDiagnostics] = Field(default_factory=list)
    # Sprint TQ2: what the guards removed or kept, and why.
    dropped_segments: list[DroppedSegment] = Field(default_factory=list)
    artefact_kept: list[KeptArtefact] = Field(default_factory=list)
    loops: list[LoopEvent] = Field(default_factory=list)
    backend_errors: list[BackendError] = Field(default_factory=list)
    # A gate that could not read its field on this backend → segments it
    # skipped, per field (e.g. ``compression_ratio`` on whisper.cpp).
    gate_unavailable: dict[str, int] = Field(default_factory=dict)
    # Who decided each run's language: the engine's own model (in-process),
    # the worker's local identifier (HTTP backends), or nobody.
    language_id: Literal["engine", "local", "unavailable", "pinned"] | None = None
    # Sprint TQ4 T4: the candidate engine's shadow comparison (numbers only).
    shadow: ShadowDiagnostics | None = None


class DiarizationStats(BaseModel):
    """Why a diarized job produced N speakers (Sprint 28). Numbers only:
    no labels-to-names mapping, no text, no embeddings."""

    engine: str
    engine_version: str
    hint_num_speakers: int | None = None
    hint_max_speakers: int | None = None
    chunks: NonNegativeInt
    clusters_raw: NonNegativeInt  # after agglomeration
    clusters_after_merge: NonNegativeInt  # after the centroid merge
    clusters_dropped: NonNegativeInt  # below the speaker floor / over the cap
    speakers: NonNegativeInt  # labels that reached a segment
    speech_seconds: NonNegativeFloat
    speaker_speech_seconds: list[float] = Field(default_factory=list)  # descending
    unknown_share: float = Field(ge=0.0, le=1.0)
    seconds: NonNegativeFloat  # wall time of the diarization step
    # Sprint 29 roster guard. ``count_confidence`` is a word, not a
    # probability: "low" when a kept speaker is tiny, a dissolved one was
    # not, or much of the speech overlaps. None on pre-Sprint-29 results.
    count_confidence: Literal["high", "low"] | None = None
    speakers_dissolved: NonNegativeInt = 0
    overlap_share: float | None = Field(default=None, ge=0.0, le=1.0)
    # Sprint 31 dual-channel capture: "mono" | "mic_system" |
    # "mono_fallback" (the channel analysis failed and the mixdown was
    # diarized instead). Numbers only.
    channel_layout: str | None = None
    leak_gain_db: float | None = None
    local_speakers: NonNegativeInt | None = None
    remote_speakers: NonNegativeInt | None = None
    both_share: float | None = Field(default=None, ge=0.0, le=1.0)


class TranscriptionMetadata(BaseModel):
    model: str
    vad_seconds_speech: NonNegativeFloat
    infer_seconds: NonNegativeFloat
    gpu_seconds: NonNegativeFloat = 0.0
    peak_gpu_mem_mb: NonNegativeInt = 0
    beam_size: int = Field(ge=1)
    # None for undiarized jobs and for transcripts stored before Sprint 28.
    diarization: DiarizationStats | None = None
    # Sprint F1: ``diagnostics.coverage.share``, copied here because the
    # metadata is also written to the job row — support reads it off the
    # job view without decrypting the transcript. None before F1.
    coverage_share: float | None = Field(default=None, ge=0.0, le=1.0)


class TranscriptionOutput(BaseModel):
    # The language the transcript is written in, as an ISO 639-1 code.
    # A job submitted with ``language=auto`` stores whatever Whisper's
    # language identification heard (any Whisper language, not just the
    # ones the NLP post-processor knows); a pinned job echoes the pin.
    # Never the literal ``auto``.
    language: str = Field(pattern=r"^[a-z]{2,3}$")
    # True when ``language`` came from language identification rather than
    # the caller; ``language_probability`` is the detector's confidence.
    language_detected: bool = False
    language_probability: float | None = Field(default=None, ge=0.0, le=1.0)
    segments: list[Segment]
    metadata: TranscriptionMetadata
    # Distinct speaker labels in first-appearance order; empty when the
    # job was not diarized (additive — older stored transcripts decode
    # with an empty list).
    speakers: list[str] = Field(default_factory=list)
    # Sprint 30: where two people spoke at once, per the diarizer (engine
    # v2 only; empty for legacy and older transcripts). Time intervals only.
    overlap_ms: list[tuple[int, int]] = Field(default_factory=list)
    # Sprint 31: label → "local" (this Mac's microphone) | "remote" (the
    # call audio). Empty for mono captures.
    speaker_sides: dict[str, Literal["local", "remote"]] = Field(default_factory=dict)
    # Sprint I2: prompt-echo spans and other-language chunk count. Older
    # artifacts decode with the empty default.
    diagnostics: Diagnostics = Field(default_factory=Diagnostics)
    # Sprint TQ2 T4: non-speech regions ≥ 5 s, marked instead of transcribed.
    noise: list[NoiseRegion] = Field(default_factory=list)
    schema_version: int = 1


# ── Result view (API-facing, sprint-05 NLP enrichment) ──────────────


class ConfidenceSpanView(BaseModel):
    """A character range in an enriched segment's ``text`` flagged by the
    NLP confidence stage (low word-probability regions, risky numbers,
    …)."""

    start_char: NonNegativeInt
    end_char: NonNegativeInt
    level: str  # "high_concern" | "moderate"


class EnrichedSegment(BaseModel):
    """One segment as served by ``GET /asr/jobs/{id}/result``.

    ``text`` is the NLP post-processed rendering (dictated punctuation
    applied, numbers/dates normalized) when the view's ``nlp_applied``
    is true; otherwise it equals ``raw_text``. ``words`` always carry
    the raw Whisper timings.
    """

    text: str
    raw_text: str
    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    words: list[WordTiming] = Field(default_factory=list)
    avg_confidence: float = Field(ge=0.0, le=1.0)
    confidence_spans: list[ConfidenceSpanView] = Field(default_factory=list)
    # Carried through from the stored transcript for diarized jobs.
    speaker: str | None = None
    # Sprint 30: which stored-artifact segment(s) this rendering is. NLP can
    # fold a punctuation-only segment into its predecessor, so one served
    # segment may stand for several artifact segments; edits address the
    # artifact, never positions in this list.
    artifact_index: int | None = None
    artifact_indices: list[int] = Field(default_factory=list)
    speaker_uncertain: bool = False
    # A person moved this segment to "Unknown": turn building must not fold
    # it back into the neighbouring speaker.
    speaker_cleared: bool = False
    # Sprint I2: set when this segment is in another language than the
    # recording (ISO 639-1); None = the recording's language.
    language: str | None = None


class TranscriptTurnView(BaseModel):
    """One speaker turn: the structure a reader actually wants.

    Built at read time from the (enriched) segments — consecutive
    segments by the same speaker, with long stretches broken into
    paragraphs at pauses and sentence ends (``asr_models.structure``).
    A turn whose ``speaker`` is ``None`` is speech the diarizer could
    not attribute (or an undiarized job, which is one long turn).
    """

    speaker: str | None = None
    # What to show for the speaker: the name a person gave this label
    # on the job, else the neutral default ("Speaker 2"); None when
    # the turn is unattributed.
    name: str | None = None
    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    paragraphs: list[str]
    # Indices of the STORED ARTIFACT's segments behind this turn (Sprint 30:
    # artifact index space, not positions in ``segments``). Opaque to
    # clients: sent back as-is to reassign the turn; a served segment's
    # ``artifact_index`` maps between the two.
    segment_indices: list[int] = Field(default_factory=list)
    # People talked over each other here, or the label was smoothed across
    # speech the diarizer could not place — where corrections are likeliest.
    uncertain: bool = False
    # Sprint I2: a turn in another language than the recording (a turn is
    # never mixed: the structure breaks where the language changes).
    language: str | None = None


class SpeakerStatView(BaseModel):
    """Talk time of one roster label, after speaker edits."""

    label: str
    speech_ms: NonNegativeInt
    share: float = Field(ge=0.0, le=1.0)
    turns: NonNegativeInt


class SpeakerEditView(BaseModel):
    """A live (not reverted) speaker edit applied to the transcript."""

    id: UUID
    kind: str  # "merge" | "reassign" (Sprint 30)
    from_label: str | None = None
    to_label: str | None = None
    created_at: datetime
    # A reassign that moved turns to a speaker the system missed (Sprint 30).
    creates_label: bool = False


class NameSuggestionView(BaseModel):
    """A name offered for an unnamed speaker, with the quote that justifies
    it (Sprint 32). Evidence is shown before a person accepts."""

    label: str
    name: str  # calendar spelling
    source: Literal["self_introduction"] = "self_introduction"
    quote: str
    start_ms: NonNegativeInt
    end_ms: NonNegativeInt
    segment_indices: list[int] = Field(default_factory=list)
    # Sprint F3: the role clause after the name, verbatim ("I am a broker
    # with Springbrook Marine Group"), or None. Nothing is inferred.
    role_text: str | None = None


class CoverageView(BaseModel):
    """``Coverage`` as served on ``/result``, with the share spelled out."""

    speech_ms: NonNegativeInt
    transcribed_ms: NonNegativeInt
    first_speech_ms: NonNegativeInt | None = None
    first_segment_ms: NonNegativeInt | None = None
    share: float = Field(ge=0.0, le=1.0)
    gaps: list[CoverageGap] = Field(default_factory=list)
    vad: Literal["silero", "stub"] = "silero"

    @classmethod
    def of(cls, coverage: Coverage) -> CoverageView:
        return cls(**coverage.model_dump(), share=round(coverage.share, 4))


class CaptureTimingView(BaseModel):
    """When the person pressed Record and how long the first audio frame
    took (Sprint F1). Client wall clock; both None for older clients."""

    record_pressed_at: datetime | None = None
    first_frame_offset_ms: NonNegativeInt | None = None


class EntityCorrectionView(BaseModel):
    """Sprint TQ3: one unified spelling — the overlay the view applied
    (``accepted``) or offers for review (``proposed``)."""

    id: UUID
    kind: Literal["entity"] = "entity"
    from_forms: list[str]
    to_text: str
    occurrences_count: NonNegativeInt
    source: Literal["glossary", "calendar", "hint", "majority", "user"]
    confidence: float = Field(ge=0.0, le=1.0)
    status: Literal["proposed", "accepted", "rejected"]
    # A person accepted, edited or rejected it: the review sheet has
    # nothing left to ask about it. An applied row nobody decided is still
    # under review.
    decided: bool = False


class TranscriptResultView(BaseModel):
    """Plaintext transcript response for a COMPLETE job (proxy-decrypt).

    The stored artifact stays :class:`TranscriptionOutput` (raw ASR);
    NLP enrichment is applied at read time and degrades gracefully —
    ``nlp_applied=False`` means the segments are the raw transcript.
    """

    job_id: UUID
    language: str = Field(pattern=r"^[a-z]{2,3}$")
    language_detected: bool = False
    language_probability: float | None = None
    segments: list[EnrichedSegment]
    metadata: TranscriptionMetadata
    # Distinct speaker labels in first-appearance order (diarized jobs).
    speakers: list[str] = Field(default_factory=list)
    # Label → display name for every roster label: the name a person
    # assigned via ``PUT /asr/jobs/{id}/speakers``, else the neutral
    # default ("Speaker 1"). Empty for undiarized jobs.
    speaker_names: dict[str, str] = Field(default_factory=dict)
    # The transcript as speaker turns with paragraphs — derived from
    # ``segments``; clients render this, not the raw segment list.
    turns: list[TranscriptTurnView] = Field(default_factory=list)
    # Talk time per roster label (after edits), roster order.
    speaker_stats: list[SpeakerStatView] = Field(default_factory=list)
    # Diarization run the edits apply to; bumped by a re-run (Sprint 29).
    result_rev: int = 1
    # Live speaker edits, application order. The stored artifact is never
    # rewritten: edits are an overlay applied at read time.
    edits: list[SpeakerEditView] = Field(default_factory=list)
    # How sure the diarizer is of the NUMBER of speakers (Sprint 29);
    # mirrors ``metadata.diarization.count_confidence``. None = undiarized
    # or a result stored before the roster guard existed.
    count_confidence: Literal["high", "low"] | None = None
    # The exact count a person asked for on this labelling, if any. More
    # than ``len(speakers)`` means fewer voices could be told apart.
    speakers_hint: int | None = None
    # Names offered for renaming (Sprint 30): the calendar invitees captured
    # with the recording. A picklist — the product never assigns them.
    name_candidates: list[str] = Field(default_factory=list)
    # Sprint 31: which side each speaker was heard on (dual-channel only),
    # and how each name came about — "channel" means the server named the
    # only local speaker after the account owner; one click clears it.
    speaker_sides: dict[str, Literal["local", "remote"]] = Field(default_factory=dict)
    speaker_name_sources: dict[str, str] = Field(default_factory=dict)
    # Sprint 32. ``None`` = suggestions are switched off server-side.
    name_suggestions: list[NameSuggestionView] | None = None
    # Made by an older engine (or never by the current one) and the audio
    # still exists: "Re-label with the current engine" can be offered.
    relabel_available: bool = False
    nlp_applied: bool = False
    nlp_pipeline_version: str | None = None
    # Sprint I3 T2: how much of this view the post-processor shaped —
    # ``full`` (every segment), ``partial`` (a stage failed on some segment,
    # which then shows its raw text) or ``raw`` (nlp-service down, a
    # language it has no rules for, or an empty transcript).
    enrichment: Literal["full", "partial", "raw"] = "raw"
    # Sprint I2: what the guards removed or labelled (timestamps and counts).
    diagnostics: Diagnostics = Field(default_factory=Diagnostics)
    # Sprint F1: how much of the speech is transcribed, and every gap with
    # its cause (None on transcripts stored before coverage was measured);
    # and the capture timing the client reported at upload.
    coverage: CoverageView | None = None
    capture: CaptureTimingView | None = None
    # Sprint TQ2 T4: music / silence / noise markers, rendered by the
    # clients as non-speaker lines. Additive: older clients ignore it.
    noise: list[NoiseRegion] = Field(default_factory=list)
    # Sprint TQ3: spellings unified by the overlay (accepted, applied in
    # ``segments``/``turns``) or offered for review (proposed); rejected ones
    # are left out. ``corrections_rev`` is what a PUT must name.
    entity_corrections: list[EntityCorrectionView] = Field(default_factory=list)
    corrections_rev: NonNegativeInt = 0
    # Why there are none: "skipped_budget" | "error" | "disabled"; None = ran.
    entity_unify: str | None = None
    schema_version: int = 1
