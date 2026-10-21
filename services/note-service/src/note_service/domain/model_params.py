"""The model parameters a workspace may set by hand (Sprint N0, trimmed by P2 to what
the writer reads): the writing temperature, the output budget per call, the parallel
calls, and the two "Ask this note" settings. Each is bounded by a sanity limit and,
where the backend declares one, capped by the backend (``effective``). A field left
unset (``None``) means the model's own value.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY: Final = 4
DEFAULT_ASK_TEMPERATURE: Final = 0.2
DEFAULT_ASK_MAX_TOKENS: Final = 700


class ModelParams(BaseModel):
    """One workspace's parameters. ``None`` = the engine's own value (backend-derived)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    temperature: float = Field(default=0.0, ge=0.0, le=0.7)
    max_output_tokens: int | None = Field(default=None, ge=512, le=8_192)
    max_concurrency: int = Field(default=DEFAULT_CONCURRENCY, ge=1, le=8)
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
    schema): logged without values, never raised — a note must still be written. Fields
    the old path owned (P2 removed them) are ignored, not refused."""
    try:
        return ModelParams.model_validate(_known(raw))
    except ValidationError:
        logger.warning("model_params.invalid", extra={"tenant": str(tenant_id), "version": version})
        return DEFAULT


def _known(raw: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (raw or {}).items() if k in ModelParams.model_fields}


def is_valid(raw: dict[str, Any] | None) -> bool:
    try:
        ModelParams.model_validate(_known(raw))
    except ValidationError:
        return False
    return True


def effective(params: ModelParams, *, max_concurrency: int | None) -> ModelParams:
    """``params`` with the backend's cap applied: never more parallel calls than its
    semaphore allows."""
    if max_concurrency and params.max_concurrency > max_concurrency:
        return params.model_copy(update={"max_concurrency": int(max_concurrency)})
    return params


def canonical_hash(params: ModelParams) -> str:
    """The pointer a generation records: sha256 of the canonical parameters."""
    blob = json.dumps({"params": params.model_dump(mode="json")}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def limits(*, max_concurrency: int | None) -> dict[str, dict[str, Any]]:
    """Per field: the range, the step, the recommended value, and the backend's cap."""

    def num(name: str, **extra: Any) -> dict[str, Any]:
        info = ModelParams.model_fields[name]
        lo = next(m.ge for m in info.metadata if hasattr(m, "ge"))
        hi = next(m.le for m in info.metadata if hasattr(m, "le"))
        return {"min": lo, "max": hi, "default": info.default, **extra}

    out = {
        "temperature": num("temperature", step=0.1),
        "max_output_tokens": num("max_output_tokens"),
        "max_concurrency": num("max_concurrency"),
        "ask_temperature": num("ask_temperature", step=0.1),
        "ask_max_tokens": num("ask_max_tokens"),
    }
    if max_concurrency:
        out["max_concurrency"] |= {"cap": int(max_concurrency), "cap_source": "backend"}
    return out


def changed_fields(before: ModelParams, after: ModelParams) -> list[str]:
    a, b = before.model_dump(), after.model_dump()
    return sorted(k for k in a if a[k] != b[k])
