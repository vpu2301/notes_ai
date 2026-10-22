# Reading a diagnostic report

A diagnostic report (`diagnostics-<recording>-<run>.md`, from the note's ⋯ menu, the admin
dashboard, or `GET /v1/telemetry/runs/{id}/report.md`) describes **one processing run** of a
recording: the first processing (`initial`) or a later one (`reprocess`: speaker re-labelling or
a note regeneration). It is generated from the stored telemetry. Exporting one never re-runs a
model or reads audio. It holds timings, counts, backends and devices, and never transcript,
note or prompt text.

**Missing is not zero.** A value that was not measured is printed `— (reason)`:

| Reason | Meaning |
|---|---|
| `not_measured` | nothing measured it in this run (e.g. no client opened the note yet) |
| `unavailable` | the probe exists but got no answer (e.g. no build SHA in the image) |
| `not_supported` | the backend cannot report it (e.g. tokens/s from a remote API) |
| `not_applicable` | it does not exist for this run (e.g. model load time of a remote LLM) |
| `error` | the inputs contradicted each other (e.g. a client clock before submission) |

## The sections

1. **Run identity** — which run this is and how it ended (`succeeded`, `partial` = transcript
   stored but a later stage failed, `failed`, `cancelled`). `attempt` > 1 means the queue
   delivered the job more than once. **Hardware & environment** tells a container run
   (`execution mode: container`, Linux, the Docker VM's memory) from a native one. **Effective
   models & backends**: what actually ran. `Device source` is the key column. `observed` means
   the code asked the library which device it was running on. `configured` means only what the
   setting says, so treat it as unverified.
2. **End-to-end timing** — `processing_wall_seconds` runs from upload accepted to the last
   result stored, and is the number to compare. `rtf` = wall ÷ audio (lower is better; 1.0 = as
   long as the recording). The `time_to_*` and `user_wait_seconds` rows come from the client
   apps: they stay `— (not_measured)` until someone opens the note in the web or a native app.
3. **Stage table** — every span, nested (`·` per level), in start order. *Share of wall* counts
   only critical-path spans. A span marked `(parallel with …)` overlapped other work and shows
   `—¹`. Never add the durations up: parents contain their children, and stages can overlap.
4. **ASR breakdown** — VAD (how much speech, in how many runs), language checks (one per
   speech run plus one for the recording; each is a separate model call), the primary passes per
   chunk with their own rtf, recovery passes, and the totals. A **reprocessing ratio** above 1
   means recovery passes transcribed some audio twice.
5. **Diarization** — load vs inference, cold or warm, and whether it overlapped ASR.
6. **LLM usage** — one row per HTTP attempt to the model (a retry is its own row with its
   `attempt` number). A `*` on tokens means an estimate, not the provider's count.
7. **Memory & resources, missing measurements** — process RSS and swap at start → end,
   telemetry's own overhead, then every missing measurement grouped by stage. If anything is
   missing, the section starts with "Telemetry for this run is incomplete."
8. **Bottleneck summary** — **Measured** lists facts only. **Hypotheses** are rule-based
   (`libs/telemetry/src/telemetry/report_rules.py`). Each one names the measurement that
   triggered it, and a rule whose input is missing says "Not assessable".

## Spotting the usual suspects

- **Cold loads.** A `model_init` or `diarization.load` row with `state cold` and a load time.
  The ASR model loads when the worker starts (`startup_load_seconds` on `asr.model`), so a job
  submitted while the worker is still starting spends that time in `queue`, not in a load span.
- **Language checks.** Many `lid.run` rows, each taking several seconds, are a cost in their own
  right. They show up as `language_detection` in the top critical-path stages.
- **Reprocessing.** `asr_recovery` rows plus a reprocessing ratio above 1.
- **Queueing.** A large `asr.queue_wait` on the critical path means another job held the worker.
  A queue wait under a skipped `worker_job` (`redelivered_after_finish`) is a queue redelivery
  after the job had finished, and is not part of this run's time.
- **UI delay.** In the Measured list: `time_to_notes − processing_wall`, the time between the
  notes being stored and someone seeing them.
- **Device doubt.** `configured` next to a device, or the "may be running on CPU — unverified"
  hypothesis.
