# Using `libs/telemetry`

Import name `telemetry` (workspace lib; add `"telemetry"` to the service's pyproject **and**
its Dockerfile's `uv pip install` list).

## Wiring (once per process)

```python
telemetry.configure(app_pool, enabled=settings.telemetry_enabled,
                    retention_days=settings.telemetry_retention_days,
                    app_commit=settings.build_sha or None)
...
await telemetry.get_store().close()   # in teardown, before the pool closes
```

Settings live in the service's `config.py` (`MDX_TELEMETRY_ENABLED`, `MDX_TELEMETRY_RETENTION_DAYS`,
`MDX_BUILD_SHA`) — libraries never read the environment.

## A run

```python
run = await telemetry.start_run(tenant_id=..., recording_id=job_id, kind="initial",
                                trigger="user", created_by=sub, audio_duration_seconds=...)
payload = JobEnqueuePayload(..., **telemetry.inject(run))          # run id + traceparent
# consumer:
run = telemetry.extract(payload.processing_run_id, tenant_id=..., recording_id=payload.job_id)
token = telemetry.set_run(run)
await telemetry.begin_run(run, effective_config=..., device_asr=...)
...
await telemetry.finish_run(run, result_stored=True, stage_statuses=[(stage, status), ...])
telemetry.reset_run(token)
```

Retries are new `attempt`s on spans, not new runs. `finish_run` closes a run once; a redelivered,
already-finished job leaves it as it is.

## Adding a span

```python
with telemetry.span("vad", "vad.speech_runs") as s:          # or `async with`
    runs = vad.speech_runs(pcm)
    s.update(backend="silero", run_count=len(runs), speech_seconds=total, ...)
```

- `stage` is one of the 18 stages in `SCHEMA_v1.md`; `name` is the code-level name.
- Exceptions mark the span `error` (or `cancelled`), record the class name only, and are
  re-raised unchanged. Parent = the enclosing span (context var; survives `asyncio.to_thread`).
- Overlap is recorded, never summed: `s.parallel_with.append(other.span_id)`.
- Outside a run, a span times itself and writes nothing.

## Adding an attribute

`s.set(key, value)` / `s.update(**values)`. The required keys per stage are in
`telemetry.schema.STAGE_KEYS`; add a new key there **and** in `SCHEMA_v1.md` +
`telemetry_v1.schema.json` (bump nothing — readers tolerate extra keys; a renamed or removed key
is a schema-version bump).

## Rules

- **Missing is not zero.** Not measured → `s.missing("threshold", "not_supported")`. A required
  key you never set is stored as `null` + `not_measured` automatically. Never write `0` for an
  unknown value; validation rejects a value and a reason together.
- **Observed vs configured.** Pass the loaded library object to `telemetry.observe_device(obj,
  configured)` (faster-whisper `WhisperModel`, a torch module). Only a value read from the backend
  at runtime is `observed`; a wrapper holding a configured string, or a backend name, is
  `configured`. HTTP backends are `configured` unless the server reports its device.
- **Privacy.** Store counts, durations, lengths, enums, ids and hashes — never audio, transcript
  text, prompts, note content, names, credentials, raw bodies or user-name paths. `redact()` runs
  on every attribute and config before storage (drops content/secret keys, strings > 256 chars,
  URL userinfo, home-directory names), but do not rely on it: don't put content in.
- **Fail-open.** Nothing in `telemetry` raises into the caller; failed writes are counted in
  `mdx_telemetry_write_errors_total{entity}` and logged at most once a minute per entity.
- **Metrics.** Low-cardinality labels only (`stage`, `backend`, `status`, `kind`,
  `model_family`, …). Run/recording/job/tenant ids go in rows and traces, never labels.
- **Clocks.** Durations from `time.monotonic_ns()`; wall UTC only to order spans across
  processes. `processing_wall_seconds = max(end_wall) − submitted_at`, never Σ spans.

## Known limits (Sprint 1)

- A job that exhausts its retries (DLQ) leaves its run `running`; the nightly retention job
  closes runs with no activity for 6 h as `failed / unknown`. Sprint 2 hooks the DLQ path.
- Overhead is measured per process; the asr-service share (`start_run`) is not added to the
  worker's figure yet.
