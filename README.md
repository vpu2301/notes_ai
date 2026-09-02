# Notes AI — Backend

> Backend for an AI-powered **business notes & meeting transcription** product:
> record voice notes or meetings, get live transcripts (with speaker separation),
> clean them up automatically, and turn them into structured, versioned,
> searchable notes.

> **Target onboarding time:** < 30 minutes from `git clone` to a running local stack.

---

## What it does

- **Voice notes & dictation** — real-time streaming speech-to-text over WebSocket
  (faster-whisper), plus a batch transcription pipeline for uploaded audio.
- **Ambient meeting capture** — speaker diarization (who said what) with
  client-side speaker naming, from a laptop/phone in the room, a dedicated
  meeting-room device (least-privilege `device` identity), or an uploaded
  recording (`diarize=true` batch jobs). See
  [docs/architecture/ambient-capture.md](docs/architecture/ambient-capture.md)
  and [docs/product/ambient-use-cases.md](docs/product/ambient-use-cases.md).
- **Notes** — template-based structured notes (meeting notes, 1-on-1s, sales calls,
  interview debriefs, project updates), autosaving drafts, append-only versions with
  diff and tamper-evident hash-chaining, full-text search with synonyms, PDF export
  with tenant branding, audio replay clips.
- **Text intelligence** — deterministic NLP post-processing (voice commands,
  punctuation, number/date normalization, abbreviations), phrase autocomplete,
  and inline AI ghost-text completion (local LLM).
- **Multi-tenant platform** — Keycloak auth (MFA, sessions, password recovery),
  tenant workspaces with roles (`tenant_admin`, `member`, `viewer`), audit trail,
  envelope encryption for all stored audio/transcripts, notifications
  (in-app feed, WebSocket push, email).

Languages: English and Ukrainian first-class (German plumbing present).

---

## Repository layout

```
notes_ai/
├── services/               # Independently deployable FastAPI services
│   ├── _template/          # Baseline template — copy this to create a new service
│   ├── auth-service/       # Identity, tenants, MFA, sessions, audit read API
│   ├── asr-service/        # Batch transcription API (upload → job → transcript)
│   ├── asr-worker/         # Whisper inference worker (Redis Streams consumer)
│   ├── dictation-service/  # Real-time streaming ASR over WebSocket + diarization
│   ├── nlp-service/        # Post-processing pipeline (punctuation, normalization…)
│   ├── note-service/       # Notes, templates, versions, diff, search, PDF
│   ├── autocomplete-service/ # Phrase/snippet suggestions (MARISA trie)
│   ├── generation-service/ # Inline ghost-text completion (local LLM)
│   └── notification-service/ # Feed, WebSocket push, email
├── libs/                   # Internal shared Python packages (uv workspace members)
│   ├── auth/               # JWT verification, Keycloak integration
│   ├── db/                 # Async engine factory, RLS tenant connections
│   ├── observability/      # Structured logging, OTel tracing + metrics, PII filter
│   ├── audit/              # Tamper-evident hash-chained audit recorder
│   ├── crypto/ storage/    # Envelope encryption + encrypted object storage
│   ├── messaging/          # Redis Streams producer/consumer abstractions
│   ├── asr_models/ note_models/ template_models/ notification_events/  # typed contracts
│   └── secret/             # Non-leaking Secret[T] wrapper
├── infra/                  # Docker Compose supporting config
│   ├── grafana/ prometheus/ loki/ otel/   # Observability stack config
│   ├── keycloak/           # Realm export (imported on first start)
│   ├── postgres/           # init SQL + migrations + seed
│   ├── seeds/templates/    # System note templates (JSON)
│   └── k8s/notes/          # Helm chart
├── scripts/                # doctor, smoke-test, seed, CI gates, migrations runner
├── docs/                   # ADRs, runbooks, API snapshots, architecture notes
├── docker-compose.yml      # Infra only (make dev-up)
├── docker-compose.override.yml  # Full stack in containers (docker compose up)
├── Makefile
└── pyproject.toml          # uv workspace root
```

