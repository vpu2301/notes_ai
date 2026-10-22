# ADR: Per-run pipeline telemetry in Postgres with deterministic reports

Status: Proposed (Sprint 0, 2026-10-22). Number to assign on merge (next free ADR number in the repo's ADR index).

## Context

Processing a recording takes about as long as the audio on the dev Mac (M5, 24 GB), and nothing today explains why. Timings that exist are partial and inconsistent: `metadata.infer_seconds` covers only `transcribe_runs`; the processor's `infer_seconds` starts before the audio fetch and includes VAD, LID and both recovery passes; diarizer/VAD/LID loads are lazy and untimed; `quality.rtf` (infer/audio) and `mdx_asr_realtime_factor` (audio/infer) are inverses; LLM usage drops cached/reasoning tokens; no manual spans exist and traces break at every queue; devices are only ever *configured*, never observed. The spec requires per-run, versioned, correlated, privacy-safe records that survive failures, plus a report without an LLM.

## Decision

1. A new workspace library **`libs/telemetry`** — schema models (v1), ID/ContextVar plumbing, a span context manager, `redact()`, a fail-open batched writer, runtime-context collector, report renderer.
2. **Own Postgres tables** (`telemetry_runs`, `telemetry_run_contexts`, `telemetry_spans`, `telemetry_llm_calls`, `telemetry_client_events`), additive migration `0092`, RLS like every tenant table, append-only spans.
3. `recording_id = transcription_jobs.id`; `processing_run_id` minted at submission / rediarize / regenerate; retries are attempts, not runs.
4. Propagation through optional fields on the existing queue payloads + a ContextVar; W3C `traceparent` carried the same way so Jaeger traces finally span the queue.
5. Reports are rendered by pure code from the stored record (same input → byte-identical Markdown), served by note-service; admin dashboard at `/admin/dashboard` behind a new `platform_admin` role; dev-only `admin/admin` via a dev-only login endpoint.
6. Prometheus gets only low-cardinality aggregates.

## Alternatives rejected

| Alternative | Why rejected (spec constraint) |
|---|---|
| OpenTelemetry-only (spans in Jaeger, no own tables) | Jaeger storage is ephemeral in dev and not access-controlled per recording; no `null + reason`, no per-run versioning, no retention tied to the recording, failed runs only as long as the collector keeps them. The spec requires persisted, versioned, ACL-inheriting records. OTel stays for traces; the run record carries the `trace_id` to link them. |
| Prometheus histograms per recording | Recording/run IDs as labels violate the low-cardinality rule and explode series; histograms cannot hold a span tree, nulls with reasons, or token accounting notes. |
| Extend `transcription_jobs.quality` / `note_generations.stats` JSONB | Couples telemetry to two services' row lifecycles, no span tree, no client events, rediarize overwrites `quality`, regenerations are separate rows with no run identity; schema versioning per blob is ad hoc. Existing fields stay untouched and keep their meaning. |
| Extend `model_usage` for LLM telemetry | It is a billing ledger (cost, tenant budgets, retention via `ai_retention`); LLM spans need TTFT, queue wait, accounting notes and run linkage. `llm_call` rows are written from the same `UsageRecord` hook, so both stay consistent without merging their purposes. |
| A separate telemetry service | One more deployable; every writer is already a Postgres client with the right tenant context. A library keeps writes in-process and fail-open. |
| ULID IDs | The repo uses UUID v4 everywhere; mixing ID styles breaks joins and conventions. |
| LLM-written diagnostic reports | Non-deterministic, can leak content, cost tokens; the spec forbids it. |
| Mint a new `recording_id` | The spec says reuse the recording PK; `transcription_jobs.id` is already the 1:1 anchor everything references. |

## Consequences

- Two nullable columns on existing tables (`transcription_jobs.processing_run_id`, `note_generations.processing_run_id`), two optional queue-payload fields, one optional `UsageRecord` extension, one new identity column and role — all additive; no endpoint shape changes (clients tag by `recording_id`).
- Workers gain ~10–20 instrumentation points; overhead budget < 1 % wall and < 50 MB RSS, measured in Sprint 5.
- The W5 note-move gate is not triggered (no FK to jobs/notes); erasure paths get one explicit delete each.
- The report becomes the single place where today's inconsistent rtf definitions are replaced by the glossary ones.
