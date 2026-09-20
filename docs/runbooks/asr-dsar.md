# Runbook — Data-subject requests for recordings and transcripts (ASR)

What the speaker-labeling work (Sprints 28–32) stores about a recording, and
where each piece goes on erasure. Recipients of shared notes: see
`sharing-dsar.md`.

| Data | Where | Erased by |
|---|---|---|
| Audio (encrypted) | object store `{tenant}/{audio}.enc` | `scripts/ops/erase_asr_job.py` |
| Transcript + every re-labelled revision | object store `{tenant}/{job}.json.enc`, `{tenant}/{job}.r{n}.json.enc` (n = 2 … `diarization_rev`) | `erase_asr_job.py` deletes every key deterministically — integration test `test_erasing_a_job_removes_every_revision_edit_and_row` |
| `speaker_names`, `speaker_name_sources`, `speaker_name_candidates`, `dismissed_name_suggestions`, `capture_context`, re-run state | `transcription_jobs` row | row delete (`erase_asr_job.py`) |
| Speaker edits (merges, moved turns) | `transcription_speaker_edits` | `ON DELETE CASCADE` with the job |
| `audio_files` row | Postgres | `erase_asr_job.py` (when no other job uses the recording) |
| "Audio still exists" cache | Redis `workspace:{tenant}:asr:audio_exists:{audio}` | expires after 10 min |
| Gold-set in-house recordings | eval bucket | `scripts/ops/erase_eval_recording.py` (consent register) |
| Speaker embeddings | **nowhere** — never stored (schema test in CI) | — |

Clients: the macOS/iOS `PendingCaptures` records (with their capture context)
and the web `sessionStorage` capture context are cleared on logout.

Audit payloads never carry names, candidates, transcript text or the local
speaker name — only labels, counts and vocabulary.

## Erase one job

A privileged operator flow — migration 0004: `app_role` never deletes.

    DB_ERASE_DSN=<operator role> S3_ENDPOINT=... S3_ACCESS_KEY=... S3_SECRET_KEY=... \
      uv run --project services/asr-service python scripts/ops/erase_asr_job.py \
        --tenant-id <uuid> --job-id <uuid>            # dry run: counts
      … --apply                                        # erase

- Every statement filters by the given tenant: a job of another tenant is
  "not found".
- A job still transcribing or re-labelling is refused (exit 3): its worker
  would write objects back afterwards. Cancel or wait, then erase.
- Every object delete is VERIFIED before any row is touched (the storage
  client swallows delete errors — missing or wrong S3 credentials would
  otherwise "succeed"). All four environment variables are required.
- Deletes revisions up to `diarization_rev + 1` (a failed re-run writes its
  artifact before the row moves). Objects first, rows last, one transaction:
  re-run the command if it stops half way.

## Access ("what do you hold about me")

`GET /asr/jobs/{id}` and `GET /asr/jobs/{id}/result` under the person's own
session return every field above that belongs to them; the DSAR export for a
workspace is those responses per job. No separate export tool yet.

## Known gap

`audio_files.retention_until` is never set or swept: audio is kept until
erased. P1 before beta (see speaker-decisions.md → debt).
