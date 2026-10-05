"""The producer → consumer event envelope: one domain fact; the consumer decides who hears about it."""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import Category

EVENT_SCHEMA_VERSION: Final = "1"

# Scalars only: nested structures are the easy path to smuggling a note body into an email template.
_ALLOWED_PAYLOAD_TYPES: Final = (str, int, float, bool, type(None))
_MAX_PAYLOAD_KEYS: Final = 20
_MAX_PAYLOAD_VALUE_LEN: Final = 200


class NotificationEvent(BaseModel):
    """A domain fact worth telling someone about.

    ``extra="forbid"``: an unrecognised field means producer and consumer
    disagree about the contract, and silently dropping it would hide a
    real deploy-skew bug (ADR-0012 lineage).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Idempotency seed: a re-publish of the same fact MUST reuse it (the consumer's dedupe_key derives from it).
    event_id: UUID
    schema_version: str = EVENT_SCHEMA_VERSION

    tenant_id: UUID
    category: Category

    # None when a job acts as the system.
    actor_user_id: UUID | None = None

    resource_type: str = Field(min_length=1, max_length=64)
    resource_id: UUID
    resource_version_id: UUID | None = None

    occurred_at: datetime

    # Recipients the PRODUCER already knows; role-derived categories leave it empty for the consumer.
    recipient_hints: tuple[UUID, ...] = ()

    # Flat, scalar-only; pointers, never content or personal data.
    payload: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def _require_tz(cls, v: datetime) -> datetime:
        # A naive timestamp breaks quiet-hours and digest windowing across deploys.
        if v.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        return v

    @field_validator("payload")
    @classmethod
    def _check_payload(
        cls, v: dict[str, str | int | float | bool | None]
    ) -> dict[str, str | int | float | bool | None]:
        if len(v) > _MAX_PAYLOAD_KEYS:
            raise ValueError(f"payload has {len(v)} keys; max is {_MAX_PAYLOAD_KEYS}")
        for key, value in v.items():
            if not isinstance(value, _ALLOWED_PAYLOAD_TYPES):
                raise ValueError(
                    f"payload[{key!r}] is {type(value).__name__}; "
                    "only scalars are allowed (see the content boundary, ADR-0031)"
                )
            if isinstance(value, str) and len(value) > _MAX_PAYLOAD_VALUE_LEN:
                raise ValueError(
                    f"payload[{key!r}] is {len(value)} chars; "
                    f"max is {_MAX_PAYLOAD_VALUE_LEN} — payloads carry pointers, not content"
                )
        return v

    def dedupe_key(self, recipient_user_id: UUID) -> str:
        """Idempotency anchor for one materialised row (UNIQUE per tenant); a replay collapses onto the same row."""
        return f"{self.event_id}:{recipient_user_id}"
