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
| generation-service (Layer C inline completion, sprint 15, ADR-0036) | `ollama.com/library/gemma3:1b` (Gemma 3 1B instruct, Q4_K_M GGUF) | tag digest `8648f39daa8f` | GGUF blob | `7cd4618c1faf8b7233c6c906dac1694b6a47684b37b8895d470ac688520b9c01` | dev: `~/.ollama/models/blobs/` (served by `llama-server`); prod bake pending GPU rig |
| libs/models `dev_mac_asr` (DEP-S0, ADR-0046; dev Mac only) | `ggerganov/whisper.cpp` → `ggml-large-v3-turbo.bin` | main (content-addressed by digest) | GGML | `1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69` | `~/.cache/whisper-cpp/` (served by `whisper-server`, fetched by `make dev-model`) |
| libs/models `dev_mac` (DEP-S0, ADR-0046; dev Mac only) | `ollama.com/library/gemma3:4b` (Gemma 3 4B instruct, Q4_K_M GGUF) | tag digest `a2af6cc3eb7f` | GGUF blob | `a2af6cc3eb7fa8be8504abaf9b04e88f17a119ec3f04a3addf55f92841195f5a` (Ollama digest) | `~/.ollama/models/blobs/`; served as `notes-chat` via `infra/models/dev-mac/Modelfile` (num_ctx 32768) |
| libs/models `hf_eu` (DEP-S1; staging/beta, HF Inference Endpoint eu-west-1) | `google/gemma-3-4b-it` (gated: accept Gemma terms in the HF namespace) | `093f9f388b31de276ce2de164bdc2081324b9767` | served by TGI (weights fetched by HF at that revision) | n/a — HF verifies the revision | `deploy/hf/endpoints/chat.yaml` |
| libs/models `hf_eu_asr` (DEP-S1; staging/beta) | `openai/whisper-large-v3-turbo` (endpoint model) served as `deepdml/faster-whisper-large-v3-turbo-ct2` (CT2) | `41f01f3fe87f28c78e2fbf8b568835947dd65ed9` / `4df90f75321148c3a29a9e2351b7ddf8f5b115a8` | Speaches image (`ghcr.io/speaches-ai/speaches:0.8.2-cuda`) | n/a — HF verifies the revision | `deploy/hf/endpoints/asr.yaml` |

Assembly for the ECAPA row is scripted — `scripts/models/prepare_ecapa.py`
(also verifies `mean_var_norm_emb.ckpt`
`cd70225b05b37be64fc5a95e24395d804231d43f74b2e1e5a513db7b69b34c33` and copies
the repo-owned offline-patched `infra/models/ecapa/hyperparams.yaml`). Known
gap, recorded deliberately: **Silero VAD weights ship inside the `silero-vad`
PyPI wheel** (uv.lock-pinned, MIT) rather than through this table's
fetch+checksum flow — acceptable for the pilot because the wheel hash is
locked, but a future sprint should hoist the JIT file into a pinned artifact.

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
repos do not require it; a private in-perimeter mirror does.

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
