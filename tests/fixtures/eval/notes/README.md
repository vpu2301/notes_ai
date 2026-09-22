# Notes gold set — the committed, synthetic five

Five **synthetic** meetings with gold annotations: what a participant
would have to find in the note for it to have been worth reading. No real
people, companies or audio. They exist so `make eval-notes` runs on any
machine, in CI, and in a pull request — the metric code is exercised even
when the real corpus is not present.

They are **not** the gold set the GA gates are measured on. That corpus
(`eval/notes/v1/`, 60 test-split meetings stratified by type, language and
duration) is real recordings under the consent register: it lives in the
eval bucket, never in git, and is passed with `--corpus`.

Each file:

```json
{ "id": "...", "language": "en|de|uk", "meeting_type": "team|client|sales|one_on_one|interview|auto",
  "transcript": [{ "speaker": "SPEAKER_1", "t_start_ms": 0, "t_end_ms": 9000, "text": "…" }],
  "gold": {
    "key_facts":  ["one sentence per thing the note must carry"],
    "actions":    [{ "text": "…", "owner": "Priya" }],
    "decisions":  ["…"],
    "open_questions": ["…"]
  } }
```

Scoring is content-word overlap against the gold text (≥ 0.6 of the gold
fact's content words), so wording is free and content is not: *"Priya
sends the release note to support by Thursday"* and *"Release note to
support — Priya, Thursday"* are the same fact. Owner accuracy is only
counted on actions that matched, because an owner on a line nobody wrote
is not an owner error.
