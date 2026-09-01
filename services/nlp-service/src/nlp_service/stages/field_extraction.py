"""Stage 6 — field extraction (ADR-0028).

Runs after ``abbreviation`` (so it reads fully normalized text —
numbers, dates and expanded abbreviations already applied) and before
``confidence`` (which must see the final text; this stage adds none).

**This stage never touches text.** Its entire product is metadata: for
each typed section in the context's template snapshot, a proposal the
user confirms or rejects. Below threshold, ambiguous, or negated
⇒ no entry at all (absence, not an empty object) — a wrong auto-filled
field is worse than an empty one.

``runs_on_partials = False``: partial text is unstable, and extracting
from it would make proposals flicker mid-sentence.

Delivery: results land on ``StageOutput.metadata`` under
``field_extraction.fields`` as ``{section_key: metadata-dict}``, which
flows verbatim through ``/nlp/process``'s deterministic ``metadata``
body to the draft-assembly caller (see ADR-0028 for why this path and
not an FE ``Operation``). Every value is produced by
``note_models``' typed constructors, so nothing invalid can be
emitted by construction.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from opentelemetry import metrics

from ..pipeline.base import ProcessingContext, StageInput, StageOutput, TemplateSection
from .extractors.choice import ExtractionResult, choose, choose_multi
from .extractors.numeric_date import bind_date, bind_numeric

logger = logging.getLogger(__name__)

_meter = metrics.get_meter("mdx.nlp.field_extraction")
_extraction_latency = _meter.create_histogram(
    "mdx_nlp_field_extraction_seconds",
    unit="s",
    description="field_extraction stage latency",
)
_extractions = _meter.create_counter(
    "mdx_field_extraction_total",
    unit="1",
    description="Field extraction outcomes by field_type",
)

CHOICE_FIELD_TYPES: Final = frozenset({"choice", "multi_choice"})
NUMERIC_FIELD_TYPES: Final = frozenset({"numeric_with_unit"})
DATE_FIELD_TYPES: Final = frozenset({"date", "date_with_note"})
# Every field type this stage acts on. free_text (and anything else)
# passes through untouched.
EXTRACTABLE_FIELD_TYPES: Final = CHOICE_FIELD_TYPES | NUMERIC_FIELD_TYPES | DATE_FIELD_TYPES


class FieldExtractionStage:
    """Text-neutral; emits proposals only."""

    name = "field_extraction"
    runs_on_partials: bool = False

    def __init__(
        self,
        *,
        confidence_threshold: float,
    ) -> None:
        self._threshold = confidence_threshold

    async def process(self, ctx: ProcessingContext, input: StageInput) -> StageOutput:
        typed = [s for s in ctx.template_sections if s.field_type in EXTRACTABLE_FIELD_TYPES]
        if not typed:
            # No typed sections ⇒ emit NOTHING, not even a marker key.
            # Requests from callers without typed sections must stay
            # byte-identical.
            return StageOutput(
                text=input.text,
                words=input.words,
                confidence_spans=input.confidence_spans,
                voice_commands=input.voice_commands,
                operations=input.operations,
                warnings=input.warnings,
            )

        fields: dict[str, Any] = {}
        for section in typed:
            key = section.section_key or str(section.id)
            result = await self._extract_one(section, input)
            _extractions.add(
                1,
                {
                    "field_type": section.field_type,
                    "outcome": result.outcome,
                    "language": ctx.language,
                },
            )
            meta = result.meta
            if meta is not None:
                # mode="json" so the metadata dict is JSON-native — it is
                # cached, replayed and compared byte-for-byte downstream.
                fields[key] = meta.model_dump(mode="json", exclude_none=True)

        metadata: dict[str, Any] = {}
        if fields:
            # Sorted so the metadata dict's iteration order can never
            # depend on template ordering — replay compares bytes.
            metadata[f"{self.name}.fields"] = {k: fields[k] for k in sorted(fields)}

        return StageOutput(
            text=input.text,
            words=input.words,
            confidence_spans=input.confidence_spans,
            voice_commands=input.voice_commands,
            operations=input.operations,
            warnings=input.warnings,
            metadata=metadata,
        )

    async def _extract_one(self, section: TemplateSection, input: StageInput) -> ExtractionResult:
        if section.field_type in CHOICE_FIELD_TYPES:
            if not section.options:
                # A choice section without options is a template-authoring
                # bug the model already rejects; stay inert rather than guess.
                return ExtractionResult(None, "no_options")
            if section.field_type == "choice":
                return choose(input.text, section.options, threshold=self._threshold)
            return choose_multi(input.text, section.options, threshold=self._threshold)

        if section.field_type in NUMERIC_FIELD_TYPES:
            meta = bind_numeric(
                input.text,
                input.numeric_artifacts,
                section,
                threshold=self._threshold,
            )
            return ExtractionResult(meta, "filled" if meta else "empty")

        if section.field_type in DATE_FIELD_TYPES:
            meta = bind_date(input.date_artifacts, threshold=self._threshold)
            return ExtractionResult(meta, "filled" if meta else "empty")

        return ExtractionResult(None, "unsupported")
