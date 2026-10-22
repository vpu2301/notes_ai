# Test recordings (fixed for the whole set)

**Status: waiting on the owner's audio.** Nothing below has been measured yet. The duration and sha256 columns get filled from the files themselves (`ffprobe` and `shasum -a 256`) once they are in place.

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

| Id | Duration | sha256 | Languages | Speakers | Capture mode | Notes |
|---|---|---|---|---|---|---|
| `de-2m` | ~2 min (pending) | pending | de | 2 | pending | |
| `en-2m` | ~2 min (pending) | pending | en | 2 | pending | |
| `uk-2m` | ~2 min (pending) | pending | uk | 1–2 | pending | |
| `mix-de-en-3m` | ~3 min (pending) | pending | de + en | pending | pending | ≥ 3 English passages of 3–10 s, ≥ 1 under 3 s; switches in `.switches.json` |
| `en-15m` | 15 min (pending) | pending | en | ≥ 3 | pending | primary speed reference. Could reuse the source of `f2e27fc8` (recording `7967deba`, already in dev MinIO) if the owner says where it came from and that reuse is permitted |
| `de-15m` (optional) | 15 min | — | de | ≥ 2 | — | |
