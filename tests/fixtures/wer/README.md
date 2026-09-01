# WER reference corpus

Each subdirectory holds a manifest + audio file pair:

```
<lang>-<domain>-<id>/
    manifest.json   # see schema below
    audio.wav       # 8 kHz+ PCM/MP3/OGG; ≤ 30 min
```

`manifest.json` schema:

```json
{
  "audio": "audio.wav",
  "language": "uk",
  "domain": "finance",
  "vocabulary_hint": "Quarterly review. ...",
  "reference": "<gold-transcript text here>"
}
```

`vocabulary_hint` is the free-text hint fed to Whisper's
`initial_prompt` (product terms, names, jargon); it mirrors the
`vocabulary_hint` field on session start / job submit.

## Targets

- UK general ≤ 18% WER
- UK domain-specific with hint ≤ 14%
- EN general ≤ 10%
- EN domain-specific with hint ≤ 8%

Files are **not committed** until the content lead approves them.
For local testing, generate synthetic audio via the team-internal TTS
pipeline (see `docs/onboarding.md § wer-fixtures`).
