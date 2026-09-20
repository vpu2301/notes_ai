# ADR-0052: Diarizer v2 — engine behind a seam, hosted on a GPU endpoint

Date: 2026-09-19
Status: Accepted (2026-09-20) — v2 measured; hosting shape B
Sprint: 29 (speaker labeling concept §4–§6); Sprint 28 was to settle this ADR and did not

## Context

The legacy batch diarizer (Silero VAD + ECAPA + average-linkage clustering,
ADR-0034/0045) overcounts: on the Sprint 28 gold set it named the right
number of speakers in about half the recordings, and a wrong count is the
single most visible speaker-labeling failure. Two questions had to be
answered before replacing it: **which engine**, and **where it runs**.

## Decision

1. **A narrow seam, not a backend registry.** `libs/diarization/protocol.py`
   defines one `Diarizer` protocol with three implementations in the same
   library — `LegacyEcapaDiarizer` (today's code), `PyannoteDiarizer`
   (in-process) and `HttpDiarizer` (the same pipeline, on an endpoint).
   Every engine returns the `OfflineDiarization` the worker's word-level
   attribution already consumes, so that code is unchanged. Rejected:
   replacing `diarize_offline` in place (no rollback, no shadow run), and
   routing through `libs/models` (it routes by workspace tier, which
   diarization does not need).
2. **v2 = pyannote `speaker-diarization-community-1`** (pyannote.audio 4.0,
   CC-BY-4.0): overlap-aware neural segmentation + VBx clustering, and it
   accepts a speaker count, which the product now asks users for. Pinned
   `<4.1`, weights baked and digest-verified at build and at load.
3. **On a GPU endpoint** (shape B, `MDX_DIAR_ENGINE=http`). Measured
   below: community-1 needs 0.64–0.85 × audio length on four CPU threads,
   three times the 0.25 budget, so shape A cannot host it on the
   staging worker. The endpoint is our own image (`deploy/diar-server`)
   running the same `PyannoteDiarizer`, so labels do not depend on where
   the model ran; `PYANNOTE_METRICS_ENABLED=false` and `HF_HUB_OFFLINE=1`
   are pinned on both sides and the engine refuses to load if either is
   off. Shape A stays in the code and is the right choice the day the
   worker gets a GPU — flipping `MDX_DIAR_ENGINE` is the only change.

   What the network hop costs, and what it must never cost: audio is a
   request body (lossless FLAC), held in memory for the call, with no
   tenant, job, user or filename beside it; the reply carries labels and
   counts, never embeddings. **A diarizer outage must not cost a user a
   transcript** — with a remote engine the job completes without
   speakers, the row records `diarization_status='failed'`, and the
   clients offer a re-run. (In shape A the same failure still fails the
   job: an engine that cannot load in-process means a broken deployment,
   and an operator should see it.)
4. **One roster guard for both engines**, and a human's count wins over it.
5. **Rollout by configuration**: shadow (`MDX_DIAR_SHADOW_ENGINE`) → v2
   primary in dev/staging → pilots → default; rollback is flipping
   `MDX_DIAR_ENGINE` back to `legacy`.

## Measurements

Gold set `eval/speakers/v1`, production code path (`scripts/eval/run_der.py`),
Apple M5 CPU. Count = exact speaker count; DER collar 0 with overlap.

Legacy engine only (v2 not yet runnable here), 16 files per split:

| Split | Config | Count exact (all) | 1–4 spk | 2 spk (4 files) | Over / under | DER |
|---|---|---|---|---|---|---|
| dev | legacy, no guard | 50 % | — | 50 % | 31 % / 19 % | 0.511 |
| dev | **legacy + guard 8 s / 3 %** | 69 % | — | 100 % | 0 % / 31 % | 0.509 |
| dev | exact count = truth (same-voice merge on, default) | 81 % | — | 100 % | 0 % / 19 % | 0.504 |
| dev | exact count = truth, merge off | 100 % | 100 % | 100 % | 0 / 0 | 0.541 |
| dev | guard + calendar cap `max = n + 2` | 69 % | — | 100 % | 0 % / 31 % | 0.503 |
| test | legacy, no guard | 44 % | — | 25 % | 50 % / 6 % | 0.382 |
| test | **legacy + guard 8 s / 3 %** | 88 % | 93 % (14/15) | 100 % | 0 % / 13 % | 0.378 |
| test | exact count = truth (merge on, default) | 94 % | — | 100 % | 0 % / 6 % | 0.384 |
| test | exact count = truth, merge off | 100 % | 100 % | 100 % | 0 / 0 | 0.388 |
| test | guard + calendar cap `max = n + 2` | 88 % | — | 100 % | 0 % / 13 % | 0.377 |

Hint rows re-measured 2026-09-19 after two fixes found by these runs (Sprint
29 review + Sprint 30 C2 replay): a stray chunk no longer takes a speaker
slot under a count, and "dust" is judged after the same-voice merge. The
calendar cap now equals the uncapped result on every file (C2 holds: it
never under-counts).

Reports: `docs/eval/der-2026-09-19-legacy-{full,guard,oracle,oracle-literal}-{dev,test}.json`.

Read with care: 4 two-speaker files per split is too few for a 95 % claim,
and the guard was chosen from the Sprint 28 grid, then only confirmed on
dev — not tuned on it. What the numbers do say: the guard alone takes the
legacy engine past the §6 count targets on test (93 % on 1–4 speakers,
4/4 two-speaker) at unchanged DER, so acceptance 1's count criteria are met
by legacy + guard; its DER criterion (≥ 30 % below baseline) is not — the
guard fixes counts, not boundaries.

**Product decision (E2 vs "never invent"), much smaller than first
measured.** Honouring a stated count literally (`hint_same_voice_merge=False`)
is 100 % exact on both splits at essentially no DER cost (0.388 vs 0.378 on
test); the safe default (merge on — an impossible count such as "3" for one
voice cannot invent speakers) is 94 % on test. Default kept safe; flipping it
is now a cheap call.

**v2 measured, 2026-09-20** (gold set `eval/speakers/v1`, 16 files per
split, production code path via `scripts/eval/run_der.py`, Apple M5; the
gated weights were fetched once with a token that accepted the terms and
pinned in `docs/models/PINS.md`):

| Split | Config | Count exact | 1–4 spk | 2 spk | Over / under | DER | Unattributed |
|---|---|---|---|---|---|---|---|
| test | legacy + guard (today) | 88 % | 93 % | 4/4 | 0 % / 13 % | 0.378 | 21 % |
| test | **v2 + guard** | 81 % | 87 % | 4/4 | 6 % / 13 % | **0.182** | 9.5 % |
| test | v2, no guard | 63 % | 67 % | 4/4 | 25 % / 13 % | 0.184 | 9.3 % |
| test | v2 + stated count | 94 % | 100 % | 4/4 | 0 % / 6 % | 0.179 | 9.3 % |
| dev | legacy + guard | 69 % | 73 % | 4/4 | 0 % / 31 % | 0.509 | 27 % |
| dev | **v2 + guard** | 81 % | 80 % | 4/4 | 0 % / 19 % | **0.245** | 10.7 % |
| dev | v2, no guard | 88 % | 87 % | 4/4 | 6 % / 6 % | 0.244 | 10.3 % |
| dev | v2 + stated count | 94 % | 93 % | 4/4 | 0 % / 6 % | 0.242 | 10.3 % |

Reports: `docs/eval/der-2026-09-{19,20}-pyannote_c1-{max8,guard,oracle}-{dev,test}.json`.

**The pre-registered rule (§5 of the concept) is met on the test split**
by v2 + guard: 1–4 speakers 87 % (≥ 85), two-speaker 4/4 (≥ 95 %), DER
0.182 against the 0.378 baseline — 52 % lower, where 30 % was asked.
Every one of the 32 files improves; the worst legacy file (far-field AMI,
DER 0.79) lands at 0.26, and a broadcast file at 0.95 lands at 0.10.
Unattributed speech more than halves, from 21 % to 9.5 %, which is the
number a reader actually feels: it is speech with no name against it.

**E3 (hosting) decided the shape.** Same recording, same code path:

| Host | Wall time ÷ audio | Budget 0.25 |
|---|---|---|
| Apple M5 GPU (MPS), v2 | 0.13–0.15 | pass |
| **4 CPU threads, v2** (the staging worker's shape) | **0.64 and 0.85** (two AMI meetings, mean 0.74) | **fail** |
| 4 CPU threads, legacy | 0.015–0.02 | pass |

A 30-minute meeting would occupy a worker for 19–25 minutes of pure
diarization, and the far-field recording — the harder one — is the slower
of the two. That is shape B, built in this sprint as B-9. (Two files, on a
laptop CPU rather than a cluster node: enough to settle a 3–5× miss, not a
number to quote.)

**The guard does NOT transfer to v2 unchanged.** It helps on test (three
AMI over-counts fixed) and hurts on dev (81 % vs 88 %): v2 barely
over-counts, so an 8 s floor mostly dissolves real, quiet speakers. It
stays on for now because it is still net positive over the 32 files
(81 % vs 75 % exact), and because the legacy engine — the rollback —
needs it. Calibrating the floor per engine is the first thing to do with
in-house recordings, and trigger 3 of the guard exception below.

**Roster guard vs the Sprint 28 B-4 ship rule — shipped as a recorded
exception (decided 2026-09-19).** The pre-registered rule was: over-count
rate falls ≥ 50 % relative, DER rises ≤ 2 points, and under-count stays
≤ 5 % of test files. Guard 8 s / 3 % on test: over-count 50 % → 0 % (met),
DER 0.382 → 0.378 (met), under-count 6 % → **13 % (2/16) — not met**. The
guard is on by default anyway (`MDX_DIAR_MIN_SPEAKER_SPEECH_MS=8000`).

Why, per file (`der-2026-09-19-legacy-{full,guard}-{dev,test}.json`):

- The 5 % bar was unreachable for any config: without the guard,
  under-count was already 6 % on test (`vc-bauzd`, 5 → 3) and 19 % on dev.
  `vc-bauzd` is identical with and without the guard.
- The guard caused **one** new under-count on test (`vc-azisu`, 4 true:
  6 → 3, DER 0.319 → 0.290) against **seven** over-counts fixed. Over both
  splits: 10 files fixed to the exact count; 3 files moved from over- to
  under-count (`vc-azisu`, `vc-afjiv` 7 → 4 of 5, `vc-ampme` 8 → 1 of 3 —
  the only file where DER got worse, 0.893 → 0.945, already unusable);
  1 already-under file lost one more (`ami-TS3003a-mix-headset` 3 → 2 of 4).
- All two-speaker files — the reported failure — go from 4/8 exact to
  8/8. Every new under-count is a 3–5-speaker broadcast or far-field file.

User-experience trade: an over-count is the symptom users report, happens
in half of all files without the guard, and is fixed in two clicks
(merge, small-speaker banner). An under-count is rarer here but hides a
person; the recovery is "set the number of speakers → re-run" (≈ minutes),
offered by the count banner only when `count_confidence` is `low` — and
`vc-azisu` came out `high`. We accept that for now.

Owner: Product + CTO. **Revert to the rule** (guard floor 0, record the
negative result) if any of these hold:

1. On the in-house gold set (Sprint 28 B-1, not yet recorded) the guard
   under-counts any two-speaker file, or under-counts more files than it
   fixes.
2. Production reassign/re-run-with-higher-count edits on guarded jobs
   exceed merge edits on unguarded jobs (weekly speakers CSV).
3. v2 ships and its own evaluation shows the guard no longer pays for
   itself on that engine.

**Measured on 2026-09-20** (above): v2 on dev and test, and E3 in both
hosting shapes. What is still **not** measured: the p95 of
`DiarizationStats.seconds / audio` on staging (`mdx_asr_diarization_audio_ratio`)
with the endpoint actually deployed, and anything at all on in-house
recordings — the gold set is public AMI and VoxConverse files, with four
two-speaker files per split, which is too few for a 95 % claim.

## Consequences

- **A second deployable and a GPU bill.** `deploy/diar-server` is ours to
  build, deploy, watch and patch. A scale-to-zero T4 is roughly
  $0.50–0.75 per GPU-hour, and at ~0.15 × audio one GPU-hour covers about
  seven hours of meetings — order $0.07–0.11 per audio-hour plus idle and
  cold starts. Cheaper than a commercial diarization API, and the audio
  stays with us, but it is a running cost where CPU time was already paid
  for.
- **A cold start on the first call.** `min_replica: 0` means the first
  diarized job of the day waits for the endpoint to wake (~4 min budget);
  the timeout allows for it, and the transcript is written first, so the
  user is not staring at nothing meanwhile.
- **One new egress destination**, in the allowlist and on the workspace
  Data page as a processor. The hub and pyannote's telemetry stay blocked
  on both sides.
- **The worker image still carries pyannote and its weights** so shape A
  stays a config flip away; that is the rollback if the endpoint is a
  problem, and it becomes the default the day workers get a GPU.
- Embeddings exist only inside `diarize()` (roster guard); a schema test
  fails the build if a vector ever reaches a stored artifact, and the
  wire format has no field for one.

## Re-open when

v2 misses the concept §6 count targets on our recordings, a pyannote
minor release changes the output attributes the adapter reads, the
workers get GPUs (shape A becomes the cheaper host), or the endpoint's
measured cost per audio-hour exceeds what a commercial API would charge.
