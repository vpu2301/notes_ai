"""Prompt/model profiles (S3): a draft is validated before it is saved, nothing is
clamped or dropped silently, a person's text is data with closed slots, and the
effective instructions always keep the platform contract.
"""

from __future__ import annotations

import asyncio
from importlib import resources
from types import SimpleNamespace
from typing import Any

import pytest

from note_service.domain import prompt_profiles as profiles
from note_service.domain.meeting_doc import prompts
from note_service.domain.meeting_doc.stage_provider import Metered, StageProvider


def _cap(**over: Any) -> profiles.Capability:
    base: dict[str, Any] = {
        "backend": "mistral_eu",
        "model_id": "mistral-large-2512",
        "processor": "Mistral AI",
        "region": "EU",
        "acknowledged": True,
        "small_model": False,
        "context_window": 131_072,
        "supported": {
            "temperature": {"min": 0.0, "max": 1.0},
            "max_output_tokens": {"min": 256, "max": 8192},
            "timeout_s": {"min": 10.0, "max": 120.0},
        },
        "unsupported": {"reasoning": "no reasoning setting", "seed": "no seed"},
    }
    base.update(over)
    return profiles.Capability(**base)


def _codes(config: profiles.ProfileConfig, caps: list[profiles.Capability] | None = None) -> set:
    return {
        (p.field, p.code) for p in profiles.validate(config, caps if caps is not None else [_cap()])
    }


# ── Validation ──────────────────────────────────────────────────────


def test_the_bundled_profile_is_valid() -> None:
    assert profiles.validate(profiles.BUNDLED, [_cap()]) == []


def test_known_placeholders_pass_and_unknown_ones_block_saving() -> None:
    good = profiles.ProfileConfig(stages={"extraction": "List facts in {{ output_language }}."})
    assert _codes(good) == set()
    bad = profiles.ProfileConfig(
        stages={"extraction": "Use {{customer_secret}} and {{output_language}}."}
    )
    assert ("stages.extraction", "unknown_variable") in _codes(bad)


def test_a_stage_text_is_bounded_and_never_empty() -> None:
    long = profiles.ProfileConfig(stages={"composition": "x" * (profiles.MAX_STAGE_CHARS + 1)})
    assert ("stages.composition", "too_long") in _codes(long)
    empty = profiles.ProfileConfig(stages={"verification": "   "})
    assert ("stages.verification", "empty") in _codes(empty)
    assert ("stages.summary", "unknown_stage") in _codes(
        profiles.ProfileConfig(stages={"summary": "x"})
    )


def test_unbalanced_braces_are_an_error_not_template_code() -> None:
    config = profiles.ProfileConfig(stages={"extraction": "Use {{output_language} please"})
    assert ("stages.extraction", "unbalanced_braces") in _codes(config)


def test_unsupported_parameters_are_refused_with_the_reason_not_dropped() -> None:
    config = profiles.ProfileConfig(
        models={"extraction": "mistral_eu"},
        params={"extraction": profiles.StageParams(seed=7, reasoning="high", temperature=0.2)},
    )
    found = {(p.field, p.code): p.detail for p in profiles.validate(config, [_cap()])}
    assert ("params.extraction.seed", "unsupported") in found
    assert ("params.extraction.reasoning", "unsupported") in found
    assert ("params.extraction.temperature", "unsupported") not in found


def test_a_backend_without_temperature_is_never_sent_one() -> None:
    no_temp = _cap(backend="asr_like", supported={"timeout_s": {"min": 10.0, "max": 60.0}})
    config = profiles.ProfileConfig(
        models={"composition": "asr_like"},
        params={"composition": profiles.StageParams(temperature=0.3)},
    )
    assert ("params.composition.temperature", "unsupported") in _codes(config, [no_temp])


def test_out_of_range_is_an_error_not_a_clamp() -> None:
    config = profiles.ProfileConfig(
        models={"verification": "mistral_eu"},
        params={"verification": profiles.StageParams(temperature=1.7, max_output_tokens=50_000)},
    )
    codes = _codes(config)
    assert ("params.verification.temperature", "out_of_range") in codes
    assert ("params.verification.max_output_tokens", "out_of_range") in codes


def test_a_model_not_offered_here_is_unavailable() -> None:
    config = profiles.ProfileConfig(models={"extraction": "some_vendor"})
    assert ("models.extraction", "model_unavailable") in _codes(config)


