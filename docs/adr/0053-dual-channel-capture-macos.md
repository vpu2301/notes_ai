# ADR-0053: Dual-channel capture on macOS (microphone + call audio)

Date: 2026-09-19
Status: Proposed — built behind a fallback; the go/no-go spike has NOT been run
Sprint: 31 (speaker labeling concept §3 cause 3, §4 option E)

## Context

The macOS recorder tapped only the microphone. In an online call with
headphones the remote side was not recorded at all; over loudspeakers it
reached the file through room → mic, the hardest input a speaker embedding
gets. The gate for this sprint (no `call_speaker_bleed` files exist in the
gold set yet) was taken as met by the founder's go.

## Decision

1. **Capture: Core Audio process tap** (`CATapDescription(stereoGlobalTapButExcludeProcesses:)`
   + `AudioHardwareCreateProcessTap`, macOS 14.2+), excluding our own
   process, inside a **private aggregate device that also holds the default
   input** (the clock source), drift compensation on: one clock, both
   streams in one IO callback. One 2-channel 16 kHz FLAC, ch0 = mic,
   ch1 = call audio. Mic-only is the automatic fallback (setting off, notice
   not accepted, macOS < 14.2, tap failure). Rejected: ScreenCaptureKit
   (Screen Recording prompt; kept as the documented fallback), two engines
   (two clocks), a virtual driver (installation, sandbox).
2. **Server: the channel partitions the problem** (`libs/diarization/channels.py`,
   `dual_channel.py`). Per 20 ms frame: local | remote | both | none from
   per-channel VAD plus a loudspeaker **leak model** (delay by envelope
   cross-correlation 0–300 ms, gain as the median level difference, per
   5-minute window; local only when the mic is ≥ `6 dB` above the predicted
   leak; correlation floor `0.3`). Each side is diarized separately through
   the ADR-0052 seam; the merge puts local labels only on local/both frames
   and remote labels only on remote/both frames — a remote voice cannot
   carry a local label by construction. Double-talk goes to `overlap_ms`
   (uncertain turns). ASR stays one pass on the mixdown. Any exception in
   the channel path → the mono path on the mixdown, `mono_fallback`.
3. **One automatic name — a scoped exception to ADR-0034** ("the server
   never guesses who a speaker is"): exactly one local speaker with ≥ 10 s
   of speech, and the client sent `local_speaker_name` → that label gets the
   account owner's name with source `channel`, shown as "from your
   microphone", one click clears it, and `cleared` is carried through re-runs
   so it never comes back. Nothing else is ever named without a click.

## Spike (M-0) — record of the exit criteria

| # | Criterion | Result |
|---|---|---|
| 1 | Sandboxed tap receives non-silent buffers | **not run** (needs the app launched with a person at the Mac) |
| 2 | Permission prompt shown once, denial detectable, re-grant path | **not run**; note: a denied tap may deliver silence rather than fail |
| 3 | One callback, skew < 5 ms after 60 min | **not run** |
| 4 | CPU < 3 % of one core | **not run** |
| 5 | Device change mid-recording survivable | **not run**; code rebuilds the aggregate device (both channels pause briefly) |

The sprint continued without the spike on the founder's instruction; the
code is built so that every failure lands in mic-only capture. Until 1–3
pass on a real Mac, the call-audio setting must not be enabled for users.
`make-app.sh` signs without the sandbox entitlements (the XcodeGen build is
the sandboxed one) — the spike must use the sandboxed build.

## Measurements

- **Synthetic TTS calls** (macOS voices; 2 headphone + 2 loudspeaker calls,
  leak −18 dB / 40 ms, 1 local + 1–2 remote; legacy engine + roster guard):
  count exact 4/4, side accuracy 100 % outside double-talk, 0 remote frames
  labelled local, DER 0.054, RTF 0.05–0.09. The mono mixdown ALSO got every
  count right — the voices are too distinct to show the gain. This verifies
  the pipeline, not X2/X3.
- **Memory**, 2 h stereo (pink noise), Apple M5: decode + mixdown peak
  1.9 GB; + Silero channel analysis 3.0 GB, before any engine pass. The full
  dual path on 2 h is not yet measured against the 3.5 GiB budget.
- **Not measured:** X2/X3 and acceptance 4/5/12 need the `dual_channel`
  gold block (8 recorded calls, `rttm/<id>.sides.json` sidecars) —
  `run_der.py --dual` is ready for it.

## Consequences

- Recordings now contain other participants' clean audio → the consent
  sheet, the always-visible mode line and badge, and counsel review of the
  help page before GA (the help URL in the app is a placeholder).
- Two diarization passes per dual job; a silent side is skipped.
- The 6 dB margin and 0.3 correlation floor are starting values; tune on the
  dev recordings and record the tuned values here.

## Re-open when

X2 (side accuracy ≥ 98 % outside double-talk) fails on the gold block —
the next step is real echo cancellation, a separate decision.
