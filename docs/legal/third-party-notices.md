# Third-party notices

Attribution for third-party models and material that ship inside our images
and are subject to an attribution licence. Software dependencies are pinned in
`uv.lock` / `web/package-lock.json` and carry their own licence files.

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
