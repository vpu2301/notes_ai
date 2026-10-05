"""No chat routing without a report (or a recorded waiver)."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_routing", REPO / "scripts/ci/check-routing-has-report.py"
)
assert _spec and _spec.loader
check = importlib.util.module_from_spec(_spec)
sys.modules["check_routing"] = check
_spec.loader.exec_module(check)

CONFIG = {
    "routing": {
        "summarize": {"standard": "hf_eu", "premium": "hf_eu"},
        "asr": {"standard": "hf_eu_asr"},
    },
    "env_overrides": {
        "dev": {"chat": {"primary": "mistral_eu"}},
        "staging": {"chat": {"primary": "mistral_eu", "fallback": "hf_eu"}},
    },
}


def test_dev_overrides_and_asr_are_not_chat_routing_but_staging_overrides_are() -> None:
    assert check.routed_chat_backends(CONFIG) == {"hf_eu", "mistral_eu"}


def test_a_report_on_the_real_corpus_at_this_version_satisfies_it(tmp_path: Path) -> None:
    (tmp_path / "notes-pipeline-x.json").write_text(
        json.dumps({"backend": "hf_eu", "prompt_version": "v9", "corpus": "eval/notes/v2"})
    )
    (tmp_path / "notes-pipeline-y.json").write_text(
        json.dumps(
            {"backend": "mistral_eu", "prompt_version": "v9", "corpus": "tests/fixtures/eval/notes"}
        )
    )
    have = check.reports(tmp_path)
    assert check.missing(CONFIG, "v9", have, {}) == ["mistral_eu"], (
        "a synthetic-set report does not count"
    )
    assert check.missing(CONFIG, "v10", have, {}) == ["hf_eu", "mistral_eu"], (
        "a prompt bump needs a new one"
    )


def test_only_an_unexpired_complete_waiver_counts(tmp_path: Path) -> None:
    path = tmp_path / "w.yaml"
    path.write_text(
        "waivers:\n"
        "  - {backend: hf_eu, prompt_version: v9, reason: r, owner: o, expires: 2099-01-01}\n"
        "  - {backend: mistral_eu, prompt_version: v9, reason: r, owner: o, expires: 2000-01-01}\n"
    )
    waived = check.waivers(path, date(2026, 10, 1))
    assert check.missing(CONFIG, "v9", set(), waived) == ["mistral_eu"]


def test_the_committed_config_passes() -> None:
    assert check.main([]) == 0
