# ASR coverage fixtures (Sprint F1)

Transcription-level regression cases, separate from the notes gold set
(`../notes/`, whose schema refuses unknown keys).

| File | What it is |
|---|---|
| `m12_en_late_start.json` | Synthetic. Audio is built from the bundled probe clip at the levels in `audio`; `truth` is the scripted transcript. The first decode writes the prompt back over everything before `first_pass.echo_until_ms`. Run in CI by `services/asr-worker/tests/unit/test_late_start_regression.py` with a scripted engine and real Silero VAD. |
| `assertions/r02_en_pardo_65gt.assertions.json` | Checklist for the real 2026-09-25 recording. The audio is third-party content and never enters git; `scripts/eval/coverage_eval.py --incident-job <id>` runs it on the dev stack. |

Assertion vocabulary, shared by both:

- `coverage_min_share` — `coverage.transcribed_ms / coverage.speech_ms` must reach it.
- `must_contain_before_ms` — each `text` must occur (case-folded) in a segment that starts before `before_ms`.
