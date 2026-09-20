# Runbook — growing the speaker eval set from product recordings (opt-in)

The gold set (`eval/speakers/v1`) is recorded on purpose. v2 adds real
product recordings that show a failure pattern the weekly speaker review
found (`docs/product/speaker-decisions.md`) — **only** with the consent of
every voice on the recording, one recording at a time, by an operator.
Nothing here runs automatically, and no product code path can reach it.

## Rules

- **Consent first, for that recording.** Every person on it signs the
  template in `docs/eval/speakers-consent.md`. Without it: no export.
- **Only audio, only to the eval prefix.** The script writes nowhere but
  `s3://notes-eval/speakers/v2/` (or `MDX_EVAL_SPEAKERS_URI`, which must
  also be an `…eval…/speakers/v2/` prefix). Transcript text and speaker
  names are never read or copied; annotation starts from scratch.
- **Audited.** Every export writes `asr.audio_exported_for_eval` (severity
  `sec`) to the tenant's audit chain: `consent_id`, `job_id`, `export_id`.
- **Erasable.** Withdrawal = erase within 7 days (below).

## Procedure

1. **Collect consent.** Signed forms for every voice. Add a register row
   in `docs/eval/speakers-consent.md`; its "recording ids" cell names the
   job as `job:<job-uuid>` (the export refuses a consent that does not name
   the job, or one marked withdrawn).
2. **Dry run** (checks consent, tenant, job and that the recording still
   exists; reads no audio, writes nothing):

   ```bash
   uv run python scripts/ops/export_job_for_eval.py \
       --consent-id C-2026-001 --tenant-id <tenant-uuid> --job-id <job-uuid>
   ```

   It needs the asr-worker's environment (`DB_*` DSNs, master key, `S3_*`)
   — run it where the worker's config resolves, e.g. an ops shell with the
   worker's env.
3. **Export** with `--apply`, with the **eval role's** AWS credentials in
   the environment for `aws s3 cp` (same as
   `scripts/eval/fetch_speaker_corpus.py`). The script decrypts through
   libs/storage + libs/crypto into a 0600 temp file, copies it, deletes it,
   writes the audit event (if that fails the object is removed again) and
   appends an entry to `eval/speakers/v2/manifest.json` (no job or tenant id
   in it; `n_speakers`, `rttm`, `split` are null until annotated).
4. **Register.** Add the printed `export_id` to the consent row's
   "recording ids", next to `job:<uuid>`.
5. **Annotate** (Audacity labels → `scripts/eval/labels_to_rttm.py`), fill
   `n_speakers`, `condition`, `split` (dev|test, then fixed forever), and
   commit the manifest + RTTM. Audio is never committed
   (`make check-no-eval-audio`).

## Withdrawal / erasure

```bash
uv run python scripts/ops/erase_eval_recording.py <export_id>
```

Finds the entry in v1 or v2, removes the object (eval role), any local copy,
the RTTM and the manifest entry. Mark the register row withdrawn with the
date and commit. The product recording itself is untouched — its lifecycle
is the tenant's retention, not this runbook.

## Failure modes

- `refused: consent … is not in …` / `does not list job:…` / `is withdrawn`
  — step 1 is missing or out of date.
- `refused: destination … is not the speaker eval prefix` — a wrong
  `--dest` / `MDX_EVAL_SPEAKERS_URI`; never point it at a product bucket.
- `refused: the recording was deleted` — retention or erasure took it;
  there is nothing to export.
- `decrypt`/`ObjectNotFoundError` — see asr-worker § object-store-outage.
