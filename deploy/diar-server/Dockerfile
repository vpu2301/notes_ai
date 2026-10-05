# diar-server: pyannote community-1 behind /v1/audio/diarizations (ADR-0052).
#   DOCKER_BUILDKIT=1 docker build -f deploy/diar-server/Dockerfile \
#     --secret id=hf_token,src=<(printf %s "$HF_TOKEN") -t diar-server:dev .
# Weights baked and digest-verified at build and at load; the gated-repo token never enters a layer.

# ── Stage 1: fetch + verify the weights ────────────────────────────────
FROM python:3.12-slim AS pyannote-fetch

ARG MDX_DIAR_V2_MODEL_REPO=pyannote/speaker-diarization-community-1
ARG MDX_DIAR_V2_MODEL_REVISION=3533c8cf8e369892e6b79ff1bf80f7b0286a54ee
ARG MDX_DIAR_V2_PINS='{"config.yaml":"7790f3cf805252b01622524f53c5eb390fb65ccbfd0ccd4b320a5addc887a873","embedding/pytorch_model.bin":"6f10ff60898a1d185fa22e1d11e0bfa8a92efec811f11bca48cb8cafebefd929","plda/plda.npz":"9b77bcd840692710dd3496f62ecfeed8d8e5f002fd991b785079b244eab7d255","plda/xvec_transform.npz":"325f1ce8e48f7e55e9c8aa47e05d2766b7c48c4b25b8de8dd751e7a4cc5fbe8f","segmentation/pytorch_model.bin":"7ad24338d844fb95985486eb1a464e32d229f6d7a03c9abe60f978bacf3f816e"}'

RUN pip install --no-cache-dir "huggingface_hub[cli]==0.25.2"

COPY scripts/models/prepare_pyannote.py /build/scripts/models/prepare_pyannote.py
COPY infra/models/pyannote-community-1/ /build/infra/models/pyannote-community-1/

ENV HF_HUB_DOWNLOAD_TIMEOUT=60
RUN --mount=type=secret,id=hf_token \
    set -eu; \
    for attempt in 1 2 3 4 5; do \
      rc=0; \
      python /build/scripts/models/prepare_pyannote.py \
        --target /opt/models/pyannote-community-1 \
        --revision "$MDX_DIAR_V2_MODEL_REVISION" \
        --pins-json "$MDX_DIAR_V2_PINS" \
        --token-file /run/secrets/hf_token || rc=$?; \
      [ "$rc" -eq 0 ] && exit 0; \
      [ "$rc" -eq 3 ] && exit 3; \
      echo "pyannote download attempt ${attempt} failed; resuming in 10s"; \
      sleep 10; \
    done; \
    echo "pyannote download failed after 5 attempts" >&2; exit 1

# ── Stage 2: runtime ───────────────────────────────────────────────────
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS runtime

ARG MDX_DIAR_V2_MODEL_REPO=pyannote/speaker-diarization-community-1
ARG MDX_DIAR_V2_MODEL_REVISION=3533c8cf8e369892e6b79ff1bf80f7b0286a54ee
ARG MDX_DIAR_V2_PINS='{"config.yaml":"7790f3cf805252b01622524f53c5eb390fb65ccbfd0ccd4b320a5addc887a873","embedding/pytorch_model.bin":"6f10ff60898a1d185fa22e1d11e0bfa8a92efec811f11bca48cb8cafebefd929","plda/plda.npz":"9b77bcd840692710dd3496f62ecfeed8d8e5f002fd991b785079b244eab7d255","plda/xvec_transform.npz":"325f1ce8e48f7e55e9c8aa47e05d2766b7c48c4b25b8de8dd751e7a4cc5fbe8f","segmentation/pytorch_model.bin":"7ad24338d844fb95985486eb1a464e32d229f6d7a03c9abe60f978bacf3f816e"}'

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Also enforced in app.py; here so a shell in the container sees them too.
    PYANNOTE_METRICS_ENABLED=false \
    HF_HUB_OFFLINE=1 \
    MDX_DIAR_V2_MODEL_DIR=/opt/models/pyannote-community-1 \
    MDX_DIAR_DEVICE=cuda

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3.12 python3-pip libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY deploy/diar-server/requirements.txt /srv/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /srv/requirements.txt

COPY libs/diarization /srv/libs/diarization
RUN pip3 install --no-cache-dir --break-system-packages --no-deps /srv/libs/diarization

COPY deploy/diar-server/app.py /srv/app.py
COPY --from=pyannote-fetch /opt/models/pyannote-community-1 /opt/models/pyannote-community-1

ENV MDX_DIAR_V2_MODEL_REPO=${MDX_DIAR_V2_MODEL_REPO} \
    MDX_DIAR_V2_MODEL_REVISION=${MDX_DIAR_V2_MODEL_REVISION} \
    MDX_DIAR_V2_PINS=${MDX_DIAR_V2_PINS}

# Never root.
RUN useradd --system --uid 10001 diar && chown -R diar:diar /srv
USER 10001

EXPOSE 8081
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8081/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "1"]
