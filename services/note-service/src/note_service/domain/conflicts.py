"""Conflict exception raised by the domain layer + routed to HTTP 409."""

from __future__ import annotations


class OptimisticLockMismatchError(Exception):
    def __init__(self, *, current_version: int, expected_version: int) -> None:
        self.current_version = current_version
        self.expected_version = expected_version
        super().__init__(f"expected version {expected_version}, current is {current_version}")
