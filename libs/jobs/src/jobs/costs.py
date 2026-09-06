"""Cost estimate per model call from ``config/model_costs.yaml`` (DEP-S1-06).

Rates are first estimates (list price ÷ measured throughput); DEP-S6
replaces them. A backend without a rate costs 0 and is flagged so the
rollup can show "unpriced" rather than "free".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from models import UsageRecord


class CostTable:
    def __init__(self, rates: dict[str, dict[str, Any]], *, currency: str = "EUR") -> None:
        self._rates = rates
        self.currency = currency

    @classmethod
    def load(cls, path: str | Path) -> CostTable:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        backends = raw.get("backends") or {}
        if not isinstance(backends, dict):
            raise ValueError(f"{path}: backends must be a mapping")
        return cls(
            {str(k): dict(v or {}) for k, v in backends.items()},
            currency=str(raw.get("currency", "EUR")),
        )

    @classmethod
    def empty(cls) -> CostTable:
        return cls({})

    def is_priced(self, backend: str) -> bool:
        rate = self._rates.get(backend) or {}
        return any(v is not None for v in rate.values())

    def estimate_cents(self, record: UsageRecord) -> float:
        rate = self._rates.get(record.backend) or {}
        cents = 0.0
        cents += (record.input_tokens / 1000.0) * float(rate.get("input_cents_per_1k") or 0)
        cents += (record.output_tokens / 1000.0) * float(rate.get("output_cents_per_1k") or 0)
        cents += (record.audio_seconds / 60.0) * float(rate.get("audio_cents_per_minute") or 0)
        if record.attempts > 1 and rate.get("cold_start_cents"):
            # A call that needed retries most likely paid for a wake-up.
            cents += float(rate["cold_start_cents"])
        return round(cents, 4)
