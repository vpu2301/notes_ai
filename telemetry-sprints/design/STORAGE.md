# Storage & retention design

Postgres 16, raw SQL migrations (`infra/postgres/migrations/`, next free number **0092**), asyncpg, RLS on every tenant table. Additive only.

## 1. Tables (migration `0092_telemetry.sql` + `.down.sql`)

| Table | PK | Key columns | Indexes |
|---|---|---|---|
| `telemetry_runs` | `processing_run_id` uuid | `tenant_id`, `recording_id` uuid (→ `transcription_jobs.id`, **no FK**, see §4), `note_id`, `note_generation_id`, `kind`, `reprocess_scope`, `trigger`, `status`, `error_category`, `submitted_at`, `started_at`, `finished_at`, derived timing columns, `created_by`, `concurrent_runs_at_start`, `other_model_activity` jsonb, `telemetry_overhead_seconds`, `trace_id`, `retention_until`, `null_reasons` jsonb, `telemetry_schema_version` smallint | `(tenant_id, recording_id, submitted_at DESC)`, `(status) WHERE status IN ('queued','running')`, `(retention_until)` |
| `telemetry_run_contexts` | `processing_run_id` | all `run_context` fields; `effective_config` jsonb | — |
| `telemetry_spans` | `span_id` uuid | `processing_run_id`, `tenant_id`, `parent_span_id`, `stage`, `name`, `attempt`, `status`, `error_category`, `error_class`, `start/end_monotonic_ns` bigint, `start/end_wall_utc` timestamptz, `clock_source`, `process_id`, `host`, `attributes` jsonb, `is_parallel_with` uuid[] | `(processing_run_id)`, `(stage, start_wall_utc)` |
| `telemetry_llm_calls` | `llm_call_id` | `span_id`, `processing_run_id`, `tenant_id`, all `llm_call` fields | `(processing_run_id)`, `(purpose, backend)` |
| `telemetry_client_events` | `event_id` (client-minted → idempotent ingest, `ON CONFLICT DO NOTHING`) | `processing_run_id` (nullable), `recording_id`, `tenant_id`, `client`, `client_version`, `event`, `client_wall_utc`, `client_monotonic_ns`, `server_received_utc`, `estimated_clock_offset_ms`, `attributes` jsonb | `(processing_run_id)`, `(tenant_id, recording_id)` |

New nullable columns (additive): `transcription_jobs.processing_run_id`, `note_generations.processing_run_id`.

CHECK constraints mirror the enums; `telemetry_schema_version` defaults to 1. Readers tolerate older versions (they switch on the column).

## 2. Write model

- **Append-only.** Spans/llm calls/client events are inserted, never updated — except the one allowed transition of a long span: a `started` begin-row is written at span start when the stage can exceed 10 s (`model_init`, `asr_primary`, `asr_recovery`, `diarization_*`, `llm_call`, `queue`), and the end row **replaces** it via `INSERT … ON CONFLICT (span_id) DO UPDATE` exactly once (status `started` → final). A crash leaves the `started` row as evidence.
- `telemetry_runs` is the one mutable row: status/timestamps/derived fields are updated as the run progresses; derived timings are recomputed from spans on finish, never accumulated.
- **Fail-open:** every write goes through `telemetry.guard()` — catches everything, logs once per (process, error class), increments `mdx_telemetry_write_failures_total{stage}`, returns. Never retries, never blocks the pipeline. Writes are batched per process and flushed off the hot path (asyncio task; sync code via a thread-safe queue).
- DB role: services already connect as `app_role` (RLS by `app.tenant_id`); workers write with the tenant of the job they process.

## 3. Retention

- `retention_until = submitted_at + MDX_TELEMETRY_RETENTION_DAYS` (default **90**), settable per environment.
- Daily job `scripts/jobs/telemetry_retention.py` (pattern of `share_retention.py` / `ai_retention.py`, cron entry in `infra/compose/cron/`) deletes runs past `retention_until` and their children (`ON DELETE CASCADE` from `telemetry_runs`).
- Deleted with the recording: the existing recording-erasure path (`scripts/ops/erase_asr_job.py`, account/workspace deletion) gets one extra `DELETE FROM telemetry_runs WHERE recording_id = $1`. Deletion removes telemetry only.
- The same job closes orphaned runs (`running` for > 6 h with no new span) as `failed / unknown`.

## 4. Access

- RLS policies identical to other tenant tables (select/insert/update/delete for `app.tenant_id`, restrictive policy), `GRANT … TO app_role` — `make check-rls` covers it.
- Recording ACL inheritance: the read API joins `telemetry_runs.recording_id → transcription_jobs → notes` and applies the existing note access rule (`domain/access.py`, collaborator/workspace visibility) — a user who can read the note/transcript can read its telemetry.
- Admin: a new platform role (ADMIN.md) reads all tenants through a dedicated `telemetry_reader` DB role with `BYPASSRLS`-free cross-tenant SELECT policies, mirroring the existing `funnel_reader` pattern (Sprint 22).
- **No FK to `transcription_jobs`:** the W5 gate (`check-note-move-covers-all-tables.py`) requires every table referencing `notes(id)`/`transcription_jobs(id)` to move with the note. Telemetry stays in the tenant where the processing happened; without an FK the gate is not triggered, and the erasure path deletes explicitly. (Alternative: FK + add to `LEFT_ALONE` with this reason — OPEN_QUESTIONS Q6.)

## 5. Redaction (`telemetry.redact`)

One function, applied at the storage boundary to `attributes`, `effective_config`, `error_class`, client-event attributes:
- drop keys matching `(?i)(text|transcript|prompt|content|name|token|secret|key|password|authorization)` — with an explicit allow-list for schema keys that contain those words but carry numbers/enums (`input_tokens`, `output_tokens`, `cached_input_tokens`, `reasoning_tokens`, `token_source`, `token_accounting_note`, `model_name`, `queue_name`, `prompt_chars`, `completion_chars`, `model_kind`);
- drop any string value longer than 256 chars;
- replace path strings containing `/Users/<name>/` or `/home/<name>/` with `<home>/…`;
- `error_class` = exception class name only, never the message.
Unit tests: each pattern, the allow-list, the 256-char rule, nested dicts/lists, and a property test that no input string from a transcript fixture survives.

## 6. Prometheus

New instruments only with low-cardinality labels: `mdx_telemetry_runs_total{kind,status}`, `mdx_telemetry_stage_seconds{stage,backend,status}`, `mdx_telemetry_llm_tokens_total{backend,model_family,direction}`, `mdx_telemetry_write_failures_total{stage}`. No run/recording/job/tenant IDs as labels (those live in rows and traces).
