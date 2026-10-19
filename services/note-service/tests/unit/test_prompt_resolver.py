"""P1-01 — one resolver for preview, experiment and production: for the same profile,
flags, language, model profile and bullet budget, the hash it gives each call is the
hash of the system text the pipeline actually sends."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from note_service.domain import prompt_profiles as profiles
from note_service.domain.meeting_doc import pipeline, prompts

from .meeting_doc_fakes import ScriptedProvider, as_result, load_fixture

# The scripted model's step → the resolver's call.
STEP_CALL = {
    "extract": "extraction",
    "context": "context",
    "block": "composition.topic",
    "summary": "composition.summary",
    "pairs": "deduplication",
    "participants": "participants",
}
EDITED = "List what was said, in {{output_language}}; keep every condition."


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _run(
    config: profiles.ProfileConfig, *, multilingual: bool, fidelity: bool
) -> tuple[Any, ScriptedProvider]:
    provider = ScriptedProvider()
    document = asyncio.run(
        pipeline.run(
            as_result(load_fixture("m09_en_voice_memo")),
            provider=provider,
            role_by_key={},
            output_language="en",
            multilingual=multilingual,
            fidelity=fidelity,
            instructions=profiles.stage_overrides(config),
            length=config.length,
        )
    )
    return document, provider


def _first_requests(provider: ScriptedProvider) -> dict[str, str]:
    """The first system text sent per call kind (retries add suffixes: other texts)."""
    out: dict[str, str] = {}
    for step, _prompt, system in provider.calls:
        call = STEP_CALL.get(step)
        if call and call not in out:
            out[call] = _sha(system)
    return out


def _resolved(config: profiles.ProfileConfig, document: Any, **flags: bool) -> dict[str, str]:
    return profiles.prompt_hashes(
        config,
        language="en",
        bullets=int(document.stats["bullets_per_block"] or profiles.DEFAULT_BULLETS),
        **flags,
    )


def test_a_profiles_resolved_hashes_are_the_requests_it_sends() -> None:
    config = profiles.ProfileConfig(stages={"extraction": EDITED})
    document, provider = _run(config, multilingual=True, fidelity=True)
    sent = _first_requests(provider)
    resolved = _resolved(config, document, multilingual=True, fidelity=True)
    assert sent, "the scripted run made no calls"
    for call, sha in sent.items():
        assert resolved[call] == sha, call
    # The edited stage text is what the extraction request carries.
    extract_system = next(s for step, _p, s in provider.calls if step == "extract")
    assert "List what was said, in English; keep every condition." in extract_system


def test_with_multilingual_evidence_off_the_profile_text_is_not_sent_and_says_so() -> None:
    config = profiles.ProfileConfig(stages={"extraction": EDITED})
    document, provider = _run(config, multilingual=False, fidelity=False)
    sent = _first_requests(provider)
    resolved = _resolved(config, document, multilingual=False, fidelity=False)
    for call, sha in sent.items():
        assert resolved[call] == sha, call
    calls = {
        c.call: c
        for c in profiles.resolve(config, language="en", multilingual=False, fidelity=False)
    }
    assert calls["extraction"].source == "not_applied"
    assert "keep every condition" not in calls["extraction"].system
    # No legacy rule labels another language as noise on the path that runs it.
    on = {
        c.call: c for c in profiles.resolve(config, language="de", multilingual=True, fidelity=True)
    }
    assert prompts._NOISE_RULE["de"] not in on["extraction"].system


def test_the_resolver_names_every_call_and_where_its_text_comes_from() -> None:
    config = profiles.ProfileConfig(stages={"composition": profiles.bundled_text("composition")})
    calls = profiles.resolve(config, language="de", multilingual=True, fidelity=True)
    sources = {c.call: c.source for c in calls}
    assert sources["composition.summary"] == "profile" and sources["composition.topic"] == "profile"
    assert sources["extraction"] == "bundled" and sources["context"] == "code"
    assert {"deduplication", "participants", "verification.final"} <= set(sources)
    small = {
        c.call
        for c in profiles.resolve(
            config, language="de", multilingual=True, fidelity=True, small=True
        )
    }
    assert {
        "composition.bullets",
        "composition.heading",
    } <= small and "composition.topic" not in small
