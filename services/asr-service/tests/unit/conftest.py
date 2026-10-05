"""Shared unit-test setup for asr-service."""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _no_spelling_overlay(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fakes know nothing of ``transcript_corrections``: the overlay reads as "no rows"
    unless a test asks for it with ``@pytest.mark.overlay``."""
    if request.node.get_closest_marker("overlay"):
        return
    from asr_service.domain import corrections

    async def no_state(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr(corrections, "job_state", no_state)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "overlay: run the TQ3 spelling overlay against the test's fake DB"
    )
