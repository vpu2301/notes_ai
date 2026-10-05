# asr-server — Parakeet-TDT-0.6B-v3 (Sprint TQ4, arm C)

The bake-off's transducer candidate (ADR-0067), behind the same OpenAI-style
route every `asr_http` backend serves:

```
POST /v1/audio/transcriptions   file, language, response_format=verbose_json, timestamp_granularities[]=word
→ {task, duration, text, segments: [{id, start, end, text}], words: [{word, start, end, probability?}], language?}
GET  /health                    {status, model_id, runtime, loaded}
```

- `language` is echoed only when the caller pinned one. Parakeet has no language
  identification, so the worker decides languages itself (TQ2 chunker).
- `no_speech_prob`, `avg_logprob` and `compression_ratio` are never sent. The
  worker's gates count them as unavailable and fall back to VAD and the n-gram loop
  detector (TQ2 T2).
- `prompt` is accepted and ignored, because Parakeet has no prompt biasing. Names come
  from the glossary and the TQ3 unifier.

## Runtimes

| `MDX_ASR_RUNTIME` | Where | What |
|---|---|---|
| `nemo` (default) | HF T4 endpoint `notes-asr-parakeet-{env}` | NeMo 3.0.0, fp16 CUDA. It switches to local attention above 20 min (`MDX_ASR_LOCAL_ATTENTION_AFTER_S`). |
| `onnx` | dev Mac (`make dev-model` with `DEV_MAC_ASR_ENGINE=parakeet`), and the fallback if the NeMo image is too large for the endpoint build | the `istupakov/parakeet-tdt-0.6b-v3-onnx` export of the same weights through `onnx-asr` 0.12 (MIT), with the CoreML / CPU execution providers |

```bash
# Endpoint image (repo root)
DOCKER_BUILDKIT=1 docker build -f deploy/asr-server/Dockerfile -t asr-server:dev .

# Mac (no Docker), on port 8082 like the endpoint
uv run --with-requirements deploy/asr-server/requirements-onnx.txt --directory deploy/asr-server \
  env MDX_ASR_RUNTIME=onnx MDX_ASR_SERVER_ALLOW_ANONYMOUS=1 uvicorn app:app --port 8082
```

Contract: the same rules as `deploy/diar-server`. There is no storage, the audio
lives in request memory only, and no identifiers are sent. The token goes in
`x-mdx-asr-token` (or a bearer header), and the server refuses to start without
one unless explicitly anonymous. The weights are baked and sha256-checked at
build. At runtime the hub is pinned offline (`HF_HUB_OFFLINE`,
`TRANSFORMERS_OFFLINE`, `HF_HUB_DISABLE_TELEMETRY`, `WANDB_MODE=disabled`).
Pins are in `docs/models/PINS.md`, and the CC-BY-4.0 attribution is in
`docs/legal/third-party-notices.md`.
