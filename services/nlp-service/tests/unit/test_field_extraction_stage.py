"""``field_extraction`` stage contracts (ADR-0028).

Stage-level invariants: text neutrality, finals-only, deterministic
metadata, no emission when there is nothing to extract, and typed
construction (no raw dicts).
"""

from __future__ import annotations

import json
from datetime import date
from uuid import UUID, uuid4

import pytest

from nlp_service.pipeline.base import (
    AbbreviationSnapshot,
    ChoiceOption,
    ProcessingContext,
    StageInput,
    StageOutput,
    TemplateSection,
    Word,
)
from nlp_service.pipeline.orchestrator import Orchestrator, idempotence_key
from nlp_service.stages.field_extraction import FieldExtractionStage
from tests.fixtures.extraction_corpus_uk import CHANNEL_OPTIONS, SUBSCRIPTION_OPTIONS

pytestmark = pytest.mark.asyncio

THRESHOLD = 0.8
_TENANT = UUID("00000000-0000-0000-0000-00000000000a")


def _subscription_section() -> TemplateSection:
    return TemplateSection(
        id=uuid4(),
        name="Статус підписки",
        aliases=("підписка",),
        section_key="subscription_status",
        field_type="choice",
        options=SUBSCRIPTION_OPTIONS,
    )


def _channels_section() -> TemplateSection:
    return TemplateSection(
        id=uuid4(),
        name="Канали зв'язку",
        aliases=("канали",),
        section_key="channels",
        field_type="multi_choice",
        options=CHANNEL_OPTIONS,
    )


def _free_text_section() -> TemplateSection:
    return TemplateSection(
        id=uuid4(),
        name="Нотатки",
        aliases=("нотатки",),
        section_key="general_notes",
        field_type="free_text",
    )


def _ctx(
    sections: tuple[TemplateSection, ...] = (),
    *,
    is_partial: bool = False,
) -> ProcessingContext:
    return ProcessingContext(
        tenant_id=_TENANT,
        language="uk",
        category=None,
        reference_date=date(2026, 7, 22),
        is_partial=is_partial,
        abbreviation_snapshot=AbbreviationSnapshot(entries=(), fingerprint="fp"),
        pipeline_version="nlp-v1.1.0",
        template_sections=sections,
    )


def _stage() -> FieldExtractionStage:
    return FieldExtractionStage(confidence_threshold=THRESHOLD)


# ── text neutrality ─────────────────────────────────────────────────


async def test_stage_never_changes_text_or_words() -> None:
    words = (Word(text="клієнт", start_s=0.0, end_s=0.5, probability=0.99),)
    input = StageInput(text="клієнт не підписаний", words=words)
    out = await _stage().process(_ctx((_subscription_section(),)), input)
    assert out.text == input.text
    assert out.words == input.words
    assert out.confidence_spans == input.confidence_spans
    assert out.voice_commands == input.voice_commands
    assert out.operations == input.operations
    assert out.warnings == input.warnings


async def test_downstream_confidence_sees_identical_bytes() -> None:
    text = "клієнт підписаний, питань немає"
    out = await _stage().process(_ctx((_subscription_section(),)), StageInput(text=text))
    assert out.as_input().text.encode("utf-8") == text.encode("utf-8")


# ── emission ────────────────────────────────────────────────────────


async def test_fills_a_choice_section() -> None:
    out = await _stage().process(
        _ctx((_subscription_section(),)), StageInput(text="клієнт підписаний")
    )
    fields = out.metadata["field_extraction.fields"]
    assert fields["subscription_status"]["selected"] == "current"
    assert fields["subscription_status"]["source"] == "extracted"
    assert fields["subscription_status"]["confidence"] >= THRESHOLD


async def test_fills_a_multi_choice_section() -> None:
    out = await _stage().process(
        _ctx((_channels_section(),)),
        StageInput(text="зв'язок через імейл та телефон"),
    )
    selected = out.metadata["field_extraction.fields"]["channels"]["selected"]
    assert set(selected) == {"email", "phone"}


async def test_negated_utterance_fills_the_negative_option() -> None:
    out = await _stage().process(
        _ctx((_subscription_section(),)), StageInput(text="клієнт не підписаний")
    )
    assert out.metadata["field_extraction.fields"]["subscription_status"]["selected"] == "never"


