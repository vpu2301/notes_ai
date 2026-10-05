"""One refusal type for the native auth surface; the HTTP status travels with the error (docs/api/error-codes.md)."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        status_code: int,
        *,
        detail: str,
        retry_after: int | None = None,
        extras: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after
        self.extras = extras or {}
