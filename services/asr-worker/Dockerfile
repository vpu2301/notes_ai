# ── GPU build for asr-worker (Whisper + CUDA) ──────────────────────────
# Uses nvidia/cuda runtime image because faster-whisper + cuDNN need both
# the CUDA runtime libs and a glibc base. Distroless is not viable here
# (driver/CUDA stack expects glibc). See ADR-0009 / ADR-0021.
#
# Build (HF token is a BuildKit secret — never baked into the image):
#   DOCKER_BUILDKIT=1 docker build \
#     --secret id=hf_token,env=HF_TOKEN \
#     -f services/asr-worker/Dockerfile -t mdx-asr-worker:gpu .
#
# The model is fetched at a PINNED commit revision and its weights are
# checksum-verified at build time; a SHA-256 mismatch FAILS THE BUILD
# (fail-closed). Runtime is fully offline (HF_HUB_OFFLINE=1) and loads the
# baked weights from /opt/models — no Hugging Face egress ever (ADR-0021).

# ── Stage 1: fetch + verify weights (build-time only) ──────────────────
FROM python:3.12-slim AS model-fetch

# Pinned source of truth. Override at build with --build-arg to re-pin.
# Values resolved from the HF API on 2026-06-10 (Sprint B1 Day 1).
ARG MD_ASR_MODEL_REPO=Systran/faster-whisper-large-v3
ARG MD_ASR_MODEL_REVISION=edaa852ec7e145841d8ffdb056a99866b5f0a478
ARG MD_ASR_MODEL_SHA256=69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1

RUN pip install --no-cache-dir "huggingface_hub[cli]==0.25.2"

# Download at the immutable revision, then verify model.bin's SHA-256
# against the pinned digest. HF_TOKEN is mounted as a build secret and
# never persists in any layer; the public Systran repo does not require it,
# but private mirrors do.
# Retry on a broken stream: hf_hub resumes from the .incomplete file in this
# same layer. If every attempt fails, sha256sum -c below still fails closed.
ENV HF_HUB_DOWNLOAD_TIMEOUT=60
RUN --mount=type=secret,id=hf_token \
    set -eu; \
    if [ -f /run/secrets/hf_token ]; then HF_TOKEN="$(cat /run/secrets/hf_token)"; export HF_TOKEN; fi; \
    for attempt in 1 2 3 4 5; do \
      huggingface-cli download "$MD_ASR_MODEL_REPO" \
        --revision "$MD_ASR_MODEL_REVISION" \
        --local-dir /opt/models/whisper \
        --local-dir-use-symlinks False \
        --max-workers 2 && break; \
      echo "whisper download attempt ${attempt} failed; resuming in 10s"; \
      sleep 10; \
    done; \
    echo "${MD_ASR_MODEL_SHA256}  /opt/models/whisper/model.bin" | sha256sum -c -; \
    echo "model.bin checksum verified against pinned digest"


# ── Stage 1b: fetch + verify the ECAPA diarization weights ─────────────
# Ambient Capture v1: diarize=true batch jobs speaker-attribute the
# transcript. Same bake contract as dictation-service (ADR-0034):
# immutable revision, sha256 fail-closed, offline at runtime.
FROM python:3.12-slim AS ecapa-fetch

ARG MDX_DIAR_MODEL_REPO=speechbrain/spkrec-ecapa-voxceleb
ARG MDX_DIAR_MODEL_REVISION=0f99f2d0ebe89ac095bcc5903c4dd8f72b367286
ARG MDX_DIAR_MODEL_SHA256=0575cb64845e6b9a10db9bcb74d5ac32b326b8dc90352671d345e2ee3d0126a2
ARG MDX_DIAR_MEANVAR_SHA256=cd70225b05b37be64fc5a95e24395d804231d43f74b2e1e5a513db7b69b34c33

RUN pip install --no-cache-dir "huggingface_hub[cli]==0.25.2"

COPY scripts/models/prepare_ecapa.py /build/scripts/models/prepare_ecapa.py
COPY infra/models/ecapa/ /build/infra/models/ecapa/

