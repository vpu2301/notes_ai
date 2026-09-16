"""One refusal type for the native auth surface.

Every service in this package needs to say "no, and here is the machine
code the client should branch on". Three near-identical exception classes
would mean three ``except`` arms in every router and three chances for
one of them to forget the ``Retry-After`` header, so there is one.

The HTTP status travels with the error because the status *is* part of
the contract in ``docs/api/error-codes.md`` — deciding it in the router
would put half the decision table in a second place.
"""

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
