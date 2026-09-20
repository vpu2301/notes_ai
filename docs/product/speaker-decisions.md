# Speaker review — decision log

One entry per weekly review (runbook: `docs/runbooks/asr-worker.md#speaker-correction-rate`).
Numbers from `scripts/jobs/weekly_speakers.py` (`speakers-YYYY-WW.csv`,
`dimension = all` unless noted) and the "ASR Health" Speakers row;
definitions and approximations in `docs/product/speaker-metrics.md`.
Correction rate is a lower bound on the error rate (no edit = assumed correct).

| Week | Opened diarized jobs | Correction rate | Count error (mean abs / signed) | Edit mix (merge / reassign / re-run) | Re-run success | low vs high correction rate | Decision |
|---|---|---|---|---|---|---|---|
| 2026-W38 | 0 | — | — | — | — | — | First run (`make weekly-speakers`, dev DB, 2026-09-19): header only, 0 rows. The dev DB holds 12 jobs (11 complete, finished 2026-09-06 … 09-17), none diarized, 0 speaker edits, and `result_first_read_at` only exists since migration 0045 — so nothing is evaluable yet. Nothing to decide; the pipeline (migration 0046, report role, CSV, cron, alert) is in place. First real numbers need diarized jobs opened after 0045, 7 days old. |

## 2026-09-20 — Diarizer v2 adopted, hosted on a GPU endpoint

A Hugging Face token with the model terms accepted arrived, so the
bake-off Sprint 28 could not run finally ran. pyannote community-1 meets
the pre-registered rule on the test split (1–4 speakers 87 %, two-speaker
4/4, DER 0.182 against 0.378 — 52 % lower) and halves unattributed
speech, from 21 % to 9.5 %. Every file in the gold set improves.

It cannot run where the worker runs: **0.64–0.85 × audio on four CPU
threads** against a 0.25 budget, versus 0.13–0.15 × on a GPU. So hosting is shape B
— our own `deploy/diar-server` image on a scale-to-zero T4, roughly
$0.07–0.11 per audio-hour plus idle. ADR-0052 is Accepted and records
both, along with what the hop may carry (audio, hints, roster policy) and
what it may never carry (identifiers, text, embeddings).

Two things this does NOT settle:

1. **Nothing is measured on our own recordings.** The gold set is public
   files with four two-speaker files per split. The in-house set is still
   the first thing worth doing.
2. **The roster floor does not transfer to v2.** v2 barely over-counts,
   so an 8 s floor mostly dissolves quiet real speakers (81 % vs 88 %
   exact on dev). Calibrate per engine; that is trigger 3 of the guard
   exception below.

Rollout follows the ADR: shadow → dev/staging → pilots → default, with
`MDX_DIAR_ENGINE=legacy` as the rollback.

## 2026-09-19 — roster guard kept despite failing its ship rule

The Sprint 28 B-4 rule allowed ≤ 5 % of test files to under-count; guard
8 s / 3 % gives 13 % (2/16), so by the letter it should not have shipped.
Kept on by default as a recorded exception: one of the two under-counts
exists without the guard too, the other is the only new one on test
against seven over-counts fixed, and all two-speaker files become exact
(4/8 → 8/8). Over-count is the reported pain and costs two clicks to fix;
under-count is rarer and fixed by stating the count and re-running.
Per-file analysis, owner and revert triggers: ADR-0052 § "Roster guard vs
the Sprint 28 B-4 ship rule". First revert check: the in-house gold set.

## 2026-W38 (Sprint 32) — name suggestions shadow, legacy removal, GA gate

**Name suggestions (B-2 shadow): stay dark.** `scripts/ops/name_suggestion_shadow.py`
is ready (counts only, CI-guarded). Eligible jobs on 2026-09-19: **0** — no completed
job has calendar candidates and a person-chosen name (the dev DB holds no jobs;
there is no production data yet). The decision rule needs ≥ 100 compared labels
(or ≥ 40 plus 100 % on the gold set; the gold set has no self-introductions matched
to calendar invitees). Result: `MDX_NAME_SUGGESTIONS_ENABLED=false`; the endpoint
and clients are built and dark. Re-run the shadow after 30 days of calendar captures.

**Legacy batch clusterer (B-4): kept** — precondition not met (v2 never ran; no
production correction rate). ADR-0054.

### GA checklist

