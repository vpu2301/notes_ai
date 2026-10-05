# Third-party notices

Attribution for third-party models and material that ship inside our images
and are subject to an attribution licence. Software dependencies are pinned in
`uv.lock` / `web/package-lock.json` and carry their own licence files.

## Mistral AI (EU) — hosted model API

Used by: `note-service` / `note-worker` for writing meeting notes
(`mistral_eu`, Mistral Large 3) and for classifying recordings, naming
notes and correcting names (`mistral_eu_small`, Mistral Small 4) — in dev
by default when `MISTRAL_API_KEY` is set (Sprint L2), on staging/prod after
the M2 rollout. This is a **processor**, not a baked model: transcript
windows, verified facts and names are sent over TLS to Mistral's EU-hosted
API (`https://api.mistral.ai/v1`) and nothing is stored there — the
account has **zero data retention** for the key and the **training
opt-out** set (`docs/runbooks/model-backends.md` §mistral-account). A
workspace is routed there only after its admin acknowledged
"Mistral AI (EU)" on the Data page; the dev seed acknowledges it for the
two dev tenants. The models are Apache-2.0 open weights served by their
maker; no weights ship in our images.

- **Provider:** Mistral AI, Paris — <https://mistral.ai>
- **Models:** `mistral-large-2512`, `mistral-small-2603` (`docs/models/PINS.md`)
- **Terms / DPA:** the Mistral AI terms of service and data processing
  addendum for the API, referenced from the runbook.

## pyannote speaker-diarization-community-1

Used by: `asr-worker`, speaker diarization for recorded meetings when
`MDX_DIAR_ENGINE=pyannote` (Diarizer v2, Sprint 29). It runs inside our worker
from a baked, checksum-verified copy (`/opt/models/pyannote-community-1`). No
audio, transcript or usage data is sent to pyannoteAI or Hugging Face:
the hub is offline at runtime and pyannote.audio's usage telemetry is
disabled (`PYANNOTE_METRICS_ENABLED=false`).

- **Work:** `pyannote/speaker-diarization-community-1` — speaker-diarization
  pipeline (segmentation, speaker-embedding and PLDA models, and pipeline
  configuration)
- **Creator / copyright:** pyannoteAI and the pyannote.audio authors
- **Source and model card:** <https://huggingface.co/pyannote/speaker-diarization-community-1>
- **Revision used:** `3533c8cf8e369892e6b79ff1bf80f7b0286a54ee`
  (see `docs/models/PINS.md`)
- **Licence:** Creative Commons Attribution 4.0 International (CC BY 4.0) —
  <https://creativecommons.org/licenses/by/4.0/>
- **Changes:** the model weights are used unmodified. The pipeline
  configuration file is a copy we maintain in this repository
  (`infra/models/pyannote-community-1/config.yaml`) with upstream's
  parameters unchanged, which loads the sub-models from local paths instead
  of the Hugging Face hub.
- **Disclaimer:** the licensor offers the work as-is and makes no
  representations or warranties of any kind concerning it (CC BY 4.0,
  Section 5).

The upstream model card is baked next to the weights as `MODEL_CARD.md`.

The pipeline runs on the `pyannote.audio` library (MIT licence,
<https://github.com/pyannote/pyannote-audio>).

## NVIDIA Parakeet-TDT-0.6B-v3 — ASR candidate (Sprint TQ4)

`nvidia/parakeet-tdt-0.6b-v3` (revision `541d1f99c6b0`) runs in `deploy/asr-server`, the
bake-off's arm C (ADR-0067). On the dev Mac its ONNX export
`istupakov/parakeet-tdt-0.6b-v3-onnx` (revision `8f23f0c03c87`) is used, which carries the
same licence.

- **Licence:** Creative Commons Attribution 4.0 International (CC-BY-4.0).
- **Attribution (required wherever the model is used or its output is shown, product docs
  included):** "Speech recognition by Parakeet-TDT-0.6B-v3, © NVIDIA Corporation, licensed
  under CC-BY-4.0 (https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)."
- **Runtimes:** NVIDIA NeMo 3.0.0 (Apache-2.0) in the endpoint image, and `onnx-asr` 0.12.0
  (MIT) on the dev Mac.
- **Status:** a candidate, not routed. The attribution must appear in the product's notices
  before ADR-0067 is accepted for it.

## Tatoeba — common-word lists for the spelling unifier (Sprint TQ3)

`libs/asr_models/src/asr_models/resources/freq_{de,en,uk}.txt` hold the 50 000 most
frequent word forms per language. They are counted from the Tatoeba sentence exports
(`https://downloads.tatoeba.org/exports/per_language/<lang>/<lang>_sentences.tsv.bz2`,
fetched 2026-10-01) by `scripts/models/build_frequency_lists.py`. No sentence is kept.

- **Licence:** Tatoeba sentences are under Creative Commons Attribution 2.0 France
  (CC-BY 2.0 FR), and some under CC0. The derived word lists are distributed under the
  same attribution terms.
- **Attribution:** "Word frequencies derived from Tatoeba (https://tatoeba.org),
  CC-BY 2.0 FR."
- **Not used:** the Leipzig Corpora Collection, whose licence could not be confirmed on
  2026-10-01 because the site is behind an anti-bot wall. Also hermitdave/FrequencyWords,
  whose data is CC-BY-SA 4.0 (share-alike).

## Metaphone (Double Metaphone) — asr-service

`Metaphone` 0.6 (https://github.com/oubiwann/metaphone), a PyPI dependency of
asr-service, gives the English and romanised-Ukrainian phonetic keys of the spelling
unifier. Licence: BSD.