async def test_below_threshold_emits_no_entry_at_all() -> None:
    """Absence, not an empty object — the prose stands alone."""
    out = await _stage().process(
        _ctx((_subscription_section(),)), StageInput(text="клієнт пдпсн щось")
    )
    assert out.metadata == {}


async def test_ambiguity_emits_no_entry() -> None:
    out = await _stage().process(
        _ctx((_subscription_section(),)), StageInput(text="підписаний та не підписаний окремо")
    )
    assert out.metadata == {}


async def test_free_text_sections_are_ignored() -> None:
    out = await _stage().process(
        _ctx((_free_text_section(),)), StageInput(text="клієнт підписаний")
    )
    assert out.metadata == {}


async def test_no_typed_sections_emits_nothing() -> None:
    """Callers without typed sections must see byte-identical output."""
    out = await _stage().process(_ctx(()), StageInput(text="клієнт підписаний"))
    assert out.metadata == {}


async def test_choice_section_without_options_stays_inert() -> None:
    section = TemplateSection(
        id=uuid4(), name="X", section_key="x", field_type="choice", options=()
    )
    out = await _stage().process(_ctx((section,)), StageInput(text="клієнт підписаний"))
    assert out.metadata == {}


async def test_multiple_sections_extracted_independently() -> None:
    ctx = _ctx((_free_text_section(), _subscription_section(), _channels_section()))
    out = await _stage().process(ctx, StageInput(text="клієнт підписаний, зв'язок через телефон"))
    fields = out.metadata["field_extraction.fields"]
    assert set(fields) == {"subscription_status", "channels"}
    assert fields["subscription_status"]["selected"] == "current"
    assert set(fields["channels"]["selected"]) == {"phone"}


async def test_section_key_falls_back_to_id_when_absent() -> None:
    sid = uuid4()
    section = TemplateSection(id=sid, name="X", field_type="choice", options=SUBSCRIPTION_OPTIONS)
    out = await _stage().process(_ctx((section,)), StageInput(text="клієнт підписаний"))
    assert str(sid) in out.metadata["field_extraction.fields"]


# ── determinism ─────────────────────────────────────────────────────


async def test_metadata_is_json_native_and_byte_stable() -> None:
    ctx = _ctx((_subscription_section(), _channels_section()))
    input = StageInput(text="клієнт підписаний, зв'язок через телефон")
    a = await _stage().process(ctx, input)
    b = await _stage().process(ctx, input)
    assert json.dumps(a.metadata, sort_keys=True) == json.dumps(b.metadata, sort_keys=True)


async def test_field_order_is_section_order_independent() -> None:
    subscription, channels = _subscription_section(), _channels_section()
    text = "клієнт підписаний, зв'язок через телефон"
    forward = await _stage().process(_ctx((subscription, channels)), StageInput(text=text))
    backward = await _stage().process(_ctx((channels, subscription)), StageInput(text=text))
    assert json.dumps(forward.metadata, sort_keys=True) == json.dumps(
        backward.metadata, sort_keys=True
    )
    assert list(forward.metadata["field_extraction.fields"]) == [
        "channels",
        "subscription_status",
    ]


async def test_confidence_is_rounded_not_raw_float() -> None:
    """Unrounded floats would differ in the last bits across platforms
    and break byte-equal replay."""
    out = await _stage().process(
        _ctx((_subscription_section(),)), StageInput(text="клієнт підписани")
    )
    value = out.metadata["field_extraction.fields"]["subscription_status"]["confidence"]
    assert value == round(value, 6)


# ── typed construction, no raw dicts ────────────────────────────────


async def test_emitted_metadata_validates_against_the_typed_contract() -> None:
    from note_models import validate_field_metadata

    ctx = _ctx((_subscription_section(), _channels_section()))
    out = await _stage().process(
        ctx, StageInput(text="клієнт підписаний, зв'язок через телефон та імейл")
    )
    fields = out.metadata["field_extraction.fields"]
    validate_field_metadata("choice", fields["subscription_status"])
    validate_field_metadata("multi_choice", fields["channels"])


# ── orchestrator-level contracts ────────────────────────────────────


class _RecordingStage:
    """Stands in for ConfidenceStage: records the text it was handed."""

    name = "recorder"
    runs_on_partials = True

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def process(self, ctx: ProcessingContext, input: StageInput) -> StageOutput:
        self.seen.append(input.text)
        return StageOutput(text=input.text, words=input.words)


