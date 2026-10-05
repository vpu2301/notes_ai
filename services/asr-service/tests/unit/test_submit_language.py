"""Every language a client offers is accepted (``LANGUAGE_REQUEST_PATTERN`` from ``asr_models``)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from asr_models import LANGUAGE_REQUEST_PATTERN, JobEnqueuePayload

from .test_submit_rejections import rig  # noqa: F401 — fixture

_AUDIO = {"audio": ("a.wav", b"RIFF0000WAVE" + b"\x00" * 64, "audio/wav")}


def _queued(rig: SimpleNamespace) -> list[bytes]:  # noqa: F811
    sent: list[bytes] = []

    async def _send(**kwargs: Any) -> None:
        sent.append(kwargs["value"])

    rig.producer.send = _send
    return sent


@pytest.mark.parametrize("language", ["auto", "uk", "en", "de"])
def test_language_every_client_offers_is_accepted(
    rig: SimpleNamespace,  # noqa: F811
    language: str,
) -> None:
    sent = _queued(rig)
    resp = rig.client.post("/asr/jobs", files=_AUDIO, data={"language": language})
    assert resp.status_code == 202, resp.text
    assert JobEnqueuePayload.model_validate_json(sent[0]).language == language


@pytest.mark.parametrize("language", ["fr", "DE", "de-DE", ""])
def test_language_outside_the_shared_pattern_is_refused(
    rig: SimpleNamespace,  # noqa: F811
    language: str,
) -> None:
    resp = rig.client.post("/asr/jobs", files=_AUDIO, data={"language": language})
    assert resp.status_code == 422, resp.text
    assert rig.producer.sent == 0


def test_route_uses_the_shared_pattern() -> None:
    from asr_service.routers import jobs

    source = Path(jobs.__file__).read_text(encoding="utf-8")
    assert 'Form(pattern="^(auto' not in source
    assert "de" in LANGUAGE_REQUEST_PATTERN
