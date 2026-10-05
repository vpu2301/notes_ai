"""``POST /nlp/process`` and ``POST /nlp/process/batch``. Field names are a replay contract."""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from auth import Claims

from .. import PIPELINE_VERSION
from ..deps import assert_size, get_state, rate_limited, requires
from ..domain.repository import fetch_abbreviation_snapshot
from ..pipeline.base import (
    ChoiceOption,
    ProcessingContext,
    StageInput,
    TemplateSection,
    Word,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/nlp", tags=["nlp"])


# ── Wire models (strict) ────────────────────────────────────────────


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WordIn(_StrictModel):
    text: str
    start_s: float = Field(ge=0.0)
    end_s: float = Field(ge=0.0)
    probability: float = Field(ge=0.0, le=1.0)
    is_voice_command_token: bool = False


class ChoiceOptionIn(_StrictModel):
    """Mirrors ``template_models.ChoiceOption``."""

    value: str = Field(max_length=64)
    label: str = Field(max_length=128)
    aliases: list[str] = Field(default_factory=list)


class TemplateSectionIn(_StrictModel):
    id: UUID
    name: str
    aliases: list[str] = Field(default_factory=list)
    # Typed-extraction fields; ``section_key`` keys the extracted-metadata map.
    section_key: str = Field(default="", max_length=64)
    field_type: str = Field(default="free_text", max_length=32)
    options: list[ChoiceOptionIn] = Field(default_factory=list)


class ProcessRequest(_StrictModel):
    text: str
    words: list[WordIn] = Field(default_factory=list)
    language: Literal["uk", "en", "de"]
    # ``specialty`` is the pre-rename wire key.
    category: str | None = Field(
        default=None, validation_alias=AliasChoices("category", "specialty")
    )
    reference_date: date | None = None
    is_partial: bool = False
    template_sections: list[TemplateSectionIn] = Field(default_factory=list)
    decimal_separator: str | None = None
    bp_separator: str | None = None
    date_format: Literal["DD.MM.YYYY", "YYYY-MM-DD", "WORD"] | None = None
    # Conversation mode passes ["voice_commands"] so other speakers cannot trigger edits.
    stages_disabled: list[
        Literal[
            "voice_commands",
            "punctuation",
            "number_norm",
            "date_norm",
            "abbreviation",
            "field_extraction",
            "confidence",
        ]
    ] = Field(default_factory=list)


class ConfidenceSpanOut(_StrictModel):
    start_char: int
    end_char: int
    level: Literal["high_concern", "moderate"]


class WordOut(_StrictModel):
    text: str
    start_s: float
    end_s: float
    probability: float
    is_voice_command_token: bool


class CommandSlotOut(_StrictModel):
    intent: str
    span_start_s: float
    span_end_s: float
    confidence: float
    arg: dict[str, str] | None = None


class OperationOut(_StrictModel):
    op: str
    arg: dict[str, str] | None = None


class WarningOut(_StrictModel):
    code: str
    detail: str = ""
    stage: str = ""


class ProcessResponse(_StrictModel):
    text: str
    words: list[WordOut]
    confidence_spans: list[ConfidenceSpanOut]
    voice_commands: list[CommandSlotOut]
    operations: list[OperationOut]
    warnings: list[WarningOut]
    pipeline_version: str
    metadata: dict[str, Any]


# ── Endpoint ────────────────────────────────────────────────────────


@router.post(
    "/process",
    response_model=ProcessResponse,
    summary="Run the 7-stage NLP pipeline on a single segment.",
)
async def process(
    body: ProcessRequest,
    claims: Annotated[Claims, Depends(rate_limited)],
    _admin: Annotated[Claims, Depends(requires("nlp.process", "nlp_text"))] = ...,  # type: ignore[assignment]
) -> ProcessResponse:
    state = get_state()
    assert_size(body.text, len(body.words))

    ref_date = body.reference_date or date.today()

    snapshot = await fetch_abbreviation_snapshot(
        state.app_pool, tenant_id=claims.tid, language=body.language
    )

    ctx = ProcessingContext(
        tenant_id=claims.tid,
        language=body.language,
        category=body.category,
        reference_date=ref_date,
        is_partial=body.is_partial,
        abbreviation_snapshot=snapshot,
        pipeline_version=PIPELINE_VERSION,
        template_sections=tuple(_section(s) for s in body.template_sections),
        decimal_separator=body.decimal_separator or _default_decimal(body.language),
        bp_separator=body.bp_separator or "/",
        date_format=body.date_format or _default_date_format(body.language),
        stages_disabled=tuple(sorted(set(body.stages_disabled))),
    )

    initial = StageInput(
        text=body.text,
        words=tuple(
            Word(
                text=w.text,
                start_s=w.start_s,
                end_s=w.end_s,
                probability=w.probability,
                is_voice_command_token=w.is_voice_command_token,
            )
            for w in body.words
        ),
    )

    out = await state.orchestrator.run(ctx, initial)

    return ProcessResponse(
        text=out.text,
        words=[
            WordOut(
                text=w.text,
                start_s=w.start_s,
                end_s=w.end_s,
                probability=w.probability,
                is_voice_command_token=w.is_voice_command_token,
            )
            for w in out.words
        ],
        confidence_spans=[
            ConfidenceSpanOut(start_char=s.start_char, end_char=s.end_char, level=s.level)
            for s in out.confidence_spans
        ],
        voice_commands=[
            CommandSlotOut(
                intent=c.intent,
                span_start_s=c.span_start_s,
                span_end_s=c.span_end_s,
                confidence=c.confidence,
                arg=c.arg,
            )
            for c in out.voice_commands
        ],
        operations=[OperationOut(op=o.op, arg=o.arg) for o in out.operations],
        warnings=[WarningOut(code=w.code, detail=w.detail, stage=w.stage) for w in out.warnings],
        pipeline_version=PIPELINE_VERSION,
        metadata=dict(out.metadata),
    )


# ── Batch ───────────────────────────────────────────────────────────


class BatchSegmentIn(_StrictModel):
    text: str
    words: list[WordIn] = Field(default_factory=list)


class BatchProcessRequest(_StrictModel):
    segments: list[BatchSegmentIn]
    language: Literal["uk", "en", "de"]
    # Legacy wire key ``specialty`` accepted.
    category: str | None = Field(
        default=None, validation_alias=AliasChoices("category", "specialty")
    )
    reference_date: date | None = None
    template_sections: list[TemplateSectionIn] = Field(default_factory=list)
    decimal_separator: str | None = None
    bp_separator: str | None = None
    date_format: Literal["DD.MM.YYYY", "YYYY-MM-DD", "WORD"] | None = None
    # Applies to all segments; conversation mode passes ["voice_commands"].
    stages_disabled: list[
        Literal[
            "voice_commands",
            "punctuation",
            "number_norm",
            "date_norm",
            "abbreviation",
            "field_extraction",
            "confidence",
        ]
    ] = Field(default_factory=list)


class BatchSegmentOut(_StrictModel):
    text: str
    words: list[WordOut]
    confidence_spans: list[ConfidenceSpanOut]
    voice_commands: list[CommandSlotOut]
    operations: list[OperationOut]
    warnings: list[WarningOut]


class BatchProcessResponse(_StrictModel):
    segments: list[BatchSegmentOut]
    pipeline_version: str


@router.post(
    "/process/batch",
    response_model=BatchProcessResponse,
    summary="Run the pipeline on a list of segments (sprint-03 batch path).",
)
async def process_batch(
    body: BatchProcessRequest,
    claims: Annotated[Claims, Depends(rate_limited)],
    _admin: Annotated[Claims, Depends(requires("nlp.process", "nlp_text"))] = ...,  # type: ignore[assignment]
) -> BatchProcessResponse:
    state = get_state()
    ref_date = body.reference_date or date.today()
    snapshot = await fetch_abbreviation_snapshot(
        state.app_pool, tenant_id=claims.tid, language=body.language
    )

    ctx = ProcessingContext(
        tenant_id=claims.tid,
        language=body.language,
        category=body.category,
        reference_date=ref_date,
        is_partial=False,
        abbreviation_snapshot=snapshot,
        pipeline_version=PIPELINE_VERSION,
        template_sections=tuple(_section(s) for s in body.template_sections),
        decimal_separator=body.decimal_separator or _default_decimal(body.language),
        bp_separator=body.bp_separator or "/",
        date_format=body.date_format or _default_date_format(body.language),
        # No editor on the batch path: punctuation ops are applied into the text.
        apply_operations_inline=True,
        stages_disabled=tuple(sorted(set(body.stages_disabled))),
    )

    out_segments: list[BatchSegmentOut] = []
    for seg in body.segments:
        assert_size(seg.text, len(seg.words))
        initial = StageInput(
            text=seg.text,
            words=tuple(
                Word(
                    text=w.text,
                    start_s=w.start_s,
                    end_s=w.end_s,
                    probability=w.probability,
                    is_voice_command_token=w.is_voice_command_token,
                )
                for w in seg.words
            ),
        )
        result = await state.orchestrator.run(ctx, initial)
        out_segments.append(
            BatchSegmentOut(
                text=result.text,
                words=[
                    WordOut(
                        text=w.text,
                        start_s=w.start_s,
                        end_s=w.end_s,
                        probability=w.probability,
                        is_voice_command_token=w.is_voice_command_token,
                    )
                    for w in result.words
                ],
                confidence_spans=[
                    ConfidenceSpanOut(start_char=s.start_char, end_char=s.end_char, level=s.level)
                    for s in result.confidence_spans
                ],
                voice_commands=[
                    CommandSlotOut(
                        intent=c.intent,
                        span_start_s=c.span_start_s,
                        span_end_s=c.span_end_s,
                        confidence=c.confidence,
                        arg=c.arg,
                    )
                    for c in result.voice_commands
                ],
                operations=[OperationOut(op=o.op, arg=o.arg) for o in result.operations],
                warnings=[
                    WarningOut(code=w.code, detail=w.detail, stage=w.stage) for w in result.warnings
                ],
            )
        )

    return BatchProcessResponse(segments=out_segments, pipeline_version=PIPELINE_VERSION)


# ── Defaults ────────────────────────────────────────────────────────


def _section(s: TemplateSectionIn) -> TemplateSection:
    """Wire → pipeline section, carrying the typed-extraction fields."""
    return TemplateSection(
        id=s.id,
        name=s.name,
        aliases=tuple(s.aliases or ()),
        section_key=s.section_key,
        field_type=s.field_type,
        options=tuple(
            ChoiceOption(value=o.value, label=o.label, aliases=tuple(o.aliases or ()))
            for o in s.options
        ),
    )


# German shares Ukrainian's decimal comma and DD.MM.YYYY.
def _default_decimal(language: str) -> str:
    return "," if language in {"uk", "de"} else "."


def _default_date_format(language: str) -> Literal["DD.MM.YYYY", "YYYY-MM-DD", "WORD"]:
    return "DD.MM.YYYY" if language in {"uk", "de"} else "YYYY-MM-DD"
