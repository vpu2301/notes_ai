# autocomplete-service runtime (sitecustomize re-adds /deps for the nonroot user).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 nonroot \
    && useradd --uid 65532 --gid 65532 --shell /sbin/nologin --no-create-home nonroot

RUN pip install --no-cache-dir --upgrade pip uv==0.10.6
# Parallel compose builds starve PyPI fetches; raise uv's 30s default.
ENV UV_HTTP_TIMEOUT=600

WORKDIR /build
COPY pyproject.toml uv.lock /build/
COPY libs/ /build/libs/
COPY services/autocomplete-service/ /build/services/autocomplete-service/

RUN uv pip install --system --no-cache \
    --target /deps \
    /build/services/autocomplete-service \
    /build/libs/observability \
    /build/libs/auth \
    /build/libs/audit \
    /build/libs/db \
    /build/libs/secret \
    /build/libs/crypto \
    /build/libs/storage

RUN printf 'import site\nsite.addsitedir("/deps")\n' > /deps/sitecustomize.py

ENV PYTHONPATH=/deps \
    PATH="/deps/bin:${PATH}"

USER nonroot
WORKDIR /app
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "autocomplete_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
