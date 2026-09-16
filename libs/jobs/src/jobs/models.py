"""Row shapes and the closed status set for the ``jobs`` table (migration 0022)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_ON_MODEL = "waiting_on_model"  # parked while a scale-to-zero backend wakes up
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD = "dead"


TERMINAL = frozenset({JobStatus.COMPLETE, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.DEAD})


@dataclass(slots=True)
class Job:
    id: UUID
    tenant_id: UUID
    kind: str
    payload: dict[str, Any]
    status: JobStatus
    attempts: int
    max_attempts: int
    run_at: datetime
    created_at: datetime
    priority: int = 0
    leased_by: str | None = None
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    waiting_backend: str | None = None
    waiting_since: datetime | None = None
    error_kind: str | None = None
    last_error: str = ""
    result: dict[str, Any] | None = None
    idempotency_key: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Any) -> Job:
        d = dict(row)
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        kwargs = {k: d[k] for k in known if k in d}
        kwargs["status"] = JobStatus(d["status"])
        for js in ("payload", "result"):
            if isinstance(kwargs.get(js), str):
                import json

                kwargs[js] = json.loads(kwargs[js])
        if kwargs.get("payload") is None:
            kwargs["payload"] = {}
        extra = {k: v for k, v in d.items() if k not in known and k != "updated_at"}
        return cls(extra=extra, **kwargs)

    def log_fields(self) -> dict[str, Any]:
        return {
            "job_id": str(self.id),
            "workspace_id": str(self.tenant_id),
            "kind": self.kind,
            "attempts": self.attempts,
            "status": str(self.status),
        }
