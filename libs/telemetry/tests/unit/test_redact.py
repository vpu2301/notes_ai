from __future__ import annotations

import pytest

from telemetry.redact import redact


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ({"api_key": "sk-1", "beam_size": 5}, {"beam_size": 5}),
        ({"password": "x", "Authorization": "Bearer y", "secret_ref": "s"}, {}),
        ({"transcript": "hello", "text": "hi", "prompt": "p", "content": "c"}, {}),
        ({"speaker_name": "Anna", "display_name": "Anna", "name": "n"}, {}),
        ({"db_app_role_dsn": "postgresql://u:p@h/db"}, {}),
        ({"url": "https://user:pass@host/x"}, {"url": "https://host/x"}),
        ({"model_path": "/Users/anna/models/w"}, {"model_path": "/Users/<user>/models/w"}),
        ({"long": "x" * 257}, {"long": None}),
        ({"ok": "x" * 256}, {"ok": "x" * 256}),
        ({"input_tokens": 10, "token_source": "provider", "model_name": "large-v3",
          "queue_name": "asr:jobs", "prompt_chars": 120}, {"input_tokens": 10,
          "token_source": "provider", "model_name": "large-v3", "queue_name": "asr:jobs",
          "prompt_chars": 120}),
        ({"nested": {"list": [{"token": "t", "n": 1}, "y" * 300], "keep": True}},
         {"nested": {"list": [{"n": 1}, None], "keep": True}}),
        ({"_reasons": {"x": "not_measured"}}, {"_reasons": {"x": "not_measured"}}),
    ],
)  # fmt: skip
def test_redact(given: dict[str, object], expected: dict[str, object]) -> None:
    assert redact(given) == expected


def test_no_transcript_string_survives() -> None:
    words = "Der Start im November bleibt das Ziel, sagte Anna Schmidt am Telefon"
    record = {"segments": [{"transcript": words}], "error": words * 10, "note_text": words}
    assert words not in repr(redact(record))
