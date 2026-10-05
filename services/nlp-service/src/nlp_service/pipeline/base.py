"""Stage interface + pipeline types: frozen records threaded by the orchestrator (no in-place mutation)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Word:
    """One word + word-level metadata; ``is_voice_command_token`` lets later stages skip it."""

    text: str
    start_s: float
    end_s: float
    probability: float
    is_voice_command_token: bool = False
    # Hidden from the displayed text (filler, first copy of a repeat); timing stays.
    hidden: bool = False


@dataclass(frozen=True, slots=True)
class ConfidenceSpan:
    """A character range in the post-processed text with a confidence label."""

    start_char: int
    end_char: int
    level: Literal["high_concern", "moderate"]


@dataclass(frozen=True, slots=True)
class CommandSlot:
    """One detected voice command."""

    intent: str
    span_start_s: float
    span_end_s: float
    confidence: float
    arg: dict[str, str] | None = None  # e.g., {"section_id": "..."}


@dataclass(frozen=True, slots=True)
class Operation:
    """A frontend-actionable editor operation, derived from a CommandSlot."""

    op: str
    arg: dict[str, str] | None = None


@dataclass(frozen=True, slots=True)
class PipelineWarning:
    code: str
    detail: str = ""
    stage: str = ""


@dataclass(frozen=True, slots=True)
class AbbreviationEntry:
    """One row from ``abbreviation_dictionary``, snapshotted at request entry."""

    expanded: str
    abbreviated: str
    direction: Literal["expand", "compact", "either"]
    domain: str | None
    case_sensitive: bool
    is_tenant_override: bool


@dataclass(frozen=True, slots=True)
class AbbreviationSnapshot:
    """Immutable per-request abbreviation snapshot; ``fingerprint`` is part of the idempotence key."""

    entries: tuple[AbbreviationEntry, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class ChoiceOption:
    """One option of a choice/multi_choice section; ``aliases`` arrive already normalized."""

    value: str
    label: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TemplateSection:
    """One section a `section.<name>` voice command can navigate to; typed fields are optional."""

    id: UUID
    name: str
    aliases: tuple[str, ...] = ()
    # The template's section slug; ``id`` is the row UUID, not what note content keys by.
    section_key: str = ""
    field_type: str = "free_text"
    options: tuple[ChoiceOption, ...] = ()


@dataclass(frozen=True, slots=True)
class ProcessingContext:
    """Per-request immutable context. Stages MUST NOT mutate this."""

    tenant_id: UUID
    language: Literal["uk", "en", "de"]
    category: str | None
    reference_date: date
    is_partial: bool
    abbreviation_snapshot: AbbreviationSnapshot
    pipeline_version: str
    template_sections: tuple[TemplateSection, ...] = ()
    decimal_separator: str = ","
    bp_separator: str = "/"
    date_format: Literal["DD.MM.YYYY", "YYYY-MM-DD", "WORD"] = "DD.MM.YYYY"
    # Batch path only: no editor, so text-shaped ops are applied into ``text`` by Stage 1.
    apply_operations_inline: bool = False
    # Stage names to skip; normalized (dedupe + sort) by callers, part of the cache key.
    stages_disabled: tuple[str, ...] = ()
    # Diarized conversation, not dictation; the disfluency stage runs only then.
    conversation: bool = False


@dataclass(frozen=True, slots=True)
class NumericArtifact:
    """One measurement the number normalizer produced; the binder consumes these, never re-parses text."""

    value: str  # normalized numeric form, e.g. "140" or "37,2"
    unit: str  # "" when the utterance carried no unit
    rendered: str  # exactly what was written into the text
    token_index: int  # position in the normalizer's output token stream


@dataclass(frozen=True, slots=True)
class DateArtifact:
    """One ISO date present in the date normalizer's output."""

    iso: str  # YYYY-MM-DD
    char_index: int  # position in the normalized text


@dataclass(frozen=True, slots=True)
class StageInput:
    """Input to a pipeline stage."""

    text: str
    words: tuple[Word, ...] = ()
    confidence_spans: tuple[ConfidenceSpan, ...] = ()
    voice_commands: tuple[CommandSlot, ...] = ()
    operations: tuple[Operation, ...] = ()
    warnings: tuple[PipelineWarning, ...] = ()
    # Structured products of earlier stages, threaded by the orchestrator.
    numeric_artifacts: tuple[NumericArtifact, ...] = ()
    date_artifacts: tuple[DateArtifact, ...] = ()


@dataclass(frozen=True, slots=True)
class StageOutput:
    """Output of a pipeline stage. Carries per-stage telemetry in ``metadata``."""

    text: str
    words: tuple[Word, ...] = ()
    confidence_spans: tuple[ConfidenceSpan, ...] = ()
    voice_commands: tuple[CommandSlot, ...] = ()
    operations: tuple[Operation, ...] = ()
    warnings: tuple[PipelineWarning, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    # Structured products for later stages; never serialized into the response.
    numeric_artifacts: tuple[NumericArtifact, ...] = ()
    date_artifacts: tuple[DateArtifact, ...] = ()

    def as_input(self) -> StageInput:
        return StageInput(
            text=self.text,
            words=self.words,
            confidence_spans=self.confidence_spans,
            voice_commands=self.voice_commands,
            operations=self.operations,
            warnings=self.warnings,
            numeric_artifacts=self.numeric_artifacts,
            date_artifacts=self.date_artifacts,
        )


class Stage(Protocol):
    """Pipeline stage Protocol."""

    name: str

    async def process(self, ctx: ProcessingContext, input: StageInput) -> StageOutput: ...

    @property
    def runs_on_partials(self) -> bool:
        """True if this stage runs on partials."""
        ...
