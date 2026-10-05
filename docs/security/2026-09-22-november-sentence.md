# 2026-09-22 — "Der Start im November bleibt das Ziel"

**Status:** closed · **Class:** prompt echo, not an isolation incident · **Closed by:** Summary Engine v2, Q1 T4

## Symptom

The generated note for a German news podcast (ZEIT "Was jetzt?", 22.09.2026) contained the sentence
*"Der Start im November bleibt das Ziel"*. Nothing like it is in the recording. The question raised by the
audit: is this another workspace's meeting leaking into the note?

## Trace

1. The sentence is the literal example in the German summary prompt: `REDUCE_SUMMARY_SYSTEM["de"]`
   (`services/note-service/src/note_service/domain/meeting_doc/prompts.py`, `fbba745` L299–300):
   *Nenne Ergebnisse, nicht den Gesprächsverlauf: „Der Start im November bleibt das Ziel“, nicht …*.
   The extraction shots carried "November launch" as well, and the extraction rules an example about
   sanctions against Russia — one topic away from the recording.
2. The summary step kept a sentence when it cited any known fact id and its numbers were supported
   (`pipeline._summary`). The example has no number, so a copied example citing a real id passed.
3. No cross-tenant path exists:
   - the reduce steps receive only `prompts.facts_block` of the facts verified **in this run**; they never
     see a transcript;
   - the worker reads its transcript snapshot by `generation.snapshot_key` with
     `aad=generation_id.bytes` (`jobs/generate_note.py`), so a job can decrypt only its own snapshot;
   - the snapshot is deleted after the run.

## Conclusion

**Not an isolation incident.** The model copied its instructions. No tenant data crossed a boundary.

## What changed (Q1)

- Every example in every prompt, in all three languages, is now about one invented subject — the board game
  company "Quillhaven", its game "Ferrytale", the "Lantern edition" — defined once in `prompts.EXAMPLES`.
  The context prompt's type list no longer opens with a meeting type.
- `prompts.EXAMPLE_PHRASES` is built from those same strings: every 4-gram with at least three content
  words, plus the two invented names. It holds prompt text only, never recording content.
- The pipeline drops any summary sentence, topic title, topic bullet or framing sentence that repeats an
  example (`stats.example_echo_dropped`), and `verify_facts` drops any fact whose text does
  (`facts_dropped_example`).
- `PROMPT_VERSION` = `2026-10-6`; its fingerprint over all prompt text and schemas is pinned in the tests.

## Tests that keep it closed

`services/note-service/tests/unit/test_meeting_doc_prompts.py`:

- `test_an_echoed_example_never_reaches_the_note`: a scripted model returns the German example as a summary
  sentence citing a real fact; the note does not contain it and the drop is counted.
- `test_prompts_carry_only_this_recording`: two recordings run in one process. Every extract prompt's data
  block is one of that run's windows; every reduce prompt lists only facts verified in that run; no prompt
  or system string of either run carries a phrase of the other recording.
- `test_no_example_phrase_appears_in_any_fixture` and `test_prompt_version_changes_with_prompt_text`.

The eval reports `example_echo` per run (`scripts/eval/notes_scoring.py`); the nightly job fails on any
value above zero.
