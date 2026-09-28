# ── auth-service runtime ───────────────────────────────────────────
# Mirrors the report-service paved-road pattern: install the service +
# its workspace-lib closure into /deps, then re-activate the editable
# .pth redirects via sitecustomize (see CLAUDE.md "New service Dockerfile").
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 nonroot \
    && useradd --uid 65532 --gid 65532 --shell /sbin/nologin --no-create-home nonroot

RUN pip install --no-cache-dir --upgrade pip uv==0.10.6
# PyPI fetches share the link with the torch wheels of the ASR images when
# `docker compose build` runs everything at once; bump uv's 30s default so a
# slow index response doesn't fail the build.
ENV UV_HTTP_TIMEOUT=600

WORKDIR /build
COPY pyproject.toml uv.lock /build/
COPY libs/ /build/libs/
COPY services/auth-service/ /build/services/auth-service/

RUN uv pip install --system --no-cache \
    --target /deps \
    /build/services/auth-service \
    /build/libs/observability \
    /build/libs/auth \
    /build/libs/audit \
    /build/libs/db \
    /build/libs/secret \
    /build/libs/ratelimit \
    /build/libs/crypto \
    /build/libs/notification_events

RUN printf 'import site\nsite.addsitedir("/deps")\n' > /deps/sitecustomize.py

ENV PYTHONPATH=/deps \
    PATH="/deps/bin:${PATH}"

USER nonroot
WORKDIR /app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "auth_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
