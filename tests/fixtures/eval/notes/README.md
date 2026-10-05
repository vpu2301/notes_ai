# Notes gold set — the committed, synthetic ten

Ten **synthetic** recordings with gold annotations: what a reader
would have to find in the note for it to have been worth reading. No real
people, companies or audio. They exist so `make eval-notes` runs on any
machine, in CI, and in a pull request — the metric code is exercised even
when the real corpus is not present.

| File | Language | Recording type | Why it is here |
|---|---|---|---|
| `m01`–`m05` | en, de, uk | meetings, a client call, a hiring debrief | v1 (Sprint 33): actions, owners, decisions |
| `m06_de_news_podcast` | de | podcast_broadcast | the synthetic twin of the 2026-09-22 audit (ZEIT "Was jetzt?"): host, correspondent, a sound bite, two stories with a cue-phrase switch, hedges, two ASR-mangled names, "heute", "am Montag … gewesen", "bis Mittwoch 0 Uhr", ≈ 3 000, a deadline |
| `m07_uk_lecture` | uk | lecture_webinar | a talk: no actions, one open question |
| `m08_en_one_on_one` | en | one_on_one | feedback, one explicit action with a date |
| `m09_en_voice_memo` | en | voice_memo | one voice, 2.5 minutes, a note to self (Q3: classified by rule) |
| `m10_de_interview` | de | interview | a journalist and an archivist; no actions, one hedged forecast |
| `m11_en_boat_walkthrough` | en | presentation_demo | F3's synthetic twin of the 2026-09-25 Pardo walkthrough: an invented yacht, eight figures with qualifiers ("a little over sixteen and a half", "just under two hundred and fifty"), a presenter with role and dealer, a call to action |

They are **not** the gold set the gates are measured on. That corpus
(`eval/notes/v2/`, target 100 recordings — concept §5) is real recordings
under the consent register plus third-party regression cases: it lives in
the eval bucket, never in git, and is passed with `--corpus`. Real
transcripts on a developer machine go in `scripts/eval/local/`
(gitignored).

## Format (v2)

Every v2 field is optional, so a v1 file is a valid v2 file.

```json
{ "id": "...", "language": "en|de|uk",
  "meeting_type": "team|client|sales|one_on_one|interview|auto",
  "recorded_on": "2026-09-22",
  "recording_type": "meeting|client_call|sales_call|interview|one_on_one|podcast_broadcast|lecture_webinar|voice_memo",
  "transcript": [{ "speaker": "SPEAKER_1", "t_start_ms": 0, "t_end_ms": 9000, "text": "…" }],
  "gold": {
    "key_facts":  ["one sentence per thing the note must carry"],
    "actions":    [{ "text": "…", "owner": "Priya", "due": "2026-09-25" }],
    "decisions":  ["…"],
    "open_questions": ["…"],
    "entities":   [{ "canonical": "Friedrich Merz", "surface_forms": ["Friedrich Schmerz"], "kind": "person|org|place|product" }],
    "hedged":     [{ "fact": "…", "modality": "forecast|estimate|plan|unconfirmed|opinion" }],
    "dates":      [{ "text": "am Montag", "resolved": "2026-09-21", "tense": "past|future|none" }],
    "speakers":   { "SPEAKER_1": "Imre Balzer" },
    "name_candidates": ["Imre Balzer"],
    "topics":     [{ "title": "…", "t_start_ms": 0 }],
    "must_contain": ["…"], "must_not_contain": ["November", "Teambesprechung"]
  } }
```

`make eval-notes-validate CORPUS=…` (`scripts/eval/notes_gold.py`)
refuses a file that contradicts itself: a surface form or a date phrase
that is not in the transcript, a `speakers` key nobody spoke under, a
`must_not_contain` string inside a gold key fact, an unknown key or
recording type. Problems name the file and the index, never the text.

`gold.speakers` names the transcript's speakers the way a person would in
the roster; the harness applies them to the result view it hands the
engine, exactly as the worker does. `recorded_on` anchors relative dates
(default `2026-01-15`).

## Regression checklists

`assertions/<id>.assertions.json` is the audit's checklist as data for
one recording — `r01_de_zeit_was_jetzt` (the audit itself; its transcript
is third-party and lives only in the bucket and `scripts/eval/local/`)
and `m06_de_news_podcast` (its synthetic twin, which runs in CI), plus `m09` and `m10` (Q3). A
`sprint` map says which Summary Engine v2 sprint owns each check.
`make eval-notes-assert BACKEND=dev_mac [CORPUS=…]`.

## Scoring

Content-word overlap against the gold text (≥ 0.6 of the gold fact's
content words), so wording is free and content is not: *"Priya sends the
release note to support by Thursday"* and *"Release note to support —
Priya, Thursday"* are the same fact. Owner accuracy is only counted on
actions that matched, because an owner on a line nobody wrote is not an
owner error. The audit metrics — unsupported lines, invented claims,
example echo, coverage by third, excluded speech, recording type,
redundancy, entities, hedges, attribution, dates — are defined in
`scripts/eval/notes_scoring.py`. Reports carry numbers and ids only.