---

## Prerequisites

| Tool | Minimum | Install |
|------|---------|---------|
| Docker + Compose plugin | 25.0 / 2.20 | https://docs.docker.com/get-docker/ |
| Python | 3.12 | https://python.org |
| uv | 0.4 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| make | any | OS package manager |
| git | 2.40 | https://git-scm.com |

> **Windows:** WSL2 is required for acceptable Docker performance. Run `make doctor` to verify.

---

## Quickstart (< 5 minutes)

```bash
# 1. Check your environment
make doctor

# 2. Start the infra stack (PostgreSQL, Redis, MinIO, Kafka, Keycloak, observability)
make dev-up

# 3. Apply migrations and seed the dev database
make migrate-up
make seed

# 4. Verify everything is healthy
make smoke-test
```

### Service URLs after `make dev-up`

| Service | URL | Credentials |
|---------|-----|-------------|
| PostgreSQL | `localhost:5432` | `postgres/postgres` |
| Redis | `localhost:6379` | — |
| MinIO (API) | `http://localhost:9000` | `minioadmin/minioadmin` |
| MinIO (Console) | `http://localhost:9001` | `minioadmin/minioadmin` |
| Kafka | `localhost:9092` | — |
| Keycloak | `http://localhost:8088` | `admin/admin` |
| Jaeger UI | `http://localhost:16686` | — |
| Prometheus | `http://localhost:9090` | — |
| Grafana | `http://localhost:3001` | `admin/admin` |
| Loki | `http://localhost:3100` | — |

---

## Run the ENTIRE backend (infra + all services) in Docker

`make dev-up` starts **infra only** (the documented dev loop runs services on
the host via `make run-*`). To bring up the **whole backend** — every
application service, plus a one-shot DB migrate and seed — in containers:

```bash
docker compose build      # builds all service images (+ the migrate/seed tools image)
docker compose up         # infra → migrate → seed → keycloak → services
```

This works because `docker-compose.override.yml` is auto-merged on a plain
`docker compose` invocation. `make dev-up` passes `-f docker-compose.yml`
explicitly, which disables the override — so it stays infra-only, unchanged.

| Service | URL | Notes |
|---------|-----|-------|
| auth-service | `http://localhost:8000` | the SPA expects this origin |
| asr-service | `http://localhost:8001` | batch transcription submit/status |
| dictation-service | `http://localhost:8002` | streaming ASR (WebSocket), meeting mode |
| notification-service | `http://localhost:8004` | feed + WebSocket push + email (Mailpit dev sink on :8025) |
| nlp-service | `http://localhost:8005` | post-processing pipeline |
| note-service | `http://localhost:8006` | notes, templates, versions, search, PDF |
| autocomplete-service | `http://localhost:8007` | phrase suggestions |
| generation-service | `http://localhost:8009` | inline completion (needs a llama-server/Ollama backend, ADR-0036) |
| asr-worker | — | Redis-stream consumer (no HTTP port) |

> **First build downloads models.** `asr-worker` and `dictation-service` bake
> pinned `faster-whisper` weights from Hugging Face at build time (offline at
> runtime), so the first `docker compose build` needs network and takes longer.
> All services run CPU-only here; add `-f infra/compose/gpu.yml` for the CUDA
> overlay. The dev override needs **12 GiB** of Docker engine memory (Whisper
> large-v3 ×2 + the diarizer) — see the header of `docker-compose.override.yml`.

Health-check every service once up:

```bash
for p in 8000 8001 8002 8004 8005 8006 8007 8009; do
  curl -s -o /dev/null -w "%{http_code}  :$p/healthz\n" http://localhost:$p/healthz
done
```

---

## API documentation

- Every service serves interactive docs at `http://localhost:<port>/docs` (Swagger UI).
- Committed OpenAPI snapshots live in [`docs/api/`](docs/api/) — one JSON per
  service, kept fresh by `make openapi-dump` and gated by `make openapi-check` in CI.
