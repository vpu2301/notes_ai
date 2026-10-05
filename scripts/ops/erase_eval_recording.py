"""Erase one in-house gold-set recording on request (consent withdrawn).

    uv run python scripts/ops/erase_eval_recording.py FILE_ID

Deletes the object from the private eval bucket (eval role), the local
copy, its RTTM and its manifest entry. Record the erasure in the consent
register (docs/eval/speakers-consent.md) and commit the manifest change.

Sprint TQ1: the ASR gold set (``eval/asr/v1``) is covered too — its whole
bucket prefix ``s3://notes-eval/asr/v1/<id>/`` (audio, reference, spans,
RTTM, alignment), the local ``eval/asr/v1/<id>/`` folder and the manifest
row. Public and third-party rows are refused, as for the speaker set.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SPEAKERS = Path(__file__).resolve().parents[2] / "eval" / "speakers"
# v1: the recorded gold set; v2: product recordings exported with consent
# (scripts/ops/export_job_for_eval.py, Sprint 30).
ROOTS = (SPEAKERS / "v1", SPEAKERS / "v2")


def _find(file_id: str) -> tuple[Path, dict, dict]:
    for root in ROOTS:
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text())
        entry = next((e for e in manifest["files"] if e["id"] == file_id), None)
        if entry is not None:
            return root, manifest, entry
    raise SystemExit(f"{file_id} not in manifest")


ASR = Path(__file__).resolve().parents[2] / "eval" / "asr" / "v1"
ASR_BUCKET = os.environ.get("MDX_EVAL_ASR_URI", "s3://notes-eval/asr/v1")


def _erase_asr(file_id: str) -> int | None:
    manifest_path = ASR / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text())
    entry = next((e for e in manifest["recordings"] if e["id"] == file_id), None)
    if entry is None:
        return None
    if entry.get("public") or not entry.get("consent_ref"):
        raise SystemExit(f"{file_id} is a public or third-party recording; nothing to erase")
    subprocess.run(
        ["aws", "s3", "rm", "--recursive", f"{ASR_BUCKET.rstrip('/')}/{file_id}/"], check=True
    )
    shutil.rmtree(ASR / file_id, ignore_errors=True)
    manifest["recordings"] = [e for e in manifest["recordings"] if e["id"] != file_id]
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"erased {file_id} ({entry['consent_ref']}); update the consent register")
    return 0


def main(file_id: str) -> int:
    asr = _erase_asr(file_id)
    if asr is not None:
        return asr
    root, manifest, entry = _find(file_id)
    manifest_path = root / "manifest.json"
    if entry["source"] != "inhouse":
        raise SystemExit(f"{file_id} is a public corpus file; nothing to erase")
    subprocess.run(["aws", "s3", "rm", entry["audio_uri"]], check=True)
    for path in (root / "audio").glob(f"{file_id}.*"):
        path.unlink()
    if entry.get("rttm"):
        (root / entry["rttm"]).unlink(missing_ok=True)
    manifest["files"] = [e for e in manifest["files"] if e["id"] != file_id]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"erased {file_id}; update the consent register")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
