# Correlation design

## 1. `recording_id` (reuse decision)

There is no `recordings` table (PIPELINE_MAP §10). One upload creates exactly one `audio_files` row and one `transcription_jobs` row, 1:1, and nothing later creates another: rediarize revisions, speaker edits, corrections, notes (`notes.source_asr_job_id`), meetings (`note_meetings.asr_job_id`) and note regenerations all hang off **`transcription_jobs.id`**.

**Decision:** `recording_id := transcription_jobs.id`. No parallel ID is minted.
- Clients already hold it (`POST /asr/jobs` returns it) and can tag events with it without any API change.
- `audio_files.id` is stored as `span.attributes.audio_id` on `capture_input`; it is not a second key.
- `note_meetings.client_capture_id` (client-minted at record press) is stored as a `client_event.attributes.client_capture_id` so pre-submission events can be joined after the job exists.
- Edge: an enqueue failure (`ENQUEUE_FAILED`, 503) makes the client resubmit, which creates a new job = a new recording. The failed one keeps its own run with `status=failed, error_category=queue`.

## 2. Where `processing_run_id` is minted

| Run | Minted in | `kind` / `reprocess_scope` / `trigger` |
|---|---|---|
| Initial | `submit_job` (`services/asr-service/.../routers/jobs.py:211`), right after `job_id = uuid4()` (:300), inserted in the same transaction as the job row | `initial` / null / `user` (upload) or `auto` (macOS pending-upload retry, from `X-Client-Type` + a new optional form field — see OPEN_QUESTIONS) |
| Rediarize | `rediarize` (`jobs.py:1742`) after `claim_rediarize` | `reprocess` / `diarization` / `user` |
| Note regenerate | `notes_generation.py:530` (regenerate) | `reprocess` / `notes` / `user` |
| Note generation of the initial run | **not a new run** — `attach_transcript` / `from-transcript` look up the job's open initial run and pass its id into `generation_service.start` | — |
| ASR retry (Redis redelivery) | not a new run — a new `attempt` on the spans | — |
| Note job retry (`JobRunner`, ≤ 5) | not a new run — `attempt` | — |

A run is the unit "the user asked for this to be (re)computed". Retries are attempts inside it.

## 3. Propagation

| Hop | Mechanism (additive) |
|---|---|
| asr-service → Redis stream → asr-worker | new optional field `processing_run_id` (+ `traceparent`) on `JobEnqueuePayload` (`libs/asr_models/src/asr_models/job.py:29`); old messages without it → worker looks the run up by `recording_id` |
| inside asr-worker | `contextvars.ContextVar` `current_run` set in `_process_one` / `_rediarize_one`; span API reads it; thread offloads (`asyncio.to_thread`) copy context automatically |
| asr job → note generation | `transcription_jobs` gets a nullable `processing_run_id` column (the current run); `attach_transcript` reads it; `generation_service.start` writes it into the `note.generate` job payload and `note_generations.processing_run_id` (new nullable column) |
| note-worker | `JobRunner` handler sets the same ContextVar from the payload |
| LLM wrapper | `libs/models` `UsageRecord` gains optional run/span ids from the ContextVar; a telemetry sink (Sprint 3) turns each record into `llm_call` + span. generation-service inline completion: request-scoped run? → no (no recording); recorded only as Prometheus, not as per-run telemetry (OPEN_QUESTIONS Q8) |
| clients | **no response-shape change.** Clients tag events with `recording_id` (the job id they already have) plus `note_id` / `generation_id` when they display notes; the ingest endpoint resolves the run: newest run of that recording whose scope covers the event (`notes_displayed` after a regenerate → the regenerate run) |
| trace | W3C `traceparent` is already the global propagator. The minting request's trace id is stored on the run and forwarded through the stream payload and the job payload, so worker spans join the same Jaeger trace (today they start new traces) |

## 4. Client events before a recording exists

`recording_stopped`, `import_submitted`, `upload_started` happen before `POST /asr/jobs` returns. The client keeps them in memory (macOS/iOS: also in the `PendingCaptures` sidecar, so a deferred upload keeps them) with `client_capture_id`, and sends them in one batch after the job id is known, together with `upload_finished`. If the upload never succeeds, they are sent with `recording_id = null` only if the client later reports `error_shown` — otherwise dropped (no run exists to attach them to).

## 5. Cancellation

- Who: asr-service `cancel_job` (`jobs.py:1946`). Queued job → the run goes `cancelled` immediately (`finished_at = now`). Running → `cancel_requested=true`; the worker's existing checks (`processor.py:353/404/532`, `_cancel_poller`, `_unless_cancelled`) raise into `_mark_cancelled`, which also closes the run.
- In-flight spans: the span API's context manager catches `CancelledError` and the worker's cancel exception and writes `status=cancelled, end_*` = now. On worker crash, the `started` begin-row (STORAGE.md §2) stays, and the run is closed by the retention/reaper job as `status=failed, error_category=unknown` with spans left `started` (evidence kept, not invented).
- Note side: a regenerate superseding a running generation (existing `superseded` handling) marks the old run `cancelled`.

## 6. Partial completion

Run `status` is derived from stage statuses:
- every required stage `ok` → `succeeded`;
- transcript persisted but diarization failed (`diarization_status='failed'`, job still `complete`) or notes failed → `partial`, `error_category` of the first failing stage (`diarization` / `llm`);
- nothing persisted → `failed`.
Per-span statuses carry the truth; the run status is a summary, never the source.

## 7. Clocks and the critical path

- Durations inside a process: `time.monotonic_ns()` (Python), `DispatchTime`/`ContinuousClock` (Swift), `performance.now()` (web). Never subtract wall clocks within a process.
- Span boundaries also carry wall UTC (`datetime.now(UTC)`, ms) so spans from different processes can be ordered; `clock_source` says which clock produced the duration.
- Clients: `client_wall_utc` (+ optional `client_monotonic_ns`); server stores `server_received_utc` and `estimated_clock_offset_ms = server_received_utc − client_wall_utc` at ingest. Stored, not applied retroactively. Client-derived timings (`user_wait_seconds`, `time_to_*`) are computed from client wall times of the **same client** (stop → displayed), so the offset cancels; offset is only used when mixing client and server times, and the report says so.
- **`processing_wall_seconds = max(end_wall_utc over backend spans of the run's critical path) − submitted_at`.** Σ span durations ≠ wall time: spans nest and overlap (LID inside ASR, diarization running after ASR, retries). The report renders the tree and never sums siblings. Critical path for an initial run: upload accepted → queue → audio_prep → vad → language_detection → asr_primary → asr_recovery → postprocess_* → diarization_* → persist → (client attach) → queue → llm_call(s) → persist. Read-time enrichment (`other/asr.result_enrich`) and shadow ASR are off the critical path.
- `asr_audio_processed_seconds` is a **sum** over `asr_primary.audio_processed_seconds` + `asr_recovery.audio_reprocessed_seconds` (+ segment-LID re-decodes), labelled as a sum in code, schema and report.

## 8. Concurrency facts

`concurrent_runs_at_start` = runs with `status=running` whose latest span `host` equals this worker's host, counted at run start (one indexed query). `other_model_activity` = overlapping `model_init`/`asr_*`/`diarization_*`/`llm_call` spans of other runs on the same host, plus native model servers the worker can see as busy (Ollama `ps`, `/health`), each with `overlap_seconds`; unknowns are not invented (empty list + reason).