- WebSocket protocols are hand-documented: [`docs/api/dictation-ws-v1.md`](docs/api/dictation-ws-v1.md),
  [`docs/api/dictation-ws-v2.md`](docs/api/dictation-ws-v2.md),
  [`docs/api/notifications-ws-v1.md`](docs/api/notifications-ws-v1.md).

---

## Running the template service locally

```bash
cd services/_template
uv pip install -e ".[dev]"
cp .env.example .env.local
uv run uvicorn template_service.main:app --reload
# Visit: http://localhost:8000/docs
```

### Creating a new service

```bash
cp -r services/_template services/my-service
# Rename package, update pyproject.toml name/description, add to infra as needed
```

---

## Development commands

```bash
make lint          # ruff check
make typecheck     # mypy --strict (foundation packages)
make test          # pytest across all packages
make test-cov      # pytest with coverage report
make security      # bandit + pip-audit + semgrep
make migrate-up    # apply SQL migrations
make seed          # seed dev tenants, users, templates, starter content
make openapi-dump  # refresh docs/api/*-openapi.json
make dev-down      # stop & remove containers
make doctor        # environment health check
make help          # full target list
```

---

## CI pipeline

Every pull request runs automatically on GitHub Actions:

1. **Lint** — `ruff check` + `ruff format --check`
2. **Type check** — `mypy --strict`
3. **Tests** — `pytest` with coverage gate ≥ 80%
4. **Architecture** — import-linter contracts + custom gates (no raw env reads,
   no direct asyncpg/crypto/object-storage, audit-writer only, template seeds valid)
5. **Security** — `bandit` (SAST) + `semgrep` (OWASP Top 10, secrets)
6. **Container scan** — `trivy` (CRITICAL/HIGH CVEs fail the build)
7. **K8s** — Helm chart renders; prod render is secret-clean
8. **Publish** — builds and pushes to GHCR on merge to `main` with semver tags

---

## Observability

All services emit traces, metrics, and logs to the local OTel Collector:

- **Traces** → Jaeger (`http://localhost:16686`)
- **Metrics** → Prometheus (`http://localhost:9090`) → Grafana
- **Logs** → Loki → Grafana (`http://localhost:3001`)

Dashboards are auto-provisioned from `infra/grafana/dashboards/`.

### PII safety

`libs/observability` includes a `PIISafeFilter` that redacts sensitive fields
(names, emails, phones, transcripts, audio references, …) from all log output
before they can be written anywhere. Notification emails carry pointers only —
never note content (enforced by a CI gate).

---

## Architecture decisions

Key ADRs (full index: [docs/adr/README.md](docs/adr/README.md)):

| # | Decision |
|---|----------|
| 0001 | Python version pin and `uv` workspace |
| 0004 | Single-helper tenant connection (Postgres RLS) |
| 0008 | Tamper-evident audit hash chain |
| 0009 | faster-whisper for ASR |
| 0011 | Three-layer envelope encryption for stored audio/transcripts |
| 0012 | WebSocket (not WebRTC) for streaming dictation |
| 0016 | JSONB note templates with cosmetic/structural edit classification |
| 0020 | Append-only note versioning |
| 0025 | Autocomplete trie + Redis |
| 0029/0030 | Redis Streams notification bus + pub/sub WS fan-out |
| 0034 | Speaker diarization (ECAPA) for meeting mode |
| 0036 | Local LLM (llama.cpp) for inline completion |
| 0039 | TOTP MFA |

---

## Security notes

- **AUTH_BYPASS_DEV=true** disables JWT enforcement for local development only.
  The service logs a `WARNING` on startup when this is set. It **must never** be
  enabled in staging or production.
- Never commit `.env`, `.env.local`, `*.pem`, or `*.key` files — they are gitignored.
- All stored audio and transcripts are envelope-encrypted per tenant
  (KEK_master → KEK_tenant → DEK_object); see `libs/crypto`.
