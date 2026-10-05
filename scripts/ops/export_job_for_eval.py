#!/usr/bin/env python3
"""Copy ONE consented product recording into the speaker eval set. Refuses without a
non-withdrawn consent-register row naming ``job:<job-id>``; writes only under the eval
prefix; emits ``asr.audio_exported_for_eval`` (ids only) or removes the object.

    uv run python scripts/ops/export_job_for_eval.py --consent-id C-2026-001 --tenant-id <uuid> --job-id <uuid> [--apply]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
CONSENT_REGISTER = REPO / "docs" / "eval" / "speakers-consent.md"
MANIFEST = REPO / "eval" / "speakers" / "v2" / "manifest.json"
DEFAULT_DEST = "s3://notes-eval/speakers/v2/"
AUDIT_KIND = "asr.audio_exported_for_eval"

CONSENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
# The eval bucket and the v2 prefix, nothing else: never a product bucket.
EVAL_DEST_RE = re.compile(r"^s3://[a-z0-9][a-z0-9.-]*eval[a-z0-9.-]*/speakers/v2/$")
NOT_WITHDRAWN = {"", "-", "—", "no"}
EXTENSIONS = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/webm": "webm",
    "audio/flac": "flac",
}
CLIENTS = {"web", "ios", "macos"}


class Refused(SystemExit):
    """A precondition failed; nothing was read or written."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"refused: {reason}")
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Request:
    consent_id: str
    tenant_id: uuid.UUID
    job_id: uuid.UUID
    dest: str
    apply: bool


def parse_args(argv: list[str] | None = None) -> Request:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--consent-id", required=True, help="consent_ref from the register")
    ap.add_argument("--tenant-id", required=True)
    ap.add_argument("--job-id", required=True)
    ap.add_argument(
        "--dest",
        default=os.environ.get("MDX_EVAL_SPEAKERS_URI", DEFAULT_DEST),
        help=f"eval prefix (default $MDX_EVAL_SPEAKERS_URI or {DEFAULT_DEST})",
    )
    ap.add_argument("--apply", action="store_true", help="export (default: dry run)")
    ns = ap.parse_args(argv)
    if not CONSENT_ID_RE.fullmatch(ns.consent_id):
        raise Refused("--consent-id must be a consent_ref (3-64 of [A-Za-z0-9._-])")
    try:
        tenant_id = uuid.UUID(ns.tenant_id)
        job_id = uuid.UUID(ns.job_id)
    except ValueError as exc:
        raise Refused("--tenant-id and --job-id must be UUIDs") from exc
    check_dest(ns.dest)
    return Request(ns.consent_id, tenant_id, job_id, ns.dest, ns.apply)


def check_dest(dest: str) -> None:
    if not EVAL_DEST_RE.fullmatch(dest):
        raise Refused(f"destination {dest!r} is not the speaker eval prefix (…eval…/speakers/v2/)")


def check_consent(consent_id: str, job_id: uuid.UUID, register: str) -> None:
    """The register row must exist, not be withdrawn, and name this job."""
    for line in register.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[0] != consent_id:
            continue
        if cells[4].lower() not in NOT_WITHDRAWN:
            raise Refused(f"consent {consent_id} is withdrawn")
        if f"job:{job_id}" not in cells[1]:
            raise Refused(f"consent {consent_id} does not list job:{job_id} under recording ids")
        return
    raise Refused(f"consent {consent_id} is not in {CONSENT_REGISTER.relative_to(REPO)}")


def audit_payload(consent_id: str, job_id: uuid.UUID, export_id: str) -> dict[str, str]:
    return {"consent_id": consent_id, "job_id": str(job_id), "export_id": export_id}


def object_uri(dest: str, export_id: str, mime_type: str) -> str:
    return f"{dest}{export_id}.{EXTENSIONS.get(mime_type.split(';')[0].strip(), 'bin')}"


def manifest_entry(
    *, export_id: str, consent_id: str, uri: str, sha256: str, row: dict[str, Any]
) -> dict[str, Any]:
    client = row.get("client")
    duration_ms = row.get("duration_ms")
    return {
        "id": export_id,
        "source": "inhouse",
        "license": "consent",
        "consent_ref": consent_id,
        "language": row.get("language"),
        "condition": "product_export",
        "client": client if client in CLIENTS else "n/a",
        "n_speakers": None,  # set when annotated
        "duration_s": round(duration_ms / 1000, 2) if duration_ms else None,
        "audio_sha256": sha256,
        "audio_uri": uri,
        "rttm": None,
        "split": None,  # assigned (dev|test) when annotated, then fixed
    }


