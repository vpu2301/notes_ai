# ASR guards (Sprint TQ2) — before/after

**Status: the measurement the sprint asks for has not been run.** `eval/asr/v1`
has no labelled recording (TQ1 T2 is open), the HF endpoint behind
`hf_eu_asr` does not exist, and no TQ1 baseline is committed. The TR gate
table per backend × language therefore stays empty. Below is what *was* run:
a synthetic smoke corpus through the job's own path on the two backends
available on the dev Mac. These numbers prove the plumbing. They are not
evidence for any acceptance criterion.

## Smoke corpus (synthetic, not in git)

There are four files, each with an exact reference: macOS TTS in de, en and uk,
each followed by 20 s of digital silence. A fourth file mixes de, then an
English clip, then de, then a 12 s synthetic chord, then 15 s of silence.
Spans mark the silence, the music and the English region.

`make eval-asr BACKEND=<b> SPLIT=dev CORPUS=<smoke> GUARDS=both` was run
on 2026-09-30 and 2026-10-01.

| Backend | Guards | WER | halluc chars/min | artefact hits | coverage | code-switch kept | translated | non-speech marked | RTF |
|---|---|---|---|---|---|---|---|---|---|
| `dev_mac_asr` (whisper.cpp turbo) | off (dry run) | 0.016 | 0 | 0 | 1.00 | 1.00 | 0 | 1.00 | 0.22 |
| `dev_mac_asr` | on | 0.016 | 0 | 0 | 1.00 | 1.00 | 0 | 1.00 | 0.21 |
| `inproc_cpu_asr` (large-v3 int8 CPU) | off (dry run) | 0.016 | 0 | 0 | 1.00 | 1.00 | 0 | 1.00 | 1.74 |
| `inproc_cpu_asr` | on | 0.016 | 0 | 0 | 1.00 | 1.00 | 0 | 1.00 | 1.67 |

All of the WER is the Ukrainian file, where both engines mishear the same
two words ("надійшли" for "надішле", "татниці" for "п'ятниці"). The de, en
and mixed files score 0.

**What the guards changed: nothing, because T1 had already removed the
cause.** Before TQ2, whisper.cpp was posted the whole file. It wrote
"Vielen Dank." over the German file's 20 s of digital silence
(`no_speech_prob` 3e-10, `avg_logprob` −0.22, timestamped 30.0–60.0 s on a
33 s file). Since T1 it receives only speech runs, so the silence is never
decoded and the gates had nothing to drop on this corpus. The artefact rule
and G1–G3 are covered by unit tests (`services/asr-worker/tests/unit/test_guards.py`);
on real audio they wait for the gold set's jingles and ad reads.

**`gate_unavailable`:** `dev_mac_asr` reports no `compression_ratio` on any
segment (18 of 18). Its `no_speech_prob` is present but useless, about 0 even
on hallucinated text, so on this backend G1 rarely fires and the VAD
condition and the artefact list do the work. `inproc_cpu_asr` reports all
three fields. `hf_eu_asr` was not measured.

**Five most frequent dropped phrases:** none were dropped on this corpus.
The only phrase seen in the wild is "Vielen Dank." (`de:16`), from the
pre-TQ2 whole-file decode above.

**RTF:** `dev_mac_asr` ran 0.21–0.22 with guards on, within TR-12's 0.25.
`inproc_cpu_asr` on CPU ran 1.67. That is not comparable with TQ1's 1.39
smoke run: a different file set (the mixed file adds three large-v3
language checks at about 11 s each on CPU) on a loaded machine. Per-run language ID with
the engine's own model is the in-process path's cost, and it predates TQ2.

## Defects found while measuring (fixed in TQ2)

1. **whisper.cpp words were sub-word tokens.** For example, "Д", "обр" and
   "ого" for "Доброго". This put Ukrainian WER at 2.8 before the fix and broke
   word timings for every `dev_mac_asr` transcript.
   `models.asr_http._merge_subwords` now joins tokens that carry no leading
   space.
2. **`dev_mac_asr` decoded every `auto` job as English.** The client omits
   `language` for auto, and whisper-server's default is `en`.
   `make dev-model` now starts it with `-l auto`. **Restart a running
   whisper-server** (`make dev-model ARGS=stop && make dev-model`).

## To run when the gold set exists

```
make eval-asr BACKEND=inproc_cpu_asr SPLIT=test LABEL=tq2 GUARDS=both
make eval-asr BACKEND=dev_mac_asr    SPLIT=test LABEL=tq2 GUARDS=both
make eval-asr BACKEND=hf_eu_asr      SPLIT=test LABEL=tq2 GUARDS=both
make eval-asr-assert
```

Fill in the TR-01/02/03/06/07/10/12 table per language from those reports.
Update the nightly baseline only if every acceptance gate holds.
