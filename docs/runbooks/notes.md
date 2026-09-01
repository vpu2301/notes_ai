# Runbook — Notes

Sprint-08 ships the central artifact of the product. This runbook lists
the operational fault-modes and their playbooks.

## Health checks

- `GET /healthz` on note-service returns 200 + JSON with db pool
  status.
- Grafana: `sprint-08-reports` dashboard (notes surface).
- Daily reconciler: cron 04:30 UTC; logs to `note-service/chain-reconciler`.

## Incident playbooks

### High autosave conflict rate

Alert: `NoteAutosaveConflictRateHigh` (> 5% of PUTs returning 409
for 10 minutes).

Likely causes (ordered):
1. **FE protocol drift** — a FE update changed the autosave cadence
   or stopped sending `expected_version` correctly. Check the FE
   release log; coordinate with frontend lead.
2. **Clock skew** — autosaves arriving out-of-order due to retry
   logic interpreting timestamps incorrectly. Check autosave-latency
   metrics for tail spikes.
3. **Two users editing the same draft** — sprint-08 doesn't
   support multi-author concurrent edit; conflict is the correct
   surface to the FE.

Mitigation:
- If protocol drift: roll back the FE.
- If genuine concurrent edit: educate; defer to sprint-future
  collaborative-editing work.
- If clock skew: investigate FE caching layer.

### Search performance issue

Alert: `NoteSearchLatencyHigh` (p95 > 500ms for 5 min).

1. SSH into a replica, `EXPLAIN ANALYZE` the slow query (use
   `pg_stat_statements` for the actual SQL).
2. If sequential scan appears on `note_versions.search_vector`:
   `REINDEX INDEX CONCURRENTLY note_versions_search_vector_idx;`
3. If GIN hit but still slow: check tenant has hit > 1M notes.
   See ADR-0021 for the partition trigger.
4. If RLS subquery showing N+1: the `EXISTS` predicate should push
   into the join. Investigate any recent migration that re-wrote the
   policy.

### Version chain break

Alert: `NoteChainIntegrityFailure` (critical; pages security lead).

**DO NOT auto-repair.** This is potentially a forensic event.

1. Pull the row from `audit.note_chain_failures` keyed by the alert
   payload's `note_id`.
2. Run `scripts/admin/note_chain_repair.py --note-id <uuid>` to
   dump the chain + history (read-only).
3. Open the security incident in the tracker.
4. Convene tech lead + DBA + security lead before any DB-level edit.
5. Manual repair: a single UPDATE with full notes in the incident
   record + manual hash-chained audit append.

### Code generation race

Symptom: two notes with identical `code` (`NOTE-{year}-{counter}`).

The advisory lock should make this impossible. If observed:
1. Check `pg_locks` for `pg_advisory_xact_lock` acquisition.
2. Confirm `note_code_counters` uniqueness constraint blocked the
   duplicate INSERT — only one of the two `RETURNING id` would have
   succeeded.
3. If somehow both succeeded, escalate to DB integrity incident.

### Stuck draft (> 30 days)

Idle-draft cleanup auto-archives at 30 days (`MDX_IDLE_DRAFT_DAYS`).
Since sprint 16 it runs in-process when `MDX_BACKGROUND_JOBS=true`
(interval `MDX_BACKGROUND_JOBS_INTERVAL_S`, default daily; ADR-0041),
or on demand:
`uv run --project services/note-service python -m note_service.jobs.idle_draft_cleanup`.
Each run audits `scheduler.job.completed` (global tenant) and
`note.cancelled` per archived draft.
For an urgent manual archive:

```sql
UPDATE notes
SET status='cancelled', cancelled_at=now(),
    cancelled_reason='manual_archive: <ticket>'
WHERE id=$1 AND status='draft';
```

Re-open within 90 days: the version chain is intact; INSERT a new
draft version and UPDATE `status='draft', cancelled_at=NULL`. Audit
this as `note.draft.updated` with payload `{manual_reopen: true}`.

## Operational tunables

| envvar / setting                  | default | purpose                                       |
| --------------------------------- | ------- | --------------------------------------------- |
| `MDX_IDLE_DRAFT_DAYS`             | 30      | idle-draft auto-archive horizon               |
| `MDX_BACKGROUND_JOBS`             | false   | in-process scheduler (cleanup + reconciler)   |
| `MDX_BACKGROUND_JOBS_INTERVAL_S`  | 86400   | scheduler interval                            |
| `MDX_TEMPLATE_CACHE_MAXSIZE`      | 5000    | in-process template cache entries             |
| `MDX_TEMPLATE_CACHE_TTL_SECONDS`  | 60      | template cache TTL                            |
| `MDX_FFMPEG_PATH`                 | ffmpeg  | audio-clip pipeline binary (ADR-0037)         |

(Autosave min-interval 5 s and diff-cache 1024 entries are in-code
defaults — `domain/autosave_rate_limit.py`, `domain/diff_cache.py`.)

## Secrets

None specific to the notes surface beyond the shared master-key mount
(`MDX_MASTER_KEY_PATH`) used by the audio-clip pipeline.

## Sprint-08 wrap

This runbook is the operational contract for the notes surface. If
a playbook step turns out wrong in practice, update this file in the
same PR as the fix.

## audio-clip-failures

`AudioClipFailuresHigh` (sprint 15, ADR-0037): the decrypt→slice→encode
pipeline on `POST /v1/audio-clips` is erroring (`outcome="pipeline_error"`,
502s to callers). 410s are NOT failures — they are the honest retention
answers (`no_audio_source` / `audio_not_retained` / `audio_erased` /
`audio_partially_retained`).

1. Is ffmpeg present in the note-service image? (`MDX_FFMPEG_PATH`,
   Dockerfile installs it since S15.) A missing binary fails EVERY clip.
2. `mdx_audio_clip_pipeline_latency_ms` p95 climbing toward the ffmpeg
   timeout → the source objects are huge (long sessions) or the host is
   CPU-starved; the whole-object GCM decrypt (~2 MB/min of audio) is
   expected cost, not a leak.
3. Corrupt source WAV (`unexpected WAV layout` in logs): the session was
   written by a pre-S04 build or the object was truncated — check
   `audio_files.sha256` against the object.
4. MinIO lifecycle: clips live 5 min (Redis registry) with a 1-day
   bucket ILM backstop on `mdx-audio-clips`; a full bucket is never the
   explanation — check the ILM rule survived a `minio-init` re-run.