| # | Gate | Evidence | Status |
|---|---|---|---|
| 1 | Gold test split: 2-spk ≥ 95 %, 1–4 ≥ 85 %, ±1 ≥ 97 %, DER ≤ 15 % in-house, unattributed ≤ 8 % | **updated 2026-09-20 with v2**: 2-spk 4/4, 1–4 87 %, ±1 94 %, DER **0.182**, unattributed **9.5 %** (`der-2026-09-19-pyannote_c1-guard-test.json`). Legacy + guard was DER 0.378 / 21 %. Closer on every axis, still short of ±1 ≥ 97 % and unattributed ≤ 8 %, and **still no in-house files** | **fail** |
| 2 | Production 14 d, ≥ 100 opened jobs: correction ≤ 10 %, abs count error ≤ 0.2 | 0 opened diarized jobs (weekly CSV empty) | **fail** (no data) |
| 3 | `count_confidence=low` corrected ≥ 2× `high` | no data | **fail** → the low-confidence banner must be removed before GA unless data arrives |
| 4 | Load scenarios pass | scenario 4 pass for the legacy engine (2 h / 8 spk: 0.016 × audio, 1.66 GB); 1, 2, 5 not run (no staging). **v2 changes the shape of this gate**: it runs on an endpoint (ADR-0052 shape B), so the numbers to take are the endpoint's — none exist yet | **fail** |
| 5 | Alerts with rule tests: latency, re-run failures, correction rate, mono-fallback, engine load | `infra/prometheus/rules/speakers.yml` + `tests/speakers-test.yml` (all pass) | **pass** |
| 6 | Runbooks: asr-worker, speakers-eval, DSAR, model-pin upgrade | `asr-worker.md` (§ diarization-engine, rediarize, stranded, dual-channel…), `speakers-eval.md`, `asr-dsar.md`, `docs/models/PINS.md` (community-1 row, `--resolve-pins`) | **pass** |
| 7 | Egress test green with telemetry/model hosts blocked; no-embeddings schema test | schema test green in CI; egress test written, **not run** (needs the stack with the allowlist) | **fail** (unverified) |
| 8 | Tenant-isolation negatives for every route 28–32 in CI | merge/undo, rediarize/undo, reassign/reset, dismiss, name sources, erasure — unit + DB integration | **pass** |
| 9 | Decision log weekly + GA entry | this file | **pass** |
| 10 | Third-party notice reachable from the product | `docs/legal/third-party-notices.md` exists; the web app has **no Data page** to link it from | **fail** |

**GA: no.** Gates 1–4, 7 and 10 fail — mostly because nothing has run where it
matters yet (no v2, no staging, no production traffic), not because a measured
number came out bad. Per the gate rule: ship the correction loop as it is, keep the
low-confidence banner only until gate 3 has data, and take the concept §10 path —
get v2 running (HF token) and a staging deployment, then re-measure.

**Would we build the same thing today?** Mostly yes. The seam, the roster guard
and the correction loop earned their keep: the guard alone took legacy from 44 % to
88 % exact on the test split, and the gold-set replays caught four real bugs in the
hint paths that unit tests had passed. What we would do differently: get the v2
model, a staging environment and real calendar-sourced captures BEFORE building
features that are gated on them (v2 removal, name suggestions, the GA gate) — three
of this sprint's items could only end in "built, not measured".

### Debt found (file as separate issues; not fixed here)

| Item | Severity |
|---|---|
| `audio_files.retention_until` is never set or swept; audio is kept indefinitely — needs a retention decision (vs re-run availability) and a purge job | **P1 before beta** |
| `POST /asr/jobs` accepts `language ∈ {auto, uk, en}` while the web type allows `de` | P1 |
| macOS and iOS Swift sources are parallel copies — shared Swift package | P2 |
| ADR-0034/0045 cite `eval/conversations/v1`, absent from the tree — amend | P2 |
| `EcapaEmbedder.embed` is one forward pass per chunk (no batching) — still true for streaming | P2 |
| Web recorder uses browser-default AGC/noise suppression — measure on `web_opus` first | P2 |
| The dev DB lost its jobs/audio rows and two identities' bridge `users` rows (Sprint 30 incident: `libs/db` integration tests wipe tables) — `make check-identity-bridge` fails until repaired or re-seeded | P1 (dev) |
