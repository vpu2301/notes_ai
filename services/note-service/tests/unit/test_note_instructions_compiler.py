"""N1 T4/T5 — the compiler: one call, one strict retry, failure → the empty profile;
post-conditions enforced by code; the text travels as data; the version is pinned."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from models import ProviderError
from note_service.domain import note_instructions as ni
from note_service.domain import note_instructions_compiler as nc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "instructions"
PRESETS = ("executive_brief", "client_ready_de", "engineering_standup")
HOSTILE = ("hostile_exfiltrate", "hostile_inject_fact", "hostile_delimiters")


@dataclass
class Scripted:
    """Answers each call from ``answers`` in order (a dict, a raw string or an exception)."""

    answers: list[Any]
    backend: str = "scripted"
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def complete(self, prompt: str, schema: Any = None, *, max_tokens: int,
                       temperature: float = 0.0, system: str | None = None) -> Any:  # fmt: skip
        self.calls.append((prompt, system or ""))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        return type("Answer", (), {"text": text})()


def _text(name: str) -> str:
    return ni.sanitize_text((FIXTURES / f"{name}.txt").read_text("utf-8"))


def _expected(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text("utf-8"))


def _compile(text: str, *answers: Any) -> tuple[nc.CompileResult, Scripted]:
    provider = Scripted(list(answers))
    return asyncio.run(nc.compile_text(text, provider=provider)), provider


@pytest.mark.parametrize("name", PRESETS + HOSTILE)
def test_fixtures_compile_to_their_expected_profiles(name: str) -> None:
    result, provider = _compile(_text(name), _expected(name))
    assert result.status == "compiled" and result.error_kind is None
    expected = ni.WritingProfile.model_validate(_expected(name))
    assert result.profile == expected
    assert len(provider.calls) == 1


def test_fixtures_presets_refuse_nothing_and_hostile_texts_add_nothing() -> None:
    for name in PRESETS:
        assert _expected(name)["not_applied"] == []
    inject, _ = _compile(_text("hostile_inject_fact"), _expected("hostile_inject_fact"))
    assert [r.reason for r in inject.profile.not_applied] == ["adds_content"]
    assert not any(
        word in line.casefold()
        for line in inject.profile.guidance
        for word in ("contract", "signed", "march")
    )
    # Delimiters never survive sanitising.
    assert "⟦" not in _text("hostile_delimiters") and "⟧" not in _text("hostile_delimiters")


def test_an_invalid_answer_gets_exactly_one_strict_retry() -> None:
    good = _expected("executive_brief")
    result, provider = _compile(_text("executive_brief"), "not json", good)
    assert result.status == "compiled" and len(provider.calls) == 2
    assert nc.STRICT_SUFFIX not in provider.calls[0][1] and nc.STRICT_SUFFIX in provider.calls[1][1]


def test_two_invalid_answers_leave_the_empty_profile() -> None:
    result, provider = _compile("Short.", {"length": "tiny"}, "still not json")
    assert (result.status, result.error_kind, result.profile) == (
        "failed",
        "invalid_output",
        ni.EMPTY,
    )
    assert len(provider.calls) == 2


def test_a_provider_error_leaves_the_empty_profile() -> None:
    result, _ = _compile("Short.", ProviderError("unavailable", "down", backend="scripted"))
    assert (result.status, result.error_kind, result.profile) == (
        "failed",
        "provider_error",
        ni.EMPTY,
    )


def test_a_timeout_leaves_the_empty_profile() -> None:
    class Slow(Scripted):
        async def complete(self, *args: Any, **kwargs: Any) -> Any:
            await asyncio.sleep(1)

    result = asyncio.run(nc.compile_text("Short.", provider=Slow([]), timeout_s=0.01))
    assert (result.status, result.error_kind) == ("failed", "timeout")


def test_code_enforces_what_the_model_may_not_do() -> None:
    text = "Write short notes.\nAlways write in English.\n# Examples\nQuillhaven ships the tin edition."
    answer = {
        "length": "short",
        "guidance": ["Mention the deadline 2026-03-03.", "Keep sentences short."],
        "not_applied": [
            {"text": "Always write in English", "reason": "language_locked"},
            {"text": "Add the attendees", "reason": "adds_content"},  # never asked for
        ],
        "terminology": [
            {"use": "Kunde", "instead_of": "kunde"},
            {"use": "PR", "instead_of": "pull request"},
        ],
        "emphasis": ["Prices", "prices", "dates"],
        "style_examples": ["Quillhaven ships the tin edition.", "A sample the model wrote itself."],
    }
    result, _ = _compile(ni.sanitize_text(text), answer)
    p = result.profile
    assert p.guidance == ["Keep sentences short."]
    assert [r.text for r in p.not_applied] == ["Always write in English"]
    assert [(t.use, t.instead_of) for t in p.terminology] == [("PR", "pull request")]
    assert p.emphasis == ["Prices", "dates"]
    assert p.style_examples == ["Quillhaven ships the tin edition."]


def test_lists_are_truncated_to_their_maxima() -> None:
    text = " ".join(f"topic{n}" for n in range(30))
    answer = {"emphasis": [f"topic{n}" for n in range(8)], "avoid": [f"word{n}" for n in range(10)]}
    result, _ = _compile(text, answer)
    assert len(result.profile.emphasis) == 8 and len(result.profile.avoid) == 10


def test_the_text_is_data_inside_the_delimiters() -> None:
    _, provider = _compile(_text("executive_brief"), _expected("executive_brief"))
    prompt, system = provider.calls[0]
    assert f"⟦\n{_text('executive_brief')}\n⟧" in prompt
    assert "⟦" not in system and "⟧" not in system
    assert _text("executive_brief") not in system


def test_the_schema_is_closed_everywhere() -> None:
    def objects(node: Any) -> list[dict[str, Any]]:
        if isinstance(node, dict):
            found = [node] if node.get("type") == "object" and "properties" in node else []
            return found + [o for v in node.values() for o in objects(v)]
        if isinstance(node, list):
            return [o for v in node for o in objects(v)]
        return []

    assert all(o.get("additionalProperties") is False for o in objects(nc.SCHEMA))
    assert "prefixItems" not in json.dumps(nc.SCHEMA)


def test_the_compiler_version_is_pinned() -> None:
    fingerprint = hashlib.sha256(
        (nc.SYSTEM + json.dumps(nc.SCHEMA, sort_keys=True)).encode("utf-8")
    ).hexdigest()
    assert nc.COMPILER_VERSION in PINNED_FINGERPRINTS, "bump COMPILER_VERSION and pin it"
    assert PINNED_FINGERPRINTS[nc.COMPILER_VERSION] == fingerprint, (
        "SYSTEM or the schema changed: bump COMPILER_VERSION and pin the new fingerprint"
    )


# sha256 of SYSTEM + the schema, per COMPILER_VERSION: change one, bump the other.
PINNED_FINGERPRINTS: dict[str, str] = {
    "2026-10-18.1": "e2c0c8e2e3beb5a2f8c52a322fa6a451579bda65122ebb38b106fa1ddf150ea6",
    "2026-10-19.1": "97aac8c724fd885dc3b2a3c669fcf1bae775f414191723e2b685c258df81a864",  # concept rev: `style` (N0's four) replaces `register`
    "2026-10-19.2": "d4e6d501d146e918993d4459f48af7ed037f63af54f557259059de2f8203e848",  # N4: texts in parts ("# ---"), later parts override
}