def test_the_extra_fields_of_a_config_are_refused() -> None:
    with pytest.raises(ValueError):
        profiles.ProfileConfig.model_validate({"stages": {}, "endpoint_url": "https://x"})
    with pytest.raises(ValueError):
        profiles.StageParams.model_validate({"api_key": "k"})


# ── Rendering and the effective instructions ────────────────────────


def test_rendering_fills_only_known_slots_and_evaluates_nothing() -> None:
    text = "Write in {{output_language}}. {{ __import__('os') }}"
    out = profiles.render(text, output_language="de")
    assert out.startswith("Write in German.") and "__import__" in out


def test_an_override_replaces_only_the_stage_text_and_keeps_everything_under_it() -> None:
    config = profiles.ProfileConfig(stages={"extraction": "List the facts in {{output_language}}."})
    text = profiles.effective_instructions(config, "extraction", language="de")
    common = prompts.task("de").common
    assert text.startswith(common) and "List the facts in German." in text
    # The bundled extraction text is replaced, never added to.
    assert prompts.task("de").extraction not in text
    # The builder's rules, the multilingual noise and source-language rules, the guard stay.
    assert prompts._NOISE_RULE_MULTILINGUAL["de"].strip() in text
    assert prompts._SOURCE_LANGUAGE_RULE["de"] in text
    assert text.endswith(prompts.guard("de"))
    assert "andere Sprache, Transkriptionsartefakt" not in text


def test_without_an_override_the_bundled_texts_are_sent() -> None:
    task = prompts.task("en")
    assert profiles.effective_instructions(
        profiles.BUNDLED, "verification", language="en"
    ) == prompts.meaning_check_system("en", task=task)
    assert profiles.bundled_text("extraction") == prompts._resource("extraction")


def test_length_mode_is_a_slot_filled_by_code() -> None:
    task = prompts.task("uk", "detailed")
    assert "The requested detail level is detailed." in task.common
    assert "Write user-facing note text in Ukrainian." in task.common
    assert (
        profiles.validate(
            profiles.ProfileConfig(stages={"extraction": "Detail: {{length_mode}}."}), [_cap()]
        )
        == []
    )


def test_each_composition_call_gets_its_own_subsection() -> None:
    task = prompts.task("en")
    heading = task.composing("HEADING SUBTASK")
    assert "Name the topic, not just its most frequent person." in heading
    assert "Select the central question" not in heading
    summary = prompts.summary_system("en", task=task)
    assert "Select the central question" in summary and "Name the topic" not in summary
    assert "A list of unrelated facts is not a temporal sequence." in summary


def test_the_content_hash_names_the_configuration_and_its_contract() -> None:
    a = profiles.ProfileConfig(stages={"composition": "Short."})
    b = profiles.ProfileConfig(stages={"composition": "Short!"})
    assert profiles.content_hash(a) == profiles.content_hash(a.model_copy())
    assert profiles.content_hash(a) != profiles.content_hash(b)


def test_a_version_from_another_contract_cannot_be_activated() -> None:
    ok = profiles.compatible(
        contract_version=profiles.CONTRACT_VERSION,
        schema=profiles.schema_version(),
        algorithm_version=profiles.ALGORITHM_VERSION,
    )
    assert ok is None
    old = profiles.compatible(
        contract_version="2026-10-01.3",
        schema=profiles.schema_version(),
        algorithm_version=profiles.ALGORITHM_VERSION,
    )
    assert old is not None and "2026-10-01.3" in old


def test_the_snapshot_pins_hashes_flags_and_bindings() -> None:
    snap = profiles.snapshot(
        profiles.BUNDLED,
        version_id=None,
        version_hash=None,
        multilingual=True,
        fidelity=False,
        language_hint="de",
        models={s: {"routed": True} for s in profiles.STAGES},
    )
    assert snap["prompt_version"] == prompts.PROMPT_VERSION
    assert snap["fidelity"] is False and snap["length"] == "standard"
    # Fidelity off: no final check, deduplication or participant call is pinned.
    assert set(snap["prompt_hashes"]) == {
        "extraction", "context", "composition.topic", "composition.summary", "verification.meaning",
    }  # fmt: skip


# ── Capabilities from the registry ──────────────────────────────────


def _resolved(name: str, kind: str = "openai_compat", region: str = "EU") -> Any:
    return SimpleNamespace(
        name=name,
        kind=kind,
        model_id=f"{name}-model",
        processor=SimpleNamespace(name="Mistral AI", region=region),
        caps=SimpleNamespace(context_window=131_072, timeout_seconds=120, small_model=False),
    )