async def test_partials_skip_the_stage() -> None:
    orch = Orchestrator(stages=[_stage()])
    out = await orch.run(
        _ctx((_subscription_section(),), is_partial=True), StageInput(text="клієнт підписаний")
    )
    assert out.metadata.get("field_extraction.skipped_partial") is True
    assert "field_extraction.fields" not in out.metadata


async def test_finals_run_the_stage() -> None:
    orch = Orchestrator(stages=[_stage()])
    out = await orch.run(_ctx((_subscription_section(),)), StageInput(text="клієнт підписаний"))
    assert "field_extraction.fields" in out.metadata


async def test_next_stage_receives_unmodified_text() -> None:
    recorder = _RecordingStage()
    orch = Orchestrator(stages=[_stage(), recorder])
    text = "клієнт не підписаний, зв'язок через телефон"
    await orch.run(_ctx((_subscription_section(), _channels_section())), StageInput(text=text))
    assert recorder.seen == [text]


async def test_double_run_through_orchestrator_is_byte_equal() -> None:
    """The determinism contract, end to end."""
    from nlp_service.pipeline.orchestrator import _encode_for_cache

    orch = Orchestrator(stages=[_stage()])
    ctx = _ctx((_subscription_section(), _channels_section()))
    input = StageInput(text="скасував підписку, зв'язок через імейл")
    first = await orch.run(ctx, input)
    second = await orch.run(ctx, input)
    assert _encode_for_cache(first) == _encode_for_cache(second)


# ── idempotence key ─────────────────────────────────────────────────
# These are synchronous; the module-level asyncio mark is stripped from
# them below so pytest-asyncio does not warn.


async def test_option_sets_participate_in_the_idempotence_key() -> None:
    """Same text + different options must not share a cache entry."""
    sid = uuid4()
    a = TemplateSection(
        id=sid,
        name="X",
        section_key="x",
        field_type="choice",
        options=(
            ChoiceOption(value="a", label="перше"),
            ChoiceOption(value="b", label="друге"),
        ),
    )
    b = TemplateSection(
        id=sid,
        name="X",
        section_key="x",
        field_type="choice",
        options=(
            ChoiceOption(value="a", label="перше"),
            ChoiceOption(value="c", label="третє"),
        ),
    )
    input = StageInput(text="перше")
    assert idempotence_key(_ctx((a,)), input) != idempotence_key(_ctx((b,)), input)


async def test_field_type_participates_in_the_idempotence_key() -> None:
    sid = uuid4()
    opts = (ChoiceOption(value="a", label="перше"), ChoiceOption(value="b", label="друге"))
    a = TemplateSection(id=sid, name="X", section_key="x", field_type="choice", options=opts)
    b = TemplateSection(id=sid, name="X", section_key="x", field_type="multi_choice", options=opts)
    input = StageInput(text="перше")
    assert idempotence_key(_ctx((a,)), input) != idempotence_key(_ctx((b,)), input)


async def test_legacy_sections_keep_a_stable_key_shape() -> None:
    """A caller sending only id/name/aliases still produces a key."""
    legacy = TemplateSection(id=uuid4(), name="Нотатки", aliases=("нотатки",))
    assert idempotence_key(_ctx((legacy,)), StageInput(text="текст"))


# ── "no raw metadata dicts" gate ────────────────────────────────────


async def test_nlp_service_never_hand_builds_field_metadata() -> None:
    """All emission must go through note_models' typed constructors."""
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "nlp_service"
    offenders: list[str] = []
    for path in src.rglob("*.py"):
        text = path.read_text("utf-8")
        # A raw dict literal keyed by the contract's field names would be
        # the bypass; the typed models are the only sanctioned producer.
        if '"source": "extracted"' in text or "'source': 'extracted'" in text:
            offenders.append(str(path.relative_to(src)))
    assert offenders == [], f"raw metadata dict assembled in {offenders}"


async def test_extractors_import_the_typed_constructors() -> None:
    from pathlib import Path

    choice_src = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "nlp_service"
        / "stages"
        / "extractors"
        / "choice.py"
    ).read_text("utf-8")
    assert "from note_models import ChoiceMeta, MultiChoiceMeta" in choice_src
