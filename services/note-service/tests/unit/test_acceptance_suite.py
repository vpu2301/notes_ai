"""P1-04 — the critical cases activation asks for: shipped with the service, checked by
code on the produced note, valid only for the code they ran on; and P1-02's clean
comparison: a run answered by another model, or on a fallback, is not one."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from note_service.domain import acceptance, experiments
from note_service.jobs.evaluate_note import comparison_integrity
from note_service.routers.ai_experiments import StartExperimentRequest


def _artifact(*lines: tuple[str, str]) -> dict[str, Any]:
    return {"sections": [{"lines": [{"kind": k, "text": t} for k, t in lines]}]}


def test_the_three_critical_cases_ship_with_the_service() -> None:
    ids = [c.id for c in acceptance.cases()]
    assert ids == ["ml01_de_host_en_promise", "ml11_de_polarity_inversion", "ml12_de_participants"]
    for case in acceptance.cases():
        assert case.result["turns"] and case.assertions


def test_a_correct_note_passes_and_an_inverted_one_fails() -> None:
    inversion = acceptance.case("ml11_de_polarity_inversion")
    assert inversion is not None
    correct = _artifact(
        ("framing", "Besprechung der Einkaufsleitung."),
        ("summary", "Die Lage der Zulieferer im Süden ist deutlich schlechter als im Vorjahr."),
        ("bullet", "- Der Aufsichtsrat hat den Ausbau in Ulm nicht genehmigt."),
    )
    inverted = _artifact(
        ("framing", "Besprechung der Einkaufsleitung."),
        ("summary", "Die Lage der Zulieferer im Süden ist besser als im Vorjahr."),
        ("bullet", "- Der Aufsichtsrat hat den Ausbau in Ulm genehmigt."),
    )
    assert acceptance.check(inversion.assertions, correct) == []
    failed = acceptance.check(inversion.assertions, inverted)
    assert "must_contain_any[0]" in failed and any(f.startswith("must_not_contain") for f in failed)


def test_an_invented_guest_fails_the_participant_case() -> None:
    case = acceptance.case("ml12_de_participants")
    assert case is not None
    invented = _artifact(("framing", "Sendung. Es sprechen Moderation und Midterm-Wahlen (Gast)."),
                         ("summary", "Der Haushalt kann blockiert werden."))  # fmt: skip
    kept = _artifact(("framing", "Sendung. Es sprechen die Moderation und Maren Vogt."),
                     ("summary", "Der Haushalt kann blockiert werden."))  # fmt: skip
    assert "framing_must_not_contain[0]" in acceptance.check(case.assertions, invented)
    assert acceptance.check(case.assertions, kept) == []


def test_a_result_is_valid_only_for_the_code_it_ran_on(monkeypatch: pytest.MonkeyPatch) -> None:
    before = acceptance.suite_version()
    monkeypatch.setattr(acceptance.final_check, "VERSION", "2099-01-01.changed")
    assert acceptance.suite_version() != before


def test_a_request_names_notes_or_the_suite_never_both() -> None:
    base = {
        "candidate_version_ids": [str(uuid4())],
        "budget_cap_cents": 100,
        "idempotency_key": "k" * 10,
    }
    assert StartExperimentRequest.model_validate({**base, "suite": "critical"}).suite == "critical"
    with pytest.raises(ValidationError):
        StartExperimentRequest.model_validate(base)
    with pytest.raises(ValidationError):
        StartExperimentRequest.model_validate(
            {
                **base,
                "suite": "critical",
                "sources": [{"note_id": str(uuid4()), "transcript_rev": 1}],
            }
        )


def _suite_experiment(version: str, *, passed: bool, current: bool = True) -> tuple[Any, list[Any]]:
    suite = acceptance.suite_version() if current else "old"
    experiment = SimpleNamespace(
        id=uuid4(),
        state="completed",
        candidates=[version],
        sources=[{"case_id": c.id, "suite_version": suite} for c in acceptance.cases()],
    )
    runs = [
        SimpleNamespace(
            candidate_index=0,
            state="done",
            metrics={
                "acceptance": {
                    "case": c.id,
                    "passed": passed or n > 0,
                    "failures": [] if passed or n > 0 else ["must_not_contain[0]"],
                }
            },
        )  # fmt: skip
        for n, c in enumerate(acceptance.cases())
    ]
    return experiment, runs


def _problem(
    monkeypatch: pytest.MonkeyPatch, version: str, found: list[tuple[Any, list[Any]]]
) -> Any:
    async def _recent(conn: Any, *, limit: int = 20) -> list[Any]:
        return [e for e, _r in found]

    async def _runs(conn: Any, *, experiment_id: Any) -> list[Any]:
        return next(r for e, r in found if e.id == experiment_id)

    monkeypatch.setattr(experiments, "recent", _recent)
    monkeypatch.setattr(experiments, "runs", _runs)
    return asyncio.run(
        experiments.acceptance_problem(
            None,
            version_id=version,
            suite_version=acceptance.suite_version(),  # type: ignore[arg-type]
        )
    )


def test_activation_needs_the_critical_cases_passed_on_this_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version = str(uuid4())
    assert "first" in _problem(monkeypatch, version, [])
    assert "failed" in _problem(monkeypatch, version, [_suite_experiment(version, passed=False)])
    assert "again" in _problem(
        monkeypatch, version, [_suite_experiment(version, passed=True, current=False)]
    )
    assert _problem(monkeypatch, version, [_suite_experiment(version, passed=True)]) is None


def test_a_comparison_is_clean_only_on_the_selected_models_without_fallback() -> None:
    snapshot = {"models": {"extraction": {"backend": "mistral_eu", "routed": False},
                           "composition": {"routed": True}}}  # fmt: skip
    calls = [
        {"stage": "extraction", "backend": "mistral_eu"},
        {"stage": "composition", "backend": "x"},
    ]
    clean = comparison_integrity(snapshot, calls, [])
    assert clean["clean"] and clean["requested"] == {
        "extraction": "mistral_eu",
        "composition": "routed",
    }
    other = comparison_integrity(
        snapshot, [{"stage": "extraction", "backend": "mistral_eu_small"}], []
    )
    assert (
        not other["clean"]
        and "extraction: answered by mistral_eu_small" in other["unclean_reasons"]
    )
    fallback = comparison_integrity(
        snapshot,
        calls,
        [{"kind": "summarize", "backend": "mistral_eu_small", "reason": "probe_failed"}],
    )
    assert not fallback["clean"] and fallback["fallbacks"]
