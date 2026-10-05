# Model pins (Sprint B1, ADR-0021)

Single source of truth for every model the platform bakes at build time.
All models are **build-time-only** sources: fetched at a pinned, immutable
commit revision, checksum-verified (fail-closed), baked into the image, and
loaded **fully offline** at runtime (`HF_HUB_OFFLINE=1`). Hugging Face is
never a runtime dependency and never sees tenant content.

Pins resolved from the Hugging Face API on **2026-06-10**.

| Service | Repo | Revision (commit) | Verified artifact | SHA-256 | Baked path |
|---|---|---|---|---|---|
| asr-worker, dictation-service (GPU) | `Systran/faster-whisper-large-v3` | `edaa852ec7e145841d8ffdb056a99866b5f0a478` | `model.bin` | `69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1` | `/opt/models/whisper-large-v3` |
| asr-worker, dictation-service (CPU dev) | `Systran/faster-whisper-tiny` | `d90ca5fe260221311c53c58e660288d3deb8d356` | `model.bin` | `dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1` | `/opt/models/whisper-tiny` |
| nlp-service | `oliverguhr/fullstop-punctuation-multilang-large` | `345e80adc07e761d3a35feafd20f2f44a151f453` | `model.safetensors` | `270f27d7398a5fdad43bdf9953ea532fbe62c5f5227ed5f5316e9bd64a9255e1` | `/opt/models/punctuation` |
| dictation-service (conversation mode, sprint 14, ADR-0034) | `speechbrain/spkrec-ecapa-voxceleb` | `0f99f2d0ebe89ac095bcc5903c4dd8f72b367286` | `embedding_model.ckpt` | `0575cb64845e6b9a10db9bcb74d5ac32b326b8dc90352671d345e2ee3d0126a2` | `/opt/models/ecapa` |
| asr-worker (Diarizer v2, Sprint 29; `MDX_DIAR_ENGINE=pyannote`) — licence **CC-BY-4.0** (gated; attribution in `docs/legal/third-party-notices.md`) | `pyannote/speaker-diarization-community-1` | `3533c8cf8e369892e6b79ff1bf80f7b0286a54ee` | `segmentation/pytorch_model.bin`, `embedding/pytorch_model.bin`, `plda/plda.npz`, `plda/xvec_transform.npz` | segmentation `7ad24338d844fb95985486eb1a464e32d229f6d7a03c9abe60f978bacf3f816e` · embedding `6f10ff60898a1d185fa22e1d11e0bfa8a92efec811f11bca48cb8cafebefd929` · plda `9b77bcd840692710dd3496f62ecfeed8d8e5f002fd991b785079b244eab7d255` · xvec_transform `325f1ce8e48f7e55e9c8aa47e05d2766b7c48c4b25b8de8dd751e7a4cc5fbe8f` (resolved 2026-09-19) | `/opt/models/pyannote-community-1` (dev: `~/.cache/mdx-models/speaker-diarization-community-1`) |
| generation-service (Layer C inline completion, sprint 15, ADR-0036) | `ollama.com/library/gemma3:1b` (Gemma 3 1B instruct, Q4_K_M GGUF) | tag digest `8648f39daa8f` | GGUF blob | `7cd4618c1faf8b7233c6c906dac1694b6a47684b37b8895d470ac688520b9c01` | dev: `~/.ollama/models/blobs/` (served by `llama-server`); prod bake pending GPU rig |
| libs/models `dev_mac_asr` (DEP-S0, ADR-0046; dev Mac only) | `ggerganov/whisper.cpp` → `ggml-large-v3-turbo.bin` | main (content-addressed by digest) | GGML | `1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69` | `~/.cache/whisper-cpp/` (served by `whisper-server`, fetched by `make dev-model`) |
| libs/models `dev_mac` (DEP-S0, ADR-0046; dev Mac only) | `ollama.com/library/gemma3:4b` (Gemma 3 4B instruct, Q4_K_M GGUF) | tag digest `a2af6cc3eb7f` | GGUF blob | `a2af6cc3eb7fa8be8504abaf9b04e88f17a119ec3f04a3addf55f92841195f5a` (Ollama digest) | `~/.ollama/models/blobs/`; served as `notes-chat` via `infra/models/dev-mac/Modelfile` (num_ctx 16384 since Sprint L1; `Modelfile.longctx` 32768 for the eval single-pass arm only) |
| libs/models `mistral_eu` (Sprint L2; **dev default** with the key, staging/prod after M2 T7) — hosted API, EU, zero data retention requested | `mistral-large-2512` (Mistral Large 3, v25.12, GA, 256k context; the writing model: `understand`/`summarize`) | dated id, never `-latest` (`MISTRAL_LARGE_PIN` overrides) | served by Mistral AI — no artifact | n/a — a processor, not a baked model | `https://api.mistral.ai/v1` (`MISTRAL_API_URL`); ids read from docs.mistral.ai on **2026-09-27** |
| libs/models `mistral_eu_small` (Sprint L2) | `mistral-small-2603` (Mistral Small 4, v26.03, GA, 256k context; `classify`/`title`/`entities`) | dated id (`MISTRAL_SMALL_PIN`) | served by Mistral AI | n/a | same endpoint, same key; prices in `config/model_costs.yaml` |
| libs/models `hf_eu` (DEP-S1; staging/beta, HF Inference Endpoint eu-west-1) | `google/gemma-3-4b-it` (gated: accept Gemma terms in the HF namespace) | `093f9f388b31de276ce2de164bdc2081324b9767` | served by TGI (weights fetched by HF at that revision) | n/a — HF verifies the revision | `deploy/hf/endpoints/chat.yaml` |
| libs/models `hf_eu_asr` (DEP-S1; staging/beta) | `openai/whisper-large-v3-turbo` (endpoint model) served as `deepdml/faster-whisper-large-v3-turbo-ct2` (CT2) | `41f01f3fe87f28c78e2fbf8b568835947dd65ed9` / `4df90f75321148c3a29a9e2351b7ddf8f5b115a8` | Speaches image (`ghcr.io/speaches-ai/speaches:0.8.2-cuda`) | n/a — HF verifies the revision | `deploy/hf/endpoints/asr.yaml` |
| libs/models `cand_parakeet_asr` (Sprint TQ4 arm C, ADR-0067; candidate, not routed) — licence **CC-BY-4.0** (attribution in `docs/legal/third-party-notices.md`) | `nvidia/parakeet-tdt-0.6b-v3` | `541d1f99c6b0c3cd0b11a95167540bb8edefd82b` | `parakeet-tdt-0.6b-v3.nemo` | `3cbdc85877e668ca7b82d0d56770eb1fac76691f55d6b97545e8d61ca588d10d` (fetched 2026-10-01) | `/opt/models/parakeet/` in `deploy/asr-server` (NeMo 3.0.0, fp16 T4); endpoint spec `deploy/hf/endpoints/asr-parakeet.yaml` |
| libs/models `dev_mac_parakeet_asr` (Sprint TQ4, dev Mac only; the endpoint's fallback runtime) | `istupakov/parakeet-tdt-0.6b-v3-onnx` (ONNX export of the weights above, CC-BY-4.0) via `onnx-asr` 0.12.0 (MIT) | `8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce` | `encoder-model.onnx(.data)`, `decoder_joint-model.onnx`, `nemo128.onnx` | encoder.data `9a22d372c51455c34f13405da2520baefb7125bd16981397561423ed32d24f36` · encoder `98a74b21b4cc0017c1e7030319a4a96f4a9506e50f0708f3a516d02a77c96bb1` · decoder_joint `e978ddf6688527182c10fde2eb4b83068421648985ef23f7a86be732be8706c1` · nemo128 `a9fde1486ebfcc08f328d75ad4610c67835fea58c73ba57e3209a6f6cf019e9f` | `~/.cache/huggingface/hub/` (fetched by `make dev-model` with `DEV_MAC_ASR_ENGINE=parakeet`) |
| libs/models `cand_whisper_v3_asr` (Sprint TQ4 arm B; candidate, not routed) | `openai/whisper-large-v3` served as `Systran/faster-whisper-large-v3` (CT2) | `06f233fe06e710322aca913c1bc4249a0d71fce1` / `edaa852ec7e145841d8ffdb056a99866b5f0a478` | Speaches image (`ghcr.io/speaches-ai/speaches:0.8.2-cuda`), fp16 | `69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1` (`model.bin`, same as the worker image) | `deploy/hf/endpoints/asr-whisper-v3.yaml` |

Assembly for the ECAPA row is scripted — `scripts/models/prepare_ecapa.py`
(also verifies `mean_var_norm_emb.ckpt`
`cd70225b05b37be64fc5a95e24395d804231d43f74b2e1e5a513db7b69b34c33` and copies
the repo-owned offline-patched `infra/models/ecapa/hyperparams.yaml`). Known
gap, recorded deliberately: **Silero VAD weights ship inside the `silero-vad`
PyPI wheel** (uv.lock-pinned, MIT) rather than through this table's
fetch+checksum flow — acceptable for the pilot because the wheel hash is
locked, but a future sprint should hoist the JIT file into a pinned artifact.

The same pinned directory is baked into TWO images: the asr-worker (shape A,
`MDX_DIAR_ENGINE=pyannote`) and `deploy/diar-server` (shape B, the GPU
endpoint that ships — ADR-0052). Both run the identical assembly script, so
the digests below are the only definition of what either one loads.

pyannote community-1 row (Sprint 29 B-7): assembled by
`scripts/models/prepare_pyannote.py` (`make prepare-pyannote`; the worker
Dockerfile's `pyannote-fetch` stage runs the same script, so image and dev
dir are byte-identical). The revision is real — the repo's `main` commit on
2026-09-19, read from the public HF model API. The four weight digests were resolved on 2026-09-19 with
`--resolve-pins` (token with the model terms accepted) and are committed to
`PINNED` in the script, the `MDX_DIAR_V2_PINS` default in
`services/asr-worker/Dockerfile` and the table above; the install verifies
them fail-closed. Public metadata
the script already checks: file sizes (segmentation 5,906,507 B; embedding
26,646,242 B; plda 133,852 B; xvec_transform 134,376 B) and the git blob ids
of upstream `config.yaml` (`4022db43960736338378fdb6b5a85cfdae198910`) and
`README.md` (`8356d6634d7b1074581dd36e2225887ec809326e`).

The pipeline config is repo-owned (`infra/models/pyannote-community-1/config.yaml`,
sha256 `7790f3cf805252b01622524f53c5eb390fb65ccbfd0ccd4b320a5addc887a873`):
every sub-model is `$model/<subfolder>`, which pyannote.audio resolves to the
local directory it was loaded from — never a hub id. The script refuses to
install if upstream's config (verified by git blob id) differs from ours in
anything but `dependencies`. `config.yaml` is part of `MDX_DIAR_V2_PINS`, so
the worker re-verifies it with the weights at load. The baked dir also
carries `MODEL_CARD.md` (upstream README, for CC-BY attribution) and
`MANIFEST.json` (repo, revision, every digest). Runtime: `HF_HUB_OFFLINE=1`
and `PYANNOTE_METRICS_ENABLED=false` (pyannote.audio 4.x ships usage
telemetry to `otel.pyannote.ai` ON by default); the in-process engine adds
no egress host.

Layer C (sprint 15) row: the Gemma 3 1B GGUF is fetched via `ollama pull
gemma3:1b` (content-addressed — the blob file IS its sha256) and served in dev
by `llama-server` pointed at the blob path (ADR-0036 records why: a constant
~420 ms/request scheduler overhead in Ollama 0.32.5 with gemma3's SWA cache).
The production image bake (fetch at pin → `sha256sum -c` → bake, same flow as
the rows above) is deferred with the GPU rig; the digest above is the pin it
must verify against.

### Runtime model *backends* (DEP-S0, ADR-0046) — an explicit exemption

The two `libs/models` rows above are **dev-Mac only** and are the first
models this table lists that are *served over HTTP at runtime* rather than
baked into an image. They keep the doctrine's intent — a named, digest-pinned
artifact that is verified before use — but the enforcement is different:
`make dev-model` fetches whisper.cpp weights by digest and Ollama stores
blobs content-addressed; nothing is baked. The staging/beta backend
(`hf_eu`, Hugging Face Inference Endpoints in an EU region) is a
*processor*, not a pin in this table: its model id is the `HF_CHAT_MODEL_PIN`
/ `HF_ASR_MODEL_PIN` environment value, recorded on every run as
`(backend, model_id)` (decision 11) and disclosed on the workspace Data
page (decision 12). "Hugging Face is never a runtime dependency" therefore
now reads: *never for the baked models in this table*; the Inference
Endpoints path is a deliberate, disclosed runtime processor for beta,
replaced by `hosted_eu` at gate H0. DEP-S1 adds the pin-upgrade runbook.

## What each ASR backend returns per segment (Sprint TQ2, probed 2026-09-30)

The TQ2 gates (`asr_worker/guards.py`) read these fields where a backend
reports them. A missing field skips that part of a gate, and
`diagnostics.gate_unavailable` counts it.

| Backend | `no_speech_prob` | `avg_logprob` | `compression_ratio` | Words | Language with `auto` |
|---|---|---|---|---|---|
| `inproc_cpu_asr` (faster-whisper large-v3) | yes | yes | yes | real words | `detect_language`, full probability table |
| `hf_eu_asr` (Speaches 0.8.2, faster-whisper) | yes, per faster-whisper's segment fields | yes | yes | top-level `words[]`, no leading spaces | `language`. The probability table is not verified, because no endpoint was raised in TQ2. |
| `dev_mac_asr` (whisper.cpp `whisper-server`, ggml-large-v3-turbo) | present, but **≈ 0 even on text written over silence**: 3e-10 on a "Vielen Dank." over 20 s of digital silence, `avg_logprob` −0.22 | yes | **absent** | **decoder tokens**: a token without a leading space continues the word before it. `asr_http._merge_subwords` joins them since TQ2. Before that, every whisper.cpp transcript's words were sub-word pieces. | `detected_language`, `detected_language_probability`, `language_probabilities`. These are reported **only when the server runs with `-l auto`**. Its default is English, and the client omits `language` for an auto job, so `make dev-model` now starts it with `-l auto`. |

whisper.cpp also stamps its last segment up to the next 30 s boundary, past
the end of the audio it was sent. `models.run_groups.Group.to_recording`
clamps those times.

The local language identifier for HTTP backends is faster-whisper **tiny**
(`MDX_ASR_LID_MODEL`). The CPU image bakes it at `/opt/models/whisper-tiny`,
using the `MD_ASR_MODEL_*` tiny pin above. On CPU it takes 0.21 s per run,
against 1.86 s for small and 11.6 s for large-v3. On clean TTS speech it
gives de 0.99, en 1.00 and uk 0.63, measured 2026-09-30. The GPU image does
not bake tiny. A GPU worker with an HTTP backend therefore decodes every run
in the recording's language, and `language_id` reads `unavailable`.

**Mac binaries for TQ4.** `parakeet.cpp` and the FluidAudio CoreML CLI, both named in the
sprint, are **not pinned or used**. The Mac arm runs the same `deploy/asr-server` code as the
endpoint, with its ONNX runtime, so the Mac and EU-GPU paths share one server. The FluidAudio
measurement that Sprint C5 needs is open (`docs/eval/asr-bakeoff-2026-11.md`).

## How the pin is enforced

Each service Dockerfile has a `model-fetch` build stage that:

1. `huggingface-cli download <repo> --revision <commit>` — immutable, never a
   moving tag.
2. `sha256sum -c` the verified artifact against the pinned digest — **a
   mismatch fails the build** (AC-B1-1).
3. The runtime stage `COPY --from=model-fetch` bakes the weights and stamps
   OCI labels `mdx.model.repo` / `mdx.model.revision` / `mdx.model.sha256`,
   so a deployed image is self-describing (`docker inspect`). The ECAPA row
   adds `mdx.diar.model.*` from its own `ecapa-fetch` stage, which reuses
   `scripts/models/prepare_ecapa.py` so the image and a developer's
   `make prepare-ecapa` produce byte-identical dirs.

### Re-asserted at startup (sprint 14)

A build-time check only proves the image was correct **when it was built**.
Since sprint 14 the diarization digests are verified AGAIN when the process
starts (`dictation_service/diarization/integrity.py`), before the weights are
loaded, driven by the `MDX_DIAR_MODEL_SHA256` / `MDX_DIAR_MEANVAR_SHA256`
ENV the Dockerfile bakes. A mismatch, a missing artifact, or a missing
`hyperparams.yaml` **refuses to start the diarizer** — the worker degrades
to dictation-only and `/readyz` reports `conversation_ready: false` with the
reason. Diarizing with weights nobody can account for is not an option for a
product entrusted with confidential audio.

Whisper is not yet startup-verified — `MD_ASR_MODEL_SHA256` is logged as
provenance only. Extending the same assertion to the ASR weights is a
follow-up (todo.md).

`HF_TOKEN` is consumed only as a BuildKit `--secret` (`--mount=type=secret,id=hf_token`)
and never lands in any layer, env, or log. The public Systran/oliverguhr
repos do not require it; a private in-perimeter mirror does, and so does the
gated pyannote community-1 repo (the `pyannote-fetch` stage reads the secret
file directly via `--token-file`, so it never enters even the build shell's
environment).

## Re-pinning

Override at build time without editing the Dockerfile:

```sh
DOCKER_BUILDKIT=1 docker build \
  --build-arg MD_ASR_MODEL_REVISION=<new-commit> \
  --build-arg MD_ASR_MODEL_SHA256=<new-model.bin-sha256> \
  -f services/asr-worker/Dockerfile -t mdx-asr-worker:gpu .
```

Any model change must be validated for transcription-quality regressions before rollout.

## Verified on 2026-06-10 (CPU/tiny, fully offline)

Built `Dockerfile.cpu`, ran with `--network none`, and transcribed real
speech end-to-end — proving pin → verify → bake → offline-load → transcribe.
A deliberately corrupted `--build-arg MD_ASR_MODEL_SHA256` failed the build as
designed. The GPU/large-v3 path uses the identical mechanism.
