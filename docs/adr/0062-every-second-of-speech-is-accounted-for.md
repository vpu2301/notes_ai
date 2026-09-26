# ADR-0062 — Every second of speech is transcribed or accounted for

**Status:** Accepted · **Date:** 2026-09-26 · **Sprint:** F1 ("From the first second") ·
**Trigger:** the Pardo 65 GT recording, whose stored transcript began ≈ 45 s late
(`docs/eval/i3-pardo-2026-09-25.md`)

## Context

Speech can vanish between "Record" and the transcript in three places: audio that never
reached the file (capture start latency), speech VAD did not hear (level or model), and speech
the decoder replaced with its prompt. Until now none of the three was measured, and a missing
opening looked exactly like a quiet one.

## Decisions

1. **Coverage is measured on every job and shown to the person.** `diagnostics.coverage` in the
   artifact, `coverage` on `/result`, `coverage_share` on the job view (read from the row's
   metadata JSON, so migration 0063 adds only the two capture columns). A gap is a VAD speech
   run of ≥ 3 s covered by surviving words for < 50 % of its length; each has a cause
   (`no_audio`, `no_speech_detected`, `decoder_empty`, `prompt_echo`, `other_language`,
   `unknown`). The Transcript tab on web, macOS and iOS says "Not transcribed: 00:00–00:44
   (audio started late)". Offsets and counts only, never text.
2. **Clients report when Record was pressed and when audio first flowed.** `record_pressed_at`
   and `first_frame_offset_ms` on `POST /asr/jobs` (0063), stored on the job; an offset of ≥ 3 s
   is a `no_audio` gap in Record-press time, outside the speech totals. The capture screen says
   "Starting…" until the first frame and "Recording from 0:03" beside the counter when the
   offset is ≥ 1 s.
3. **Decode twice on suspicion.** A run the first decode left empty, covered < 50 %, or > 30 %
   echo is decoded again without the prompt, without conditioning and with beam ≥ 5; the
   attempt with more non-echo words wins, and a second attempt under 0.4 mean word
   probability is never kept. One budget covers both passes (multiplier × 1.3; reaper running
   grace 11 h → 14 h to stay above it).
4. **VAD gets a floor, not a threshold change.** When VAD hears < 20 % speech but the rest is
   louder than −45 dBFS, VAD runs again at threshold 0.35, per channel for a mic/system file,
   and the union is used.
5. **A 300 ms leading pad** on every run, clamped to the previous run's end.

## Deviations from the work order

- **Coverage and the second pass run in the processor, for every backend** — not inside
  `inference.transcribe`. Dev and hosted ASR are HTTP servers that decode the whole file and
  never see the worker's VAD (the ADR-0061 precedent). The processor runs VAD once more for the
  measurement (per channel for stereo) and re-decodes a lost run through the same provider with
  a new `second_pass` flag; the in-process engine then skips VAD and language ID for that slice
  and decodes it whole with the decision-3 options, an HTTP backend honours "no prompt" only.
  The in-process engine's own VAD gets the pad and the floor (on the mixdown).
- **Splicing is word-level**: an HTTP segment can straddle a good run and a lost one, so only
  words inside the re-decoded slice are replaced.
- **Short runs (< 3 s) are never decoded twice**, whatever their coverage: a prompt-free decode
  of a breath is where Whisper writes "Thank you." The confidence floor in decision 3 is the
  same guard for longer runs.
- **Metrics:** `mdx_asr_speech_ms_total` is added as the denominator of the alert
  `AsrUncoveredSpeech` (uncovered share > 5 % over 1 h, `no_audio` excluded — it is the
  clients'). A second pass that times out is `cause="timeout", outcome="empty"`.

## Consequences

- A person sees why part of a recording has no text, and support sees the share per job.
- Inference can cost more on recordings the first decode handled badly; the budget and the
  reaper grace were raised for it, and the eval report measures it.
- With the Silero stub (dev without silero-vad) the whole file is one run and coverage is
  complete by construction (`coverage.vad = "stub"`); no second pass runs there.

Measurements: `docs/eval/asr-coverage-2026-10.md`. Runbook: `docs/runbooks/asr-worker.md#coverage`.
