"""Versioned prompt/model profiles: what a workspace may change about how its notes
are written, and what it may not.

The effective instruction a stage sends is four things in a fixed order: the stage
task text (bundled, or a saved version's), the platform contract code appends (the
noise and source-language rules, the data guard), the delimited source data, and
nothing else. A profile replaces only the task text; it can never remove the
contract. Text a person writes is data with ``{{variable}}`` slots from a closed
list, never template code.

A saved version is immutable (the table refuses UPDATE); the active pointer picks a
whole version, never a mix of prompt and model settings. Pure, apart from reading
the registry it is handed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from .meeting_doc import prompts

STAGES: Final[tuple[str, ...]] = prompts.EDITABLE_STAGES
# The registry has no per-stage operations: every stage is a call of the notes writer.
# Stated, not implied — a stage binding picks a backend for the `chat` kind only.
STAGE_OPERATION: Final[dict[str, str]] = dict.fromkeys(STAGES, "chat")
MAX_STAGE_CHARS: Final = 20_000
LENGTHS: Final[tuple[str, ...]] = ("short", "standard", "detailed")
# Output languages a stage has bundled instructions for; "auto" resolves per recording.
OUTPUT_LANGUAGES: Final[tuple[str, ...]] = ("auto", *prompts.BUNDLED_LANGUAGES)
# The variables a stage text may use (05-prompt-instructions.md), filled in by code.
VARIABLES: Final[frozenset[str]] = prompts.TASK_VARIABLES
LANGUAGE_NAMES: Final[dict[str, str]] = prompts.LANGUAGE_NAMES
_SLOT: Final = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
_BRACE: Final = re.compile(r"\{\{|\}\}")

# What a saved version was written against. A version from another contract or
# algorithm cannot be activated or rolled back to: it would run on code it never saw.
CONTRACT_VERSION: Final = prompts.PROMPT_VERSION
ALGORITHM_VERSION: Final = "2026-10-18.fidelity"
COMPATIBLE_CONTRACTS: Final[frozenset[str]] = frozenset({CONTRACT_VERSION})
COMPATIBLE_ALGORITHMS: Final[frozenset[str]] = frozenset({ALGORITHM_VERSION})


def schema_version() -> str:
    """The prompt tables and schemas the contract is made of (``prompts.fingerprint``)."""
    return prompts.fingerprint()[:16]


# ── Configuration ───────────────────────────────────────────────────


class StageParams(BaseModel):
    """Per-stage call settings; only what the bound backend supports is accepted."""

    model_config = ConfigDict(extra="forbid")

    temperature: float | None = None
    max_output_tokens: int | None = None
    timeout_s: float | None = None
    # Accepted keys with no adapter support: always refused with the reason, never dropped.
    reasoning: str | None = None
    seed: int | None = None


class ProfileConfig(BaseModel):
    """One complete configuration. ``stages[stage] = None`` keeps the bundled text;
    ``models[stage] = None`` keeps the workspace's routing."""

    model_config = ConfigDict(extra="forbid")

    stages: dict[str, str | None] = Field(default_factory=dict)
    models: dict[str, str | None] = Field(default_factory=dict)
    params: dict[str, StageParams] = Field(default_factory=dict)
    output_language: str = "auto"
    length: Literal["short", "standard", "detailed"] = "standard"


BUNDLED: Final = ProfileConfig()


@dataclass(frozen=True, slots=True)
class Problem:
    """One reason a draft cannot be saved: where, a closed code, and words for the admin."""

    field: str
    code: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "detail": self.detail}


# ── Model capabilities ──────────────────────────────────────────────

# Adapters that take per-call temperature and output tokens (libs/models).
_CALL_PARAM_KINDS: Final[frozenset[str]] = frozenset({"openai_compat", "anthropic"})
MIN_OUTPUT_TOKENS: Final = 256
MAX_OUTPUT_TOKENS: Final = 8_192
MIN_TIMEOUT_S: Final = 10.0


@dataclass(frozen=True, slots=True)
class Capability:
    """A registered chat backend this workspace may bind, with the parameters its
    adapter supports (bounds) and the ones it does not (reason)."""

    backend: str
    model_id: str
    processor: str | None
    region: str | None
    acknowledged: bool
    small_model: bool
    context_window: int
    supported: dict[str, dict[str, float]] = field(default_factory=dict)
    unsupported: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "model_id": self.model_id,
            "processor": self.processor,
            "region": self.region,
            "acknowledged": self.acknowledged,
            "small_model": self.small_model,
            "context_window": self.context_window,
            "stages": list(STAGES),
            "supported": self.supported,
            "unsupported": self.unsupported,
        }


