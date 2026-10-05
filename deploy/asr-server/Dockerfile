# asr-server — Parakeet-TDT-0.6B-v3 (NeMo) behind /v1/audio/transcriptions.
#
# Arm C of the TQ4 bake-off (ADR-0067). Built from the repo root:
#
#   DOCKER_BUILDKIT=1 docker build -f deploy/asr-server/Dockerfile -t asr-server:dev .
#
# The weights are baked at a pinned revision and digest-checked; nothing is
# downloaded at runtime (HF_HUB_OFFLINE=1). The repo is not gated, so no
# token is needed; the secret mount is honoured if given (rate limits).

# ── Stage 1: fetch + verify the .nemo ──────────────────────────────────
FROM python:3.12-slim AS parakeet-fetch

ARG MDX_ASR_MODEL_REPO=nvidia/parakeet-tdt-0.6b-v3
ARG MDX_ASR_MODEL_REVISION=541d1f99c6b0c3cd0b11a95167540bb8edefd82b
ARG MDX_ASR_MODEL_FILE=parakeet-tdt-0.6b-v3.nemo
ARG MDX_ASR_MODEL_SHA256=3cbdc85877e668ca7b82d0d56770eb1fac76691f55d6b97545e8d61ca588d10d

RUN pip install --no-cache-dir "huggingface_hub[cli]==0.25.2"
ENV HF_HUB_DOWNLOAD_TIMEOUT=60
RUN --mount=type=secret,id=hf_token,required=false \
    set -eu; \
    if [ -s /run/secrets/hf_token ]; then export HF_TOKEN="$(cat /run/secrets/hf_token)"; fi; \
    for attempt in 1 2 3 4 5; do \
      huggingface-cli download "$MDX_ASR_MODEL_REPO" "$MDX_ASR_MODEL_FILE" \
        --revision "$MDX_ASR_MODEL_REVISION" --local-dir /opt/models/parakeet && break; \
      echo "parakeet download attempt ${attempt} failed; resuming in 10s"; sleep 10; \
    done; \
    echo "${MDX_ASR_MODEL_SHA256}  /opt/models/parakeet/${MDX_ASR_MODEL_FILE}" | sha256sum -c -

# ── Stage 2: runtime ───────────────────────────────────────────────────
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS runtime

ARG MDX_ASR_MODEL_REPO=nvidia/parakeet-tdt-0.6b-v3
ARG MDX_ASR_MODEL_REVISION=541d1f99c6b0c3cd0b11a95167540bb8edefd82b
ARG MDX_ASR_MODEL_SHA256=3cbdc85877e668ca7b82d0d56770eb1fac76691f55d6b97545e8d61ca588d10d

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    WANDB_MODE=disabled \
    MDX_ASR_RUNTIME=nemo \
    MDX_ASR_DEVICE=cuda \
    MDX_ASR_MODEL_PATH=/opt/models/parakeet/parakeet-tdt-0.6b-v3.nemo

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3.12 python3-pip libsndfile1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
RUN pip3 install --no-cache-dir --break-system-packages \
      --index-url https://download.pytorch.org/whl/cu124 "torch==2.5.1" "torchaudio==2.5.1"
COPY deploy/asr-server/requirements.txt /srv/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /srv/requirements.txt

COPY deploy/asr-server/app.py deploy/asr-server/parakeet_engines.py deploy/asr-server/parakeet_format.py /srv/
COPY --from=parakeet-fetch /opt/models/parakeet /opt/models/parakeet

LABEL mdx.model.repo="${MDX_ASR_MODEL_REPO}" \
      mdx.model.revision="${MDX_ASR_MODEL_REVISION}" \
      mdx.model.sha256="${MDX_ASR_MODEL_SHA256}"

RUN useradd --system --uid 10001 asr && chown -R asr:asr /srv
USER 10001

EXPOSE 8082
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s \
    CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8082/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8082", "--workers", "1"]
