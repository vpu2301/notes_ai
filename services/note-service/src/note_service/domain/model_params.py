"""The model parameters a workspace may set by hand (Sprint N0), and the writing style.

Only what the engine reads is offered, each field bounded by the engine's own sanity
limits and, where the backend declares one, capped by the backend (``effective``). A
field left unset (``None``) means "the engine's own choice" — the default is today's
behaviour exactly. Extraction, verification, classification, title and entity calls
are not governed by any of this: they stay at temperature 0.0.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

STYLES: Final = ("business", "formal", "informal", "academic")
WritingStyle = Literal["business", "formal", "informal", "academic"]
Retries = Literal["off", "standard", "thorough"]

DEFAULT_CONCURRENCY: Final = 4
DEFAULT_FACTS_PER_WINDOW: Final = 24
DEFAULT_ASK_TEMPERATURE: Final = 0.2
DEFAULT_ASK_MAX_TOKENS: Final = 700


class ModelParams(BaseModel):
    """One workspace's parameters. ``None`` = the engine's own value (backend-derived)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    temperature: float = Field(default=0.0, ge=0.0, le=0.7)
    context_window_tokens: int | None = Field(default=None, ge=8_192, le=262_144)
    max_output_tokens: int | None = Field(default=None, ge=512, le=4_096)
    max_concurrency: int = Field(default=DEFAULT_CONCURRENCY, ge=1, le=8)
    facts_per_window: int = Field(default=DEFAULT_FACTS_PER_WINDOW, ge=8, le=24)
    retries: Retries = "standard"
    ask_temperature: float = Field(default=DEFAULT_ASK_TEMPERATURE, ge=0.0, le=1.0)
    ask_max_tokens: int = Field(default=DEFAULT_ASK_MAX_TOKENS, ge=200, le=2_000)

    @field_validator("temperature", "ask_temperature")
    @classmethod
    def _tenths(cls, value: float) -> float:
        if abs(round(value * 10) - value * 10) > 1e-6:
            raise ValueError("must be a multiple of 0.1")
        return round(value, 1)


DEFAULT: Final = ModelParams()


def from_stored(
    raw: dict[str, Any] | None, *, tenant_id: Any = None, version: int = 0
) -> ModelParams:
    """The stored object, or the defaults when it does not validate (an older or newer
    schema): logged without values, never raised — a note must still be written."""
    try:
        return ModelParams.model_validate(raw or {})
    except ValidationError:
        logger.warning("model_params.invalid", extra={"tenant": str(tenant_id), "version": version})
        return DEFAULT


def is_valid(raw: dict[str, Any] | None) -> bool:
    try:
        ModelParams.model_validate(raw or {})
    except ValidationError:
        return False
    return True


def effective(
    params: ModelParams, *, context_window: int | None, max_concurrency: int | None
) -> ModelParams:
    """``params`` with the backend's caps applied: never more context than the backend
    takes, never more parallel calls than its semaphore allows."""
    update: dict[str, Any] = {}
    if (
        context_window
        and params.context_window_tokens
        and params.context_window_tokens > context_window
    ):
        update["context_window_tokens"] = int(context_window)
    if max_concurrency and params.max_concurrency > max_concurrency:
        update["max_concurrency"] = int(max_concurrency)
    return params.model_copy(update=update) if update else params


def canonical_hash(params: ModelParams, style: str) -> str:
    """The pointer a generation records: sha256 of the canonical parameters and style."""
    blob = json.dumps({"params": params.model_dump(mode="json"), "style": style}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def limits(*, context_window: int | None, max_concurrency: int | None) -> dict[str, dict[str, Any]]:
    """Per field: the range, the step, the recommended value, and the backend's cap."""

    def num(name: str, **extra: Any) -> dict[str, Any]:
        info = ModelParams.model_fields[name]
        lo = next(m.ge for m in info.metadata if hasattr(m, "ge"))
        hi = next(m.le for m in info.metadata if hasattr(m, "le"))
        return {"min": lo, "max": hi, "default": info.default, **extra}

    out = {
        "temperature": num("temperature", step=0.1),
        "context_window_tokens": num("context_window_tokens", default=context_window),
        "max_output_tokens": num("max_output_tokens"),
        "max_concurrency": num("max_concurrency"),
        "facts_per_window": num("facts_per_window"),
        "retries": {"options": ["off", "standard", "thorough"], "default": "standard"},
        "ask_temperature": num("ask_temperature", step=0.1),
        "ask_max_tokens": num("ask_max_tokens"),
    }
    if context_window:
        out["context_window_tokens"] |= {"cap": int(context_window), "cap_source": "backend"}
    if max_concurrency:
        out["max_concurrency"] |= {"cap": int(max_concurrency), "cap_source": "backend"}
    return out


def changed_fields(before: ModelParams, after: ModelParams) -> list[str]:
    a, b = before.model_dump(), after.model_dump()
    return sorted(k for k in a if a[k] != b[k])


def retry_budget(policy: str, standard_s: float | None) -> float | None:
    """``off`` → no second read; ``thorough`` → twice the standard budget."""
    if policy == "off":
        return 0.0
    if policy == "thorough" and standard_s is not None:
        return standard_s * 2
    return standard_s
