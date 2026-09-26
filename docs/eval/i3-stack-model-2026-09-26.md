# Sprint I3 acceptance on the stack model — 2026-09-26

**Model:** `notes-chat` (Gemma 3 4B, Q4_K_M) on the dev Mac through Ollama. **Tool:**
`make eval-notes-assert BACKEND=dev_mac`. **r02:** built from this branch's own re-transcription
of the Pardo job (F1 `floor_second`), held under gitignored `scripts/eval/local/r02/` — the
recording is third-party content. One run each; the model's output varies from run to run, so a
single check can flip between runs.

## Checklists

| Meeting | Before the stack-model fixes | After |
|---|---|---|
| r02 (Pardo) | 6 / 11 | **8 / 11** |
| m11 (synthetic walkthrough) | 6 / 11 | **10 / 11** |
| m06, m09, m10 | 16/23, 6/9, 6/10 | 16/23, 6/9, 5/10 (Q2–Q4 model checks, unchanged by F1–F3) |

**r02 passes:** every line cited, no copied line, no line without information, no citation
mark in the text, "incredible" / "crowded boat" absent, a Contact line, figures cited.

**r02 fails:**
- `figures` — the checklist's two figures are the 66 ft length (written in the passing runs)
  and "just under 300 gallons" of water (written in one run, not in the last). Per-line answers
  of the 4B model vary; the engine drops a figure whose words it cannot verify rather than keep
  a guess.
- `presenter_line` — the engine writes "Presenter: Mitchell, broker with Springbrook Marine
  Group (dealer for all of the Great Lakes)": the words that were said. The checklist holds the
  work order's paraphrase, "(Pardo dealer for the Great Lakes)"; a verified line cannot say
  "Pardo dealer" where the speaker said "Pardo Yachts dealer for all of".
- `topics[0]` — no swim-platform topic: the model extracted too few facts about the platform
  for the reduce step to form a topic (F2 keeps copies as evidence; the restate answer's quotes
  did not match the transcript).

**m11 fails:** `figures` — 5 to 7 of 8 figures come back verified depending on the run; the
checklist needs 7 with their qualifiers.

## What the checks do not show

- The notes eval's recall gate for F2 was not re-run after the F2 tuning in 7759f84 (the
  2026-09-26 report of the as-built F2 is `notes-pipeline-2026-09-26-dev_mac-f2-as-built.json`).
- The blind pairs (F2 topics, F3 r02) need human raters and were not run.