def append_manifest(entry: dict[str, Any]) -> None:
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text())
    else:
        manifest = {
            "version": "v2",
            "notes": "Product recordings exported with consent (scripts/ops/"
            "export_job_for_eval.py). Audio is never committed. No job or tenant ids here: "
            "the audit event asr.audio_exported_for_eval links export_id to the job.",
            "files": [],
        }
    manifest["files"].append(entry)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")


async def _export(req: Request) -> int:  # pragma: no cover — needs the stack
    sys.path.insert(0, str(REPO / "services" / "asr-worker" / "src"))
    from asr_worker.config import settings
    from audit import AuditWriter, Severity
    from crypto import Envelope, TenantKekRepository, build_master_key_provider
    from db import create_pool, tenant_connection
    from storage import EncryptedObjectStore, S3Client

    app_pool = await create_pool(settings.db_app_role_dsn, application_name="eval-export")
    try:
        async with tenant_connection(app_pool, req.tenant_id) as conn:
            row = await conn.fetchrow(
                """
                SELECT j.status, j.audio_id, j.language, j.capture_context->>'client' AS client,
                       a.status AS audio_status, a.mime_type, a.duration_ms
                FROM transcription_jobs j JOIN audio_files a ON a.id = j.audio_id
                WHERE j.id = $1
                """,
                req.job_id,
            )
    finally:
        await app_pool.close()
    if row is None:
        raise Refused("no such job in that tenant")
    if row["status"] != "complete":
        raise Refused(f"job is {row['status']}, not complete")
    if row["audio_status"] == "deleted":
        raise Refused("the recording was deleted (retention or erasure)")

    export_id = f"inhouse-{uuid.uuid4().hex[:12]}"
    uri = object_uri(req.dest, export_id, str(row["mime_type"]))
    if not req.apply:
        print(f"--dry-run: consent ok, job complete, would copy the audio to {uri}")
        return 0

    master = build_master_key_provider(
        provider=settings.master_key_provider,
        file_path=settings.master_key_path,
        vault_addr=settings.vault_addr,
        vault_token=settings.vault_token,
        vault_transit_key=settings.vault_transit_key,
        vault_transit_mount=settings.vault_transit_mount,
    )
    await master.startup_self_check()
    crypto_pool = await create_pool(settings.db_crypto_writer_dsn, application_name="eval-export")
    audit_pool = await create_pool(settings.db_audit_writer_dsn, application_name="eval-export")
    try:
        envelope = Envelope(
            master_key_provider=master,
            kek_repository=TenantKekRepository(pool=crypto_pool, master_key_provider=master),
        )
        store = EncryptedObjectStore(
            s3=S3Client(
                endpoint_url=settings.s3_endpoint,
                access_key=settings.s3_access_key,
                secret_key=settings.s3_secret_key,
                region=settings.s3_region,
                use_ssl=settings.s3_use_ssl,
            ),
            bucket=settings.s3_audio_bucket,
            envelope=envelope,
        )
        audio_id = row["audio_id"]
        audio = await store.get(
            key=f"{req.tenant_id}/{audio_id}.enc", tenant_id=req.tenant_id, aad=audio_id.bytes
        )
        sha256 = hashlib.sha256(audio).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audio"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(audio)
            del audio
            subprocess.run(["aws", "s3", "cp", "--only-show-errors", str(path), uri], check=True)
        try:
            await AuditWriter(audit_pool).write_event(
                tenant_id=req.tenant_id,
                kind=AUDIT_KIND,
                actor_role="operator",
                target_kind="asr_job",
                target_id=str(req.job_id),
                payload=audit_payload(req.consent_id, req.job_id, export_id),
                severity=Severity.SEC,
            )
        except Exception:
            subprocess.run(["aws", "s3", "rm", "--only-show-errors", uri], check=False)
            print("audit write failed: the exported object was removed", file=sys.stderr)
            raise
    finally:
        await crypto_pool.close()
        await audit_pool.close()

    append_manifest(
        manifest_entry(
            export_id=export_id, consent_id=req.consent_id, uri=uri, sha256=sha256, row=dict(row)
        )
    )
    print(
        f"exported {export_id} → {uri}; add {export_id} to the consent row's recording ids, "
        "annotate, then commit the manifest"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    req = parse_args(argv)
    check_consent(req.consent_id, req.job_id, CONSENT_REGISTER.read_text(encoding="utf-8"))
    return asyncio.run(_export(req))


if __name__ == "__main__":
    raise SystemExit(main())
