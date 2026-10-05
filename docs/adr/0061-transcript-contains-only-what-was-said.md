# ADR-0061 — A transcript contains only what was said

**Status:** Accepted · **Date:** 2026-09-25 · **Sprint:** I2 · **Trigger:** the 2026-09-25
incident and its audit (`docs/security/2026-09-25-isolation-audit.md`)

## Context

The workspace glossary is Whisper's `initial_prompt` on every recording. Over audio the decoder
cannot read — silence, a breath, speech in another language — it writes the prompt back. On
2026-09-25 that put speaker role labels from earlier notes ("Gysi, Moderator II, moderatorin,
narrator, speaker background") into a new transcript, fused with real speech, and rendered a
Ukrainian aside as an English paraphrase. Nothing crossed a workspace; the vocabulary did what
it was built to do with input nobody meant as vocabulary, and the guard only caught
whole-segment echoes over non-speech.

## Decisions

1. **Vocabulary is a whitelist of things worth spelling, not a log of renames.** A term is
   vocabulary only if some token is not a role word or ordinal, and a person has a capital
   letter somewhere (`glossary.is_vocabulary`). The server refuses the rest
   (`term_not_vocabulary`), the clients never offer to remember them, and the hint skips stored
   ones — so the affected workspace needs no data migration. The tables live in one fixture
   (`tests/fixtures/glossary/role_words.json`); every copy has a test against it.
2. **What the transcriber was told is stored with the job.** `transcription_jobs.vocabulary_hint`
   (0061), tenant data under RLS, erased with the job, served to the job's workspace only. The
   audit event carries the count.
3. **Echo detection is lexical and positional, not confidence-gated.** A run of ≥ 3 consecutive
   prompt tokens (repeats allowed, one filler allowed) at a segment start or after a 1.5 s pause
   is removed at word level; a prompt term said once mid-sentence stays. The guard only removes
   words. **Deviation from the sprint:** it runs in the worker's processor on every backend's
   output (`asr_worker/echo.py`), not inside the in-process engine's `_run_chunk` — the dev and
   hosted backends are HTTP services that never execute engine code, and the incident's own dev
   stack transcribes through one.
4. **A chunk is decoded in its own language when it clearly is not the recording's.** Per VAD
   chunk ≥ 2 s: language ID; another language only when it is one the product transcribes
   (en, de, uk), at p ≥ 0.6, with the recording's ≤ 0.2. **Deviation from the sprint's 0.8:**
   T7 measured clean Ukrainian at uk 0.75 / ru 0.18 (related languages share the mass) with
   en 0.002 — the second bar is what stops a stray word from flipping, the first only has to
   say which. The supported-language gate is new: Whisper's detector called accented English
   "Welsh" on VoxConverse and decoding that as Welsh would replace speech with noise. The
   segment carries `language`; `task` is always `transcribe`. In-process engine only; HTTP
   backends leave the field unset and the note engine keeps its script heuristic for those.
5. **`condition_on_previous_text` stays on for batch chunks** (`MDX_ASR_CONDITION_PREV`, default
   on). **Deviation from the sprint's "off":** T7 ran both on the incident recording — with
   conditioning off, conversation chunks (which get no punctuation model, G0) came back as
   lower-case run-ons ("boat for those that don't know my name is Mitchell I'm a broker…"), the
   very symptom I3 §1 lists; with it on, the sentences hold. The cascade conditioning amplifies
   is contained by decisions 1 and 3, and the switch remains for a workspace that echoes anyway.
   `hotwords` is a measured variant (`MDX_ASR_VOCABULARY_MODE`), not the default.
3b. **The echo rule is term-aware.** A run of ≥ 3 prompt tokens is removed only when it spans two
   or more prompt *terms* (repeats included) or writes a word twice; one multi-word term said once
   at a segment start ("of Williams Jet Tender that you can have in this boat", the incident
   recording) is the presenter naming the product and stays — T7 caught the guard removing it.
6. **Per-segment language is a first-class field** through the result view (segment, turn,
   `diagnostics`) to the note engine, which flags and confirms `other_language` from it by code,
   and to the Transcript tab, which tags the passage instead of hiding it.

Rejected: removing the hint (it is what fixes customer and product names); an LLM pass to clean
transcripts (a model editing the evidence layer is the failure class being fixed); enforcing
prompt *order* in the echo rule (fragile against repeats; the run-length and position rules
catch the incident and the silence case without it).

## Consequences

- A rename to a role label is no longer remembered anywhere; the affected workspace's seven
  terms stop reaching the transcriber the moment the service deploys.
- A presenter who reads three or more glossary names in a row at the start of a sentence loses
  them from the transcript; the diagnostics say where, and the job can be re-run without a hint.
- Per-chunk language ID costs one encoder pass per chunk ≥ 2 s on the in-process engine.
- Older artifacts and HTTP backends have no `language`/`diagnostics`; every reader defaults.

## Trigger conditions for revisiting

- `AsrPromptEchoRate` fires after the vocabulary rule: the run-length rule is too loose or a
  backend regressed.
- T7's report shows WER worse by more than 0.5 pt with conditioning off: turn
  `MDX_ASR_CONDITION_PREV` back on and rely on the guard alone.
- A bilingual workspace reports flips: raise the chunk threshold or turn chunk LID off per
  environment.

## Amendment (2026-09-30, Sprint TQ2) — every backend, and what decision 5 now covers

**Decision 4 now runs in the worker for every backend.** `asr_worker/chunks.py` holds the
rule, moved from `inference.py`, not copied. The worker runs VAD once and plans speech runs
(≤ 30 s, merged < 500 ms). It identifies the recording's language and each run's, then hands
the backend `SpeechRun`s, each with its own language. The thresholds are unchanged.
`asr_inproc` uses the engine's own model, so its behaviour is unchanged. `asr_http` gets the
recording's language from the backend itself: one request on a 30 s speech sample, so the
production model decides, as it did when it was sent the whole file. Each run's language comes
from a local faster-whisper **tiny** (`MDX_ASR_LID_MODEL`, baked in the CPU image, 0.2 s per
run on CPU). Tiny scores clean Ukrainian at 0.63. The rule tolerates that: a run switches only
when the recording's language is ≤ 0.2, so a weak uk score keeps the run in uk. The last
sentence of decision 4 ("In-process engine only; HTTP backends leave the field unset") is
withdrawn.

HTTP backends receive only speech. Runs of one language are joined with 300 ms of silence into
groups of at most `MDX_ASR_HTTP_GROUP_SECONDS` (300 s), one request per group, and timestamps
are mapped back (`models.run_groups`). Silence the decoder never hears cannot become
"Vielen Dank.". On the TQ2 smoke file, whisper.cpp wrote exactly that over a 20 s silent tail
when sent the whole file, and nothing once sent the runs.

**Decision 5, amended rather than flipped.** The TQ2 order asked for conditioning OFF on
grouped requests, decided by number. The number we have is T7's: off costs punctuation on
conversation chunks. The TQ1 gold set that would settle WER is not labelled yet. What TQ2
changes is the context's reach:

- In-process, each run is its own faster-whisper call, so conditioning acts within one run of
  at most 30 s and never across runs. The default stays on, per T7.
- HTTP backends expose no conditioning switch (the OpenAI-style API has none). Their context
  used to run across the whole file. It now resets at every run group.

`MDX_ASR_CONDITION_PREV` therefore applies to the in-process engine only. Revisit when
`eval/asr/v1` exists: if the in-process WER with conditioning off is within 0.5 pp and loops
(`diagnostics.loops`) drop, turn it off.

**Decision 6 holds on every backend.** `Segment.language` is set for a run decoded in another
language than the recording's, whoever decoded it.

**Also from TQ2.** Segment gates G1–G3 and the known-artefact list (`asr_worker/guards.py`,
`asr_models/artefacts.yaml`) run in `processor.decode_recording` before the echo guard, with
`MDX_ASR_GATES_ENABLED` as the rollback switch (dry-run diagnostics stay on). Non-speech
stretches of 5 s or more become `noise` markers (`music` / `silence` / `noise`), not text.
Every drop has a `reason` in `diagnostics.dropped_segments`, as numbers and enums only.
