# Test recordings (fixed for the whole set)

**Status: built 2026-10-22, synthetic (macOS TTS).** No owner recordings were available, and the owner asked for the set to be found and made. `tools/asr_bench/make_tts_set.py` renders the scripted conversations in `tools/asr_bench/tts_set/*.json` with `say` (165 wpm, seeded pauses of 0.5–1.6 s between speakers, 16 kHz mono FLAC). A rebuild gives the same audio, assuming the same macOS voices.

What synthetic audio means for the numbers:
- **Speed numbers are valid.** Cost depends on duration, VAD runs and chunking, and the files are real speech audio of the right lengths. TTS has cleaner pauses than a meeting, so VAD may cut fewer, cleaner runs than real recordings would.
- **Quality numbers are a floor case.** TTS has no noise, no crosstalk and no hesitations. Drift between conditions still shows; absolute WER says little about real meetings.
- **Ground truth exists.** Each file has its scripted text, speakers and turn spans in `refs/<id>.truth.json`. True WER and true switch spans are therefore available in addition to the pseudo-reference drift.
- Owner recordings can replace any file later under the same id; the harness doesn't change.

## Location and naming (outside the repo)

```
~/asr-perf-audio/
  de-2m.<ext>  en-2m.<ext>  uk-2m.<ext>  mix-de-en-3m.<ext>  en-15m.<ext>  [de-15m.<ext>]
  mix-de-en-3m.switches.json     # the owner's switch timestamps, see below
  refs/<id>.json                 # pseudo-references (transcript text, never committed)
```

`run_matrix.py` finds `<id>.*` in `~/asr-perf-audio/` (or `$ASR_BENCH_AUDIO`).

## References: decision at Sprint A (owner, 2026-10-22)

There are no hand-corrected transcripts. The reference for each recording is the transcript of its **first counted warm `baseline-cpu` run**, frozen with `quality.py ref` into `~/asr-perf-audio/refs/<id>.json`. All quality numbers therefore measure **drift from the CPU baseline**, not error against the truth. The CPU path is deterministic: two runs of the same 120 s file (`ebf66ca8` vs `e3290649`) gave WER 0.000, timestamp Δ 0 ms and speaker agreement 1.000, so the baseline's run-to-run noise floor is zero.

The mixed file still needs the switch timestamps the sprint asks for. That's a few minutes of noting times, not transcript labelling. Format of `mix-de-en-3m.switches.json`: one entry per English passage, in seconds:

```json
[{"start_s": 31.2, "end_s": 38.9, "lang": "en"}, {"start_s": 74.0, "end_s": 76.1, "lang": "en"}]
```

## The set

| Id | Duration | sha256 | Languages | Speakers (voices) | Capture | Notes |
|---|---|---|---|---|---|---|
| `de-2m` | 113.87 s | `11115e3f70a65398…` | de | 2 (Anna, Reed de) | synthetic upload, FLAC 16 kHz mono | 13 turns, 242 words |
| `en-2m` | 113.85 s | `2b542c9516c85628…` | en | 2 (Samantha, Daniel) | same | 15 turns, 316 words |
| `uk-2m` | 114.00 s | `77007bec32fcd208…` | uk | 2 (Lesya; Lesya pitch × 0.82) | same | only one Ukrainian voice is installed, so speaker B is pitch-shifted |
| `mix-de-en-3m` | 178.25 s | `acbca3107f0ca60a…` | de + en | 2 (Flo, Rocko; de and en voices of each) | same | 4 English passages, below |
| `en-15m` | 892.39 s | `d0dfdd6fb33c01df…` | en | 4 (Samantha, Daniel, Reed en-US, Shelley en-GB) | same | 86 turns, 2,332 words; quarterly-planning meeting |
| `de-15m` (optional) | — | — | — | — | — | not built |

English passages in `mix-de-en-3m` (`mix-de-en-3m.switches.json`; exact by construction):

| # | Start s | End s | Length s | Class |
|---|---|---|---|---|
| 1 | 17.68 | 24.60 | 6.93 | ≥ 3 s |
| 2 | 59.10 | 65.98 | 6.88 | ≥ 3 s |
| 3 | 80.91 | 86.12 | 5.21 | ≥ 3 s |
| 4 | 101.59 | 102.98 | 1.39 | < 3 s ("Sounds good.") |

There are 4 real switches into English, so the C2 call limit for this file is 1 + 2 × 4 = 9.
