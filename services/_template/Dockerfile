# ── Stage 1: build dependencies into a target directory ──────────────────────
FROM python:3.12-slim AS build

WORKDIR /build

RUN pip install --no-cache-dir uv==0.10.6
# Parallel compose builds starve PyPI fetches; raise uv's 30s default.
ENV UV_HTTP_TIMEOUT=600

COPY pyproject.toml .
RUN uv pip install --system --no-cache \
    --target /deps \
    .

COPY src/ /app/

# ── Stage 2: distroless final image (non-root) ────────────────────────────────
FROM gcr.io/distroless/python3-debian12:nonroot

WORKDIR /app

COPY --from=build /deps /deps
COPY --from=build /app /app

# Editable-lib .pth files only activate in a site dir, not via PYTHONPATH.
RUN printf 'import site\nsite.addsitedir("/deps")\n' > /deps/sitecustomize.py

ENV PYTHONPATH=/deps
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["-m", "uvicorn", "template_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
