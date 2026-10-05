# ASR entities (Sprint TQ3) — one name, one spelling

**Status: the acceptance measurement has not been run.** `eval/asr/v1` has no
labelled recording (TQ1 T2 is open), so `entity_consistency`, `wrong_merges`
and the proposal accept rate per language are **not measured**. There has been
no reviewer pass on a dev split, so the accept rate has no number. The harness
is ready.

```
make eval-asr BACKEND=<backend> SPLIT=test LABEL=tq3
```

Entities are now scored on the **applied view**, the transcript as every reader
gets it with the overlay's accepted corrections applied. The raw artefact's
numbers sit beside them as `entity_consistency_raw` and `entity_error_rate_raw`.
`wrong_merges` counts clusters that rewrote an occurrence of another gold
entity. The r03/r04 entity checklists are no longer expected to fail.

## What was measured (synthetic, not evidence for acceptance)

**Unit fixture.** The r04 spellings ("Handala" ×5, "Handela" ×2, "Andala",
"Hand aller", "Handler") form one cluster, Handala, confidence 0.853, accepted.
"Handler" is a common word in the de ∪ en list, so it joins only when the
glossary names it (`heard_as`). Inflections ("Lagersystem/Lagersystems",
"Петро/Петра"), numbers and role words are never merged. Attendees "Müller" and
"Miller" are never merged. `services/asr-service/tests/unit/test_entity_unify.py`
has 17 tests.

**Real decodes on the dev Mac (whisper.cpp turbo).** Five TTS files ran: de, en,
uk, the mixed file, and a German file naming "Handala" eight times and
"Welchering" three. The unifier formed **0 clusters** and made **0 wrong merges**.
Entity consistency was 1.0 and entity error 0. Clean TTS gives the decoder
nothing to mishear, so this measures precision (no false merges on real output),
not recall.

**Time.** A synthetic hour (900 segments, 10 800 words of German, 30 %
capitalised) took 0.08 s on the dev Mac. The budget is 2 s per audio hour.
Runs over it are dropped as `skipped_budget`.

## Findings

- **Search.** The search index (`note_versions.search_vector`) covers the
  note's rendered text, never the transcript. Notes are built from the applied
  view, so they already carry the unified spelling. No issue is filed, because
  search never reads the raw artefact.
- **Glossary learning.** It goes through the existing `POST /v1/glossary`
  merge, which is capped at 8, de-duplicated and never stores the term itself.
  The next job's `vocabulary_hint` deliberately carries only the canonical term
  (Sprint I2): the transcriber is told the right spelling, and the learned
  variants reach the next job through the unifier's glossary read, as exact
  `heard_as` matches.

## The three clusters the algorithm got wrong

None of these came from real recordings; they were found while building the
fixtures. Each is now covered by a rule and a test.

1. **"Bei Handala", "Handala ist"** attached to the Handala cluster as two-word
   variants. Applying them would have rewritten "Bei Handala" to "Handala". The
   fix: a two-word span attaches only when neither word is a member, or near
   one.
2. **"Hand"** joined Handala under a glossary prior. Jaro–Winkler's prefix bonus
   rated it 0.91. The fix: a form under 70 % of the target's length is never a
   variant.
3. **"Lagersystems" into "Lagersystem"** (and "Петра" into "Петро"): grammatical
   forms of one word, which German and Ukrainian decline. The fix: a
   language-specific inflection guard means they are never merged.
