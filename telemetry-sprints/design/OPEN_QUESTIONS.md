# Open questions (answer at GATE 0)

Each has a proposed default; silence = default.

| # | Question | Proposed default |
|---|---|---|
| Q1 | **Branch/commit workflow.** The pack wants `feat/telemetry-sprint-<n>` + PR per sprint; the cleanup sprint ran uncommitted on `cleaning-branch` with the owner committing. | Owner commits the cleanup first; then the agent creates `feat/telemetry-sprint-0` from it and the owner commits/pushes each sprint (agent makes no commits, per CLAUDE.md "no AI authorship"). |
| Q2 | `recording_id := transcription_jobs.id` (no `recordings` table; 1:1 with `audio_files`). OK, or prefer `audio_files.id`? | `transcription_jobs.id` — clients already hold it, everything references it. |
| Q3 | Is a note **regeneration** a reprocess run of the recording (`kind=reprocess, reprocess_scope=notes`)? And a **rediarize** (`scope=diarization`)? | Yes to both. |
| Q4 | `trigger=auto` for the macOS/iOS pending-upload retry needs the client to say so. Add an optional form field `submission_trigger` to `POST /asr/jobs`, or accept `user` for all uploads? | Accept `user` for all uploads in v1 (no API change); revisit with client events (`upload_started.attributes.retries`). |
| Q5 | Client events tag runs by `recording_id` (+ `note_id`/`generation_id`) instead of a `processing_run_id` returned in API responses (adding a response field = shape change). OK? | Yes — server resolves the run at ingest. |
| Q6 | Telemetry tables without an FK to `transcription_jobs` (keeps the W5 note-move gate untouched; erasure deletes explicitly) vs FK + `LEFT_ALONE` entry. | No FK. |
| Q7 | When a note is moved/copied to another workspace (W5 rehome), does its recording's telemetry move too? | No — it stays in the tenant that processed it; platform admin still sees it. |
| Q8 | generation-service inline completion (Layer C) is not tied to a recording. Record per-run telemetry for it? | No per-run records; only Prometheus aggregates (`purpose=inline_completion` stays in the enum for future use). |
| Q9 | `provider_probe` runs 1–2 real completions before every note job (`worker.py:141-143`). Record them as `llm_call purpose=provider_probe` inside the run? | Yes — they cost time on the critical path and explain part of the wait. |
| Q10 | Platform admin role name and storage: `platform_admin` via new column `identities.platform_role`. | Yes. |
| Q11 | Dev-only login: new endpoint `POST /auth/dev/admin-login` (username `admin` → `admin@dev.notes-ai.test`) instead of relaxing the existing `EmailStr` password login. | Yes. Dev = `ENVIRONMENT ∈ {development, dev, local}` and `MDX_IDP_MODE ∈ {dual, native}`. |
| Q12 | Telemetry HTTP surface in note-service under `/v1/telemetry/...` and `/v1/admin/telemetry/...` (repo convention) instead of the pack's `/api/telemetry` / `/api/admin`. | Yes. |
| Q13 | Retention 90 days default; delete with the recording. Different value for prod? | 90 days everywhere; `MDX_TELEMETRY_RETENTION_DAYS`. |
| Q14 | Observed device: add probes (CTranslate2 `get_cuda_device_count`/`get_supported_compute_types`, `torch.cuda/mps`, whisper-server/diar-server have no device API → `configured`). Allowed to call these at worker start? | Yes, once per process at start; HTTP backends stay `observation=configured` unless the server reports a device. |
| Q15 | `execution_mode` detection: `/.dockerenv` or cgroup → `container`; `KUBERNETES_SERVICE_HOST` → `container`; HTTP model backends → `remote` for that stage's device; else `native`. | Yes. |
| Q16 | Is a native (non-Docker) asr-worker run on the Mac wanted for the M5 baseline (Sprint 5), or only Docker + native model servers? | Docker asr-worker with each ASR backend (`inproc_cpu_asr`, `dev_mac_asr` whisper-server Metal, `dev_mac_parakeet_asr`), since that is how dev runs today. |
| Q17 | The ASR stream has no heartbeat; a job running > 60 s can be reclaimed while alive (XAUTOCLAIM). Telemetry will show duplicate attempts if it happens. Fix it, or only observe? | Only observe in these sprints (out of scope; report it). |
| Q18 | Existing metric bugs found (ms buckets on `mdx_model_latency_seconds`; `mdx_note_generation_seconds_histogram` never recorded; `tenant_id` labels on audit/auth metrics). Fix inside these sprints? | No — list them in the report; separate fix. |
| Q19 | UNKNOWN: contents of `web/tests/fixtures`; audio fixtures in the macOS/iOS test targets. | Sprint 3 checks when writing client-event tests; fake recordings come from `one_second_of_audio()` and `probe_clip.wav`. |
| Q20 | `SPRINT_1.md` … `SPRINT_5.md` were not provided (only the overview and Sprint 0). | Paste them, or place the `telemetry-sprints/` folder in the repo root. |
