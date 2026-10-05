# ASR engine bake-off (Sprint TQ4, ADR-0067)

**Status: the decision has not been taken, and nothing below can take it.** The
pre-registered rule (ADR-0067) is applied to `eval/asr/v1` **test split**, per
language. That split has no labelled recording yet (TQ1 T2 is open). Neither HF
endpoint, arm B (`notes-asr-whisper-v3-*`) or arm C (`notes-asr-parakeet-*`),
has been raised, so there is no T4 speed or cost. Everything measured here is
on **synthetic speech on the dev Mac**. It is plumbing evidence and engine
properties, not evidence for the rule. ADR-0067 stays **proposed**, `routing`
is unchanged, and no shadow has run.

## Decision-rule table (test split)

| Criterion | A `hf_eu_asr` (turbo) | B `cand_whisper_v3_asr` | C `cand_parakeet_asr` | Rule met? |
|---|---|---|---|---|
| TR-01 WER de / uk / en | not measured (n = 0) | not measured | not measured | — |
| TR-04 entity error (entity view: unified) | not measured | not measured | not measured | — |
| TR-02 halluc chars/min, artefact hits | not measured | not measured | not measured | — |
| TR-06 code-switch coverage | — | — | not measured | — |
| TR-08 word-ts median MAE, missing | — | — | not measured (no forced alignment yet) | — |
| TR-12 rtf on T4 / M-series | not measured on T4 | not measured on T4 | not on T4; Mac below | — |
| Cost per audio hour | not measured | not measured | not measured | — |

## What was measured (synthetic, dev Mac, 2026-10-01)

Five macOS-TTS files ran: de, en, uk, a de/en/de mix with 12 s of a chord and
15 s of silence, and a German file naming "Handala" ×8. They went through the
production worker path (`decode_recording`: chunker, guards, coverage) with
guards on and the TQ3 unifier on (`entity_view: unified`). Turbo and Parakeet
had three runs each; large-v3 had one. With n = 1 per language for en and uk,
every language row is **not measured** under the rule's own n ≥ 3. The numbers
are directional at best.

| Arm (Mac stand-in) | WER all | de | en | uk | entity err | halluc chars/min | artefacts | code-switch | rtf (worker path, mean of runs) |
|---|---|---|---|---|---|---|---|---|---|
| A: `dev_mac_asr` (turbo, whisper.cpp, Metal) | 0.028 | 0.024 | 0.000 | 0.091 | 0.00 | 0.0 | 0 | 1.00 | 0.239 |
| B family: `inproc_cpu_asr` (large-v3 int8, CPU) | 0.022 | 0.016 | 0.000 | 0.091 | 0.00 | 0.0 | 0 | 1.00 | 2.21 (CPU; per-run LID with large-v3) |
| C: `dev_mac_parakeet_asr` (asr-server, ONNX, CoreML/CPU) | 0.028 | 0.016 | 0.031 | 0.091 | 0.00 | 0.0 | 0 | 1.00 | 0.116 |

All three arms make the same two Ukrainian errors ("надійшли" for "надішле",
"татниці" for "п'ятниці"), which points at the TTS voice rather than the engines.
Through the production path no arm wrote anything over silence or music,
because since TQ2 the chunker sends speech only.

### Engine property: non-speech sent straight to the engine (no chunker)

This is what the guards protect against, and why the market analysis
favours a transducer. Characters per minute of audio:

| Clip | turbo (whisper.cpp), de | turbo, en | Parakeet (ONNX), de | Parakeet, en |
|---|---|---|---|---|
| 12 s chord + 15 s silence | 113.4 (invented lyrics) | 2.2 | 0.0 | 0.0 |
| 30 s white noise | 48.0 ("Untertitelung des ZDF, 2020") | 22.0 ("So, let's go.") | 0.0 | 0.0 |
| 30 s digital silence | 22.0 ("Vielen Dank.") | 18.0 ("Thank you.") | 0.0 | 0.0 |

Turbo reproduces the r04 artefacts word for word. Parakeet emits nothing.
That is consistent with the transducer's blank emission, measured on
synthetic clips.

### Mac table, and the number Sprint C5 consumes

| Mac build | de | en | uk | mixed | entity | rtf (engine only) |
|---|---|---|---|---|---|---|
| whisper.cpp turbo (`dev_mac_asr`), through the worker | 0.000 | 0.000 | 0.091 | 0.000 | 0.053 | ≈ 0.24 incl. worker overhead |
| asr-server ONNX Parakeet (`dev_mac_parakeet_asr`), through the worker | 0.000 | 0.031 | 0.091 | 0.000 | 0.035 | ≈ 0.12 incl. worker overhead |
| **FluidAudio CoreML Parakeet v3** (Neural Engine, `fluidaudiocli transcribe --model-version v3`, whole file) | 0.000 | 0.062 | 0.091 | 0.000 | 0.035 | **0.006–0.015** (rtfx ≈ 66–180) |

The C5 number is that FluidAudio's CoreML Parakeet v3 runs at 0.6–1.5 % of
real time on the Neural Engine here, with WER on synthetic de/en/uk equal to
the GPU-path engines. FluidAudio is Apache-2.0, at commit
`0b1f46289fe2` (2026-10-01), built from source in a scratch folder. It is not
vendored. The per-language WER that C5 needs on real meeting audio waits for
the gold set.

## Defects found by the bake-off (fixed)

1. **Join-gap timestamps** (`models.run_groups`, a TQ2 bug). A word stamped
   inside the 300 ms silence between two runs mapped to the end of the earlier
   run. With Parakeet's 80 ms frames that moved a sentence ahead of the English
   clip, and WER on the mixed file read 0.488. Such a time now snaps to the
   nearer run edge, and the mixed file scores 0.000.
2. **"Detected" language from a server that detects nothing.** Parakeet names
   no language. The client had marked the fallback "en" as detected, which
   would have decoded every auto recording as English. Now a server that names
   none is not detected, and the worker's local identifier decides, choosing
   among de/en/uk when unsure.
3. **Word probabilities absent.** They now count as `gate_unavailable` and
   skip G3, instead of reading as 1.0.

## Worst files per arm (synthetic)

| Arm | Worst | Code |
|---|---|---|
| A turbo | tts-uk (0.091, two misheard words); tts-entity ("Najee El Ali") | T-ENT |
| B large-v3 | tts-uk (0.091); tts-entity ("Naj-Ali") | T-ENT |
| C Parakeet | tts-uk (0.091); tts-en (dropped "the") | T-ENT, T-COV |

## To take the decision

1. Label `eval/asr/v1` (TQ1 T2).
2. Build and push `deploy/asr-server`, then raise `notes-asr-parakeet-staging`
   and `notes-asr-whisper-v3-staging` (`make hf-endpoints ARGS="apply --env staging"`).
3. Run `make eval-asr BACKEND={hf_eu_asr,cand_whisper_v3_asr,cand_parakeet_asr} SPLIT=test GUARDS=on`
   three times each.
4. Fill in the table above, apply the rule verbatim and record the outcome in
   ADR-0067.
5. If it adopts C or B, run the shadow (`MDX_ASR_SHADOW_BACKEND`) for two weeks
   and at least 200 jobs, then switch routing.