ENV HF_HUB_DOWNLOAD_TIMEOUT=60
RUN --mount=type=secret,id=hf_token \
    set -eu; \
    if [ -f /run/secrets/hf_token ]; then HF_TOKEN="$(cat /run/secrets/hf_token)"; export HF_TOKEN; fi; \
    for attempt in 1 2 3 4 5; do \
      python /build/scripts/models/prepare_ecapa.py \
        --target /opt/models/ecapa \
        --revision "$MDX_DIAR_MODEL_REVISION" \
        --embedding-sha256 "$MDX_DIAR_MODEL_SHA256" \
        --meanvar-sha256 "$MDX_DIAR_MEANVAR_SHA256" && exit 0; \
      echo "ecapa download attempt ${attempt} failed; resuming in 10s"; \
      sleep 10; \
    done; \
    echo "ecapa download failed after 5 attempts" >&2; exit 1

# ── Stage 1c: fetch + verify the pyannote community-1 weights ──────────
# Diarizer v2 (Sprint 29, MDX_DIAR_ENGINE=pyannote). Same bake contract as
# the stages above; the assembly script is the single source of truth for
# the pins (docs/models/PINS.md). The upstream repo is GATED: the build
# needs `--secret id=hf_token,...` from an account that accepted the
# CC-BY-4.0 terms. The script reads the token straight from the secret
# mount (--token-file) — it never enters ARG, ENV, the shell environment
# or a layer. An unfilled pin, a checksum or config mismatch, or a
# gated-repo refusal exits 3 and FAILS THE BUILD without retrying.
FROM python:3.12-slim AS pyannote-fetch

ARG MDX_DIAR_V2_MODEL_REPO=pyannote/speaker-diarization-community-1
ARG MDX_DIAR_V2_MODEL_REVISION=3533c8cf8e369892e6b79ff1bf80f7b0286a54ee
# artifact -> sha256, the runtime MDX_DIAR_V2_PINS shape. The weight
# digests are EMPTY until resolved (`prepare_pyannote.py --resolve-pins`
# with a token); until then this stage refuses to build.
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

# ── Stage 2: runtime image ─────────────────────────────────────────────
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS runtime

# Re-declare ARGs so they are visible to LABEL/ENV in this stage.
ARG MD_ASR_MODEL_REPO=Systran/faster-whisper-large-v3
ARG MD_ASR_MODEL_REVISION=edaa852ec7e145841d8ffdb056a99866b5f0a478
ARG MD_ASR_MODEL_SHA256=69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1
ARG MDX_DIAR_MODEL_REPO=speechbrain/spkrec-ecapa-voxceleb
ARG MDX_DIAR_MODEL_REVISION=0f99f2d0ebe89ac095bcc5903c4dd8f72b367286
ARG MDX_DIAR_MODEL_SHA256=0575cb64845e6b9a10db9bcb74d5ac32b326b8dc90352671d345e2ee3d0126a2
ARG MDX_DIAR_MEANVAR_SHA256=cd70225b05b37be64fc5a95e24395d804231d43f74b2e1e5a513db7b69b34c33
ARG MDX_DIAR_V2_MODEL_REPO=pyannote/speaker-diarization-community-1
ARG MDX_DIAR_V2_MODEL_REVISION=3533c8cf8e369892e6b79ff1bf80f7b0286a54ee
ARG MDX_DIAR_V2_PINS='{"config.yaml":"7790f3cf805252b01622524f53c5eb390fb65ccbfd0ccd4b320a5addc887a873","embedding/pytorch_model.bin":"6f10ff60898a1d185fa22e1d11e0bfa8a92efec811f11bca48cb8cafebefd929","plda/plda.npz":"9b77bcd840692710dd3496f62ecfeed8d8e5f002fd991b785079b244eab7d255","plda/xvec_transform.npz":"325f1ce8e48f7e55e9c8aa47e05d2766b7c48c4b25b8de8dd751e7a4cc5fbe8f","segmentation/pytorch_model.bin":"7ad24338d844fb95985486eb1a464e32d229f6d7a03c9abe60f978bacf3f816e"}'

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.12 \
        python3.12-venv \
        python3.12-dev \
        python3-pip \
        ffmpeg \
        libsndfile1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 nonroot \
    && useradd --uid 65532 --gid 65532 --shell /sbin/nologin --no-create-home nonroot

RUN python3.12 -m pip install --no-cache-dir --upgrade pip uv==0.4.29