def test_capabilities_come_from_the_registry_and_its_acknowledgements() -> None:
    class Registry:
        backend_names = ["mistral_eu", "broken", "recorded"]

        def backend(self, name: str, *, expect_kind: str) -> Any:
            if name == "broken":
                raise RuntimeError("missing_env")
            return _resolved(name, kind="recorded" if name == "recorded" else "openai_compat")

    [cap] = profiles.capabilities(Registry(), acknowledged=frozenset({("mistral ai", "eu")}))
    assert cap.backend == "mistral_eu" and cap.acknowledged
    assert cap.supported["max_output_tokens"]["max"] == 8192
    assert "seed" in cap.unsupported
    [unagreed] = profiles.capabilities(Registry(), acknowledged=frozenset())
    assert not unagreed.acknowledged


# ── Bundled resources ───────────────────────────────────────────────


def test_every_guide_resource_and_builder_rule_is_bundled() -> None:
    folder = resources.files("note_service.domain.meeting_doc").joinpath("prompt_templates")
    for name in prompts.TASK_RESOURCES:
        assert folder.joinpath(f"{name}.md").read_text(encoding="utf-8").strip()
    for rules in ("extract_rules", "summary_rules"):
        for language in prompts.BUNDLED_LANGUAGES:
            assert folder.joinpath(f"{rules}.{language}.txt").read_text(encoding="utf-8").strip()


# ── A stage's settings on every call ────────────────────────────────


class _Inner:
    backend = "mistral_eu"
    model_id = "mistral-large-2512"
    small_model = False

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []

    async def complete(
        self,
        prompt: str,
        schema: Any = None,
        *,
        max_tokens: int,
        temperature: float = 0.0,
        system: str | None = None,
    ) -> Any:  # noqa: E501
        self.seen.append({"max_tokens": max_tokens, "temperature": temperature})
        return SimpleNamespace(input_tokens=100, output_tokens=20, latency_ms=5, text="{}")


def test_a_stage_provider_applies_its_settings_and_a_meter_counts_the_call() -> None:
    inner = _Inner()
    staged = Metered(
        StageProvider(inner, stage="composition", temperature=0.4, max_output_tokens=500),
        stage="composition",
    )
    asyncio.run(staged.complete("p", None, max_tokens=1200, temperature=0.0))
    assert inner.seen == [{"max_tokens": 500, "temperature": 0.4}]
    assert staged.calls == [
        {"stage": "composition", "backend": "mistral_eu", "model_id": "mistral-large-2512",
         "ok": True, "system_sha": None, "input_tokens": 100, "output_tokens": 20,
         "latency_ms": 5}
    ]  # fmt: skip
    # Unset settings leave the pipeline's own values; attributes pass through.
    plain = StageProvider(inner, stage="extraction")
    asyncio.run(plain.complete("p", None, max_tokens=300, temperature=0.0))
    assert inner.seen[-1] == {"max_tokens": 300, "temperature": 0.0}
    assert plain.small_model is False and plain.backend == "mistral_eu"


def test_a_stage_timeout_stops_the_call() -> None:
    class Slow(_Inner):
        async def complete(self, *a: Any, **k: Any) -> Any:
            await asyncio.sleep(1)

    with pytest.raises(TimeoutError):
        asyncio.run(
            StageProvider(Slow(), stage="extraction", timeout_s=0.01).complete("p", max_tokens=1)
        )


# ── A queued job keeps what it was queued with ──────────────────────


def test_a_queued_job_runs_its_pinned_configuration_after_settings_change() -> None:
    from note_service.jobs.generate_note import run_configuration

    queued_with = profiles.snapshot(
        profiles.ProfileConfig(stages={"composition": "Short, in {{output_language}}."}, length="short"),
        version_id="v1", version_hash="h", multilingual=True, fidelity=False, language_hint="de",
        models={s: {"routed": True} for s in profiles.STAGES},
    )  # fmt: skip
    # Since then an admin turned fidelity on and activated another version.
    deps_now = SimpleNamespace(multilingual_evidence=True, fidelity=True)
    pinned, multilingual, fidelity, config = run_configuration(
        SimpleNamespace(config_snapshot=queued_with), deps_now
    )
    assert (multilingual, fidelity) == (True, False)
    assert config.length == "short" and config.stages["composition"].startswith("Short")
    assert pinned["profile_version_id"] == "v1"
    # A row from before S3 runs as it always did.
    legacy = run_configuration(SimpleNamespace(config_snapshot=None), deps_now)
    assert legacy == ({}, True, True, profiles.BUNDLED)