def capability_of(resolved: Any, *, acknowledged: frozenset[tuple[str, str]]) -> Capability:
    """One registry backend as a capability; bounds come from its own metadata."""
    caps = resolved.caps
    processor = resolved.processor
    supported: dict[str, dict[str, float]] = {}
    if resolved.kind in _CALL_PARAM_KINDS:
        supported["temperature"] = {"min": 0.0, "max": 1.0}
        supported["max_output_tokens"] = {
            "min": MIN_OUTPUT_TOKENS,
            "max": max(MIN_OUTPUT_TOKENS, min(MAX_OUTPUT_TOKENS, caps.context_window // 4)),
        }
    supported["timeout_s"] = {"min": MIN_TIMEOUT_S, "max": float(caps.timeout_seconds)}
    return Capability(
        backend=resolved.name,
        model_id=resolved.model_id,
        processor=processor.name if processor else None,
        region=processor.region if processor else None,
        acknowledged=processor is None
        or (processor.name.strip().casefold(), processor.region.strip().casefold()) in acknowledged,
        small_model=bool(caps.small_model),
        context_window=int(caps.context_window),
        supported=supported,
        unsupported={
            "reasoning": "this backend's adapter sends no reasoning setting",
            "seed": "this backend's adapter sends no seed; a seed would not make output repeatable",
        },
    )


def capabilities(registry: Any, *, acknowledged: frozenset[tuple[str, str]]) -> list[Capability]:
    """Registered chat backends this environment allows (``Registry.backend`` enforces
    env, enabled and credentials); a backend that refuses to resolve is not offered."""
    out: list[Capability] = []
    for name in registry.backend_names:
        try:
            resolved = registry.backend(name, expect_kind="chat")
        except Exception:  # noqa: BLE001 — not usable here: not offered
            continue
        if resolved.kind not in _CALL_PARAM_KINDS:
            continue
        out.append(capability_of(resolved, acknowledged=acknowledged))
    return out


# ── Validation ──────────────────────────────────────────────────────


def variables_in(text: str) -> list[str]:
    return [m.group(1) for m in _SLOT.finditer(text)]


def validate(
    config: ProfileConfig, available: list[Capability], *, context_tokens: int | None = None
) -> list[Problem]:
    """Every reason this configuration cannot be saved. Nothing is clamped or dropped:
    an unsupported or out-of-range setting is a problem, named."""
    problems: list[Problem] = []
    by_name = {c.backend: c for c in available}
    for stage in config.stages:
        if stage not in STAGES:
            problems.append(Problem(f"stages.{stage}", "unknown_stage", f"stages are {STAGES}"))
    for stage, text in config.stages.items():
        if text is None or stage not in STAGES:
            continue
        where = f"stages.{stage}"
        if not text.strip():
            problems.append(Problem(where, "empty", "empty text; use null for the bundled text"))
        if len(text) > MAX_STAGE_CHARS:
            problems.append(
                Problem(where, "too_long", f"{len(text)} characters; at most {MAX_STAGE_CHARS}")
            )
        for name in variables_in(text):
            if name not in VARIABLES:
                problems.append(
                    Problem(
                        where,
                        "unknown_variable",
                        f"{{{{{name}}}}} is not one of {sorted(VARIABLES)}",
                    )
                )
        if len(_BRACE.findall(text)) != 2 * len(variables_in(text)):
            problems.append(Problem(where, "unbalanced_braces", "a {{ or }} without its pair"))
        if context_tokens is not None and len(text) // 3 > context_tokens // 4:
            problems.append(
                Problem(
                    where, "context_budget", "the instructions leave too little room for the data"
                )
            )
    for stage in [*config.models, *config.params]:
        if stage not in STAGES:
            problems.append(Problem(f"models.{stage}", "unknown_stage", f"stages are {STAGES}"))
    for stage in STAGES:
        name = config.models.get(stage)
        capability = by_name.get(name) if name else None
        if name and capability is None:
            problems.append(
                Problem(f"models.{stage}", "model_unavailable", f"{name!r} is not offered here")
            )
        params = config.params.get(stage)
        if params is None:
            continue
        for key, value in params.model_dump(exclude_none=True).items():
            where = f"params.{stage}.{key}"
            if capability is None and name is None:
                # No binding: the workspace's routed backend decides; bounds of any offered one.
                capability = next(iter(available), None)
            if capability is None:
                problems.append(Problem(where, "model_unavailable", "no backend to check against"))
                continue
            if key in capability.unsupported:
                problems.append(Problem(where, "unsupported", capability.unsupported[key]))
                continue
            bounds = capability.supported.get(key)
            if bounds is None:
                problems.append(Problem(where, "unsupported", f"{capability.backend} has no {key}"))
            elif not bounds["min"] <= float(value) <= bounds["max"]:
                problems.append(
                    Problem(where, "out_of_range", f"{key} must be {bounds['min']}–{bounds['max']}")
                )
    if config.output_language not in OUTPUT_LANGUAGES:
        problems.append(
            Problem("output_language", "unsupported_language", f"one of {OUTPUT_LANGUAGES}")
        )
    return problems


# ── Effective instructions ──────────────────────────────────────────


def render(text: str, *, output_language: str, length_mode: str = "standard") -> str:
    """The allowlisted slots filled in; nothing else is evaluated (validated before)."""
    return prompts.render_slots(text, output_language=output_language, length_mode=length_mode)


def bundled_text(stage: str, language: str = "en") -> str:
    """The editable task text a stage ships with — the English canonical resource
    (``prompt_templates/<stage>.md``), whatever the output language. Never the
    builder's rules or the contract: those are added by code under any text."""
    del language  # one canonical text; the output language is a variable, not a variant
    return prompts._resource(stage)


def stage_overrides(config: ProfileConfig) -> dict[str, str]:
    """``{stage: unrendered text}`` for the stages this configuration replaces; the
    pipeline renders them with the generation's language and length."""
    return {
        stage: text for stage, text in config.stages.items() if text is not None and stage in STAGES
    }


def effective_instructions(
    config: ProfileConfig, stage: str, *, language: str, small: bool = False
) -> str:
    """The full system text a stage sends for ``language``: what the preview shows and
    what a generation runs — the same functions."""
    task = prompts.task(language, config.length, overrides=stage_overrides(config))
    if stage == "extraction":
        return prompts.extract_system(language, noise=not small, multilingual=True, task=task)
    if stage == "composition":
        return prompts.summary_system(language, task=task)
    return prompts.meaning_check_system(language, task=task)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(config: ProfileConfig) -> str:
    """Identity of a configuration with the contract it was written against."""
    blob = json.dumps(
        {
            "config": config.model_dump(mode="json"),
            "contract": CONTRACT_VERSION,
            "schema": schema_version(),
            "algorithm": ALGORITHM_VERSION,
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return _sha(blob)


def prompt_hashes(config: ProfileConfig, *, language: str) -> dict[str, str]:
    """sha256 of every stage's effective system text for ``language``."""
    return {
        stage: _sha(effective_instructions(config, stage, language=language)) for stage in STAGES
    }


def compatible(*, contract_version: str, schema: str, algorithm_version: str) -> str | None:
    """None when this code can run a version written against these; else why not."""
    if contract_version not in COMPATIBLE_CONTRACTS:
        return f"written for prompt contract {contract_version}; this deployment runs {CONTRACT_VERSION}"
    if algorithm_version not in COMPATIBLE_ALGORITHMS:
        return (
            f"written for algorithm {algorithm_version}; this deployment runs {ALGORITHM_VERSION}"
        )
    if schema != schema_version():
        return "written against other prompt schemas; save it again as a new version"
    return None


# ── The snapshot a generation is pinned to ──────────────────────────


def snapshot(
    config: ProfileConfig,
    *,
    version_id: str | None,
    version_hash: str | None,
    multilingual: bool,
    fidelity: bool,
    language_hint: str,
    models: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Everything a queued generation runs with, fixed at enqueue: the version, its
    hashes, the code's contract/schema/algorithm, the flags, the language policy, the
    length and the backend each stage was resolved to. Counts and names, no transcript.
    ``language_hint`` is the language prompt hashes are computed for."""
    return {
        "profile_version_id": version_id,
        "content_hash": version_hash or content_hash(config),
        "contract_version": CONTRACT_VERSION,
        "schema_version": schema_version(),
        "algorithm_version": ALGORITHM_VERSION,
        "prompt_version": prompts.effective_version(multilingual=multilingual, fidelity=fidelity),
        "multilingual": multilingual,
        "fidelity": fidelity,
        "output_language": config.output_language,
        "length": config.length,
        "stages": {s: config.stages.get(s) is not None for s in STAGES},
        "prompt_hashes": prompt_hashes(config, language=language_hint),
        "config": config.model_dump(mode="json"),
        "models": models,
    }