WORKDIR /build
COPY pyproject.toml uv.lock /build/
COPY libs/ /build/libs/
COPY services/asr-worker/ /build/services/asr-worker/

RUN python3.12 -m uv pip install --system --no-cache \
    --target /deps \
    /build/services/asr-worker \
    /build/libs/observability \
    /build/libs/auth \
    /build/libs/audit \
    /build/libs/db \
    /build/libs/messaging \
    /build/libs/crypto \
    /build/libs/storage \
    /build/libs/asr_models \
    /build/libs/diarization \
    /build/libs/secret

# Bake the verified weights from the fetch stages.
COPY --from=model-fetch /opt/models/whisper /opt/models/whisper-large-v3
COPY --from=ecapa-fetch /opt/models/ecapa /opt/models/ecapa
COPY --from=pyannote-fetch /opt/models/pyannote-community-1 /opt/models/pyannote-community-1

# Self-describing image (AC-B1-1): a deployed image carries its provenance.
LABEL mdx.model.repo="${MD_ASR_MODEL_REPO}" \
      mdx.model.revision="${MD_ASR_MODEL_REVISION}" \
      mdx.model.sha256="${MD_ASR_MODEL_SHA256}" \
      mdx.diar.v2.model.repo="${MDX_DIAR_V2_MODEL_REPO}" \
      mdx.diar.v2.model.revision="${MDX_DIAR_V2_MODEL_REVISION}"

# Editable workspace libs install as .pth files, which Python only honors
# in a site dir — not via PYTHONPATH. sitecustomize is auto-imported because
# /deps is on PYTHONPATH; it re-registers /deps as a site dir so the editable
# .pth files (asr_models, audit, observability, …) actually activate.
RUN printf 'import site\nsite.addsitedir("/deps")\n' > /deps/sitecustomize.py

ENV PYTHONPATH=/deps \
    PATH="/deps/bin:${PATH}" \
    # Cut the runtime cord to Hugging Face entirely (AC-B1-2).
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    # Load from the baked local dir instead of resolving a HF id at runtime.
    MD_ASR_MODEL=/opt/models/whisper-large-v3 \
    MD_ASR_MODEL_REPO="${MD_ASR_MODEL_REPO}" \
    MD_ASR_MODEL_REVISION="${MD_ASR_MODEL_REVISION}" \
    MD_ASR_MODEL_SHA256="${MD_ASR_MODEL_SHA256}" \
    MDX_DIAR_MODEL_DIR=/opt/models/ecapa \
    MDX_DIAR_MODEL_REPO="${MDX_DIAR_MODEL_REPO}" \
    MDX_DIAR_MODEL_REVISION="${MDX_DIAR_MODEL_REVISION}" \
    MDX_DIAR_MODEL_SHA256="${MDX_DIAR_MODEL_SHA256}" \
    MDX_DIAR_MEANVAR_SHA256="${MDX_DIAR_MEANVAR_SHA256}" \
    # Diarizer v2 (Sprint 29). MDX_DIAR_ENGINE stays at its `legacy`
    # default — switching engines is a deploy decision, not an image one.
    # The pins are re-verified at load (diarization.integrity).
    MDX_DIAR_V2_MODEL_DIR=/opt/models/pyannote-community-1 \
    MDX_DIAR_V2_MODEL_REPO="${MDX_DIAR_V2_MODEL_REPO}" \
    MDX_DIAR_V2_MODEL_REVISION="${MDX_DIAR_V2_MODEL_REVISION}" \
    MDX_DIAR_V2_PINS="${MDX_DIAR_V2_PINS}" \
    # pyannote.audio 4.x ships usage telemetry ON (otel.pyannote.ai);
    # config.py forces it off too — this is the image-level default.
    PYANNOTE_METRICS_ENABLED=false

# Model-provider registry (DEP-S0). The worker resolves ASR_BACKEND against
# this file at startup; the default `inproc_cpu_asr` keeps the baked whisper
# path. Env vars referenced by other backends are only required when that
# backend is enabled in the running ENV.
COPY --chown=nonroot:nonroot config/models.yaml /app/config/models.yaml
ENV MODELS_CONFIG=/app/config/models.yaml

USER nonroot
WORKDIR /app
CMD ["python3.12", "-m", "asr_worker.main"]
