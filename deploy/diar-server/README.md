# diar-server

Speaker diarization as an endpoint — shape B of ADR-0052.

It runs the same `PyannoteDiarizer` the worker can run in-process, so the
labels are identical; only the compute moves to a GPU. The worker reaches
it through `diarization.HttpDiarizer` and both sides share
`diarization.wire`, which is the only definition of the payload.

| | |
|---|---|
| Route | `POST /v1/audio/diarizations` (multipart: `file`, optional `num_speakers`/`min_speakers`/`max_speakers`, roster policy), `GET /health` |
| Auth | `X-MDX-Diar-Token: $MDX_DIAR_SERVER_TOKEN` (or the same value as a bearer, for a bare container). Checked in middleware **before the body is read**. Without a token the process refuses to start unless `MDX_DIAR_SERVER_ALLOW_ANONYMOUS=1` |
| Limits | one pass at a time (`MDX_DIAR_MAX_CONCURRENT`), 300 MB upload, `MDX_DIAR_MAX_AUDIO_SECONDS` on the DECODED length; CPU hosting refused (`MDX_DIAR_ALLOW_CPU=1` to override) |
| Stores | nothing — the audio lives in the request's memory |
| Receives | audio, hints, roster policy. **No** tenant id, job id, user, filename or text |
| Returns | labelled spans, overlap spans, counts. **Never** speaker embeddings (biometric data, concept §7) |
| Logs | duration, wall time, speaker count, hint kind |

## Run it on a laptop (dev)

```bash
make prepare-pyannote                      # once: gated weights into ~/.cache/mdx-models
MDX_DIAR_SERVER_ALLOW_ANONYMOUS=1 \
MDX_DIAR_DEVICE=mps \
MDX_DIAR_V2_MODEL_DIR=~/.cache/mdx-models/speaker-diarization-community-1 \
  uv run --with 'pyannote.audio>=4.0,<4.1' --with fastapi --with 'uvicorn[standard]' \
  --with python-multipart --with soundfile --project libs/diarization \
  uvicorn app:app --app-dir deploy/diar-server --port 8081
```

Point the worker at it with `MDX_DIAR_ENGINE=http` (the `dev_mac_diar`
backend in `config/models.yaml` already has the URL).

## Build the image

```bash
DOCKER_BUILDKIT=1 docker build -f deploy/diar-server/Dockerfile \
  --secret id=hf_token,src=<(printf %s "$HF_TOKEN") -t diar-server:dev .
```

The weights are baked and digest-verified at build and again at load. The
gated-repo token is a BuildKit secret and never enters a layer.

## Deploy

`deploy/hf/endpoints/diar.yaml` (T4, EU, scale-to-zero). Operations:
`docs/runbooks/model-backends.md#diarization-endpoint`.
