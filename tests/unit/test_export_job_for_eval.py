"""Eval export (Sprint 30): consent, destination and payload checks — no S3, no DB."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "export_job_for_eval", REPO / "scripts" / "ops" / "export_job_for_eval.py"
)
assert _spec is not None and _spec.loader is not None
export = importlib.util.module_from_spec(_spec)
sys.modules["export_job_for_eval"] = export
_spec.loader.exec_module(export)

TENANT = uuid.UUID("00000000-0000-0000-0000-00000000000a")
JOB = uuid.UUID("11111111-2222-3333-4444-555555555555")
REGISTER = f"""
| consent_ref | recording ids | people | date | withdrawn |
|---|---|---|---|---|
| C-2026-001 | job:{JOB} | 3 | 2026-09-20 | |
| C-2026-002 | job:{JOB} | 2 | 2026-09-20 | 2026-09-22 |
| C-2026-003 | inhouse-abc | 2 | 2026-09-20 | — |
"""


def _args(*extra: str) -> list[str]:
    return ["--consent-id", "C-2026-001", "--tenant-id", str(TENANT), "--job-id", str(JOB), *extra]


def test_consent_id_is_required() -> None:
    with pytest.raises(SystemExit):
        export.parse_args(["--tenant-id", str(TENANT), "--job-id", str(JOB)])


@pytest.mark.parametrize("flag", ["--tenant-id", "--job-id"])
def test_tenant_and_job_are_required(flag: str) -> None:
    argv = _args()
    i = argv.index(flag)
    with pytest.raises(SystemExit):
        export.parse_args(argv[:i] + argv[i + 2 :])


@pytest.mark.parametrize("consent", ["", "x", "C 1", "../etc", "a" * 65])
def test_malformed_consent_id_is_refused(consent: str) -> None:
    argv = _args()
    argv[1] = consent
    with pytest.raises(export.Refused):
        export.parse_args(argv)


def test_non_uuid_ids_are_refused() -> None:
    argv = _args()
    argv[3] = "not-a-uuid"
    with pytest.raises(export.Refused, match="UUIDs"):
        export.parse_args(argv)


def test_dry_run_is_the_default_and_dest_defaults_to_the_eval_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MDX_EVAL_SPEAKERS_URI", raising=False)
    req = export.parse_args(_args())
    assert req.apply is False
    assert req.dest == "s3://notes-eval/speakers/v2/"
    assert export.parse_args(_args("--apply")).apply is True


@pytest.mark.parametrize(
    "dest",
    [
        "s3://mdx-audio/",
        "s3://mdx-audio/speakers/v2/",
        "s3://notes-eval/speakers/v1/",
        "s3://notes-eval/speakers/v2",
        "s3://notes-eval/speakers/v2/../../mdx-audio/",
        "file:///tmp/eval/speakers/v2/",
        "https://notes-eval.example.com/speakers/v2/",
    ],
)
def test_only_the_eval_prefix_is_a_destination(dest: str) -> None:
    with pytest.raises(export.Refused, match="eval prefix"):
        export.parse_args(_args("--dest", dest))


def test_a_configured_eval_bucket_is_accepted() -> None:
    req = export.parse_args(_args("--dest", "s3://acme-eval-eu/speakers/v2/"))
    assert req.dest == "s3://acme-eval-eu/speakers/v2/"


def test_consent_listed_for_the_job_passes() -> None:
    export.check_consent("C-2026-001", JOB, REGISTER)


def test_unknown_consent_is_refused() -> None:
    with pytest.raises(export.Refused, match="not in"):
        export.check_consent("C-2026-999", JOB, REGISTER)


def test_withdrawn_consent_is_refused() -> None:
    with pytest.raises(export.Refused, match="withdrawn"):
        export.check_consent("C-2026-002", JOB, REGISTER)


def test_consent_for_another_recording_is_refused() -> None:
    with pytest.raises(export.Refused, match="does not list"):
        export.check_consent("C-2026-003", JOB, REGISTER)


def test_main_refuses_before_touching_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_req: object) -> int:
        raise AssertionError("export must not start without consent")

    monkeypatch.setattr(export, "_export", boom)
    with pytest.raises(export.Refused):
        export.main(_args())  # the real register has no row naming this job


def test_audit_payload_carries_ids_only() -> None:
    payload = export.audit_payload("C-2026-001", JOB, "inhouse-0123456789ab")
    assert payload == {
        "consent_id": "C-2026-001",
        "job_id": str(JOB),
        "export_id": "inhouse-0123456789ab",
    }
    assert export.AUDIT_KIND == "asr.audio_exported_for_eval"


def test_object_uri_stays_under_the_prefix() -> None:
    uri = export.object_uri("s3://notes-eval/speakers/v2/", "inhouse-ab", "audio/webm;codecs=opus")
    assert uri == "s3://notes-eval/speakers/v2/inhouse-ab.webm"
    assert export.object_uri("s3://notes-eval/speakers/v2/", "inhouse-ab", "x/y").endswith(".bin")


def test_manifest_entry_has_no_job_or_tenant_and_folds_unknown_clients() -> None:
    entry = export.manifest_entry(
        export_id="inhouse-ab",
        consent_id="C-2026-001",
        uri="s3://notes-eval/speakers/v2/inhouse-ab.webm",
        sha256="0" * 64,
        row={"language": "de", "client": "<script>", "duration_ms": 61234},
    )
    assert entry["client"] == "n/a"
    assert entry["duration_s"] == 61.23
    assert entry["split"] is None and entry["n_speakers"] is None
    flat = repr(entry)
    assert str(JOB) not in flat and str(TENANT) not in flat
