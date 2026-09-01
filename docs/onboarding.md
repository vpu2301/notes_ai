# Onboarding

Goal: from a clean machine to a running Notes AI stack and a green test run
inside 30 minutes. If it takes longer, capture the friction in
`docs/onboarding-friction.md` so the next person hits a smoother path.

## 0. Prerequisites

| Tool | Minimum | Why |
| ---- | ------- | --- |
| Docker (with the Compose plugin) | 25.0 / 2.20 | Local stack |
| Python | 3.12 | Pinned in `.python-version` |
| `uv` | 0.4 | Workspace dependency manager (ADR-0001) |
| `make` | 4.0 | Command surface |
| `git` | 2.40 | … |

`make doctor` checks the lot and prints remediation hints.

## 1. Clone & verify

```bash
git clone https://github.com/your-org/notes-ai-backend
cd notes-ai-backend
make doctor
```

Re-run `make doctor` until every line is `✓`.

## 2. Bring up the stack

```bash
make dev-up      # Postgres, Redis, MinIO, Kafka, Keycloak, OTel + Loki + Prometheus + Grafana + Jaeger
make migrate-up  # apply SQL migrations to the `notes` database
make seed        # dev tenants, users, templates, starter content
make smoke       # curls every health endpoint
```

Infra URLs and credentials are listed in the README. Key points:

- **Database:** a single Postgres database named `notes`; every user-schema
  table is tenant-isolated via RLS (ADR-0004, ADR-0007).
- **Keycloak:** realm `notes` (issuer `http://keycloak:8080/realms/notes`),
  admin console at `http://localhost:8088` (`admin/admin`).
- **Roles:** `tenant_admin`, `member`, `viewer`, `auditor`, plus the
  machine-to-machine `service` role. The permission matrix lives in
  `docs/auth/permissions.csv`.

## 3. The services

`make dev-up` starts infra only; application services run on the host via
`make run-*` targets (or bring up everything in containers with a plain
`docker compose up` — see the README).

| Service | Port | What it does |
| ------- | ---- | ------------ |
| auth-service | 8000 | Identity, tenants, MFA, sessions, audit read API |
| asr-service | 8001 | Batch transcription (upload → job → transcript) |
| dictation-service | 8002 | Real-time streaming ASR over WebSocket (`dictation.v1`/`dictation.v2`), meeting mode + diarization |
| notification-service | 8004 | In-app feed, WebSocket push (`notifications.v1`), email |
| nlp-service | 8005 | Deterministic post-processing pipeline |
| note-service | 8006 | Notes, templates, versions, diff, search, PDF export |
| autocomplete-service | 8007 | Phrase/snippet suggestions |
| generation-service | 8009 | Inline ghost-text completion (local LLM) |
| asr-worker | — | Whisper inference worker (Redis Streams consumer, no HTTP port) |

## 4. Run the template service

```bash
cd services/_template
uv pip install -e ".[dev]"
cp .env.example .env.local            # defaults match the dev stack
uv run uvicorn template_service.main:app --reload
# In another terminal:
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

In Jaeger (`http://localhost:16686`), filter by
`service.name=template-service` and you should see one span per request. In
Loki (via Grafana, `http://localhost:3001`) the same request appears as a
JSON log line whose `trace_id` matches the span.

## 5. First PR walkthrough

1. Create a branch off `main`.
2. Make a tiny change (e.g. a docstring update in `services/_template`).
3. `make ci` locally — it mirrors CI exactly. Don't push if it's red.
4. Open a PR; the template walks you through the security checklist.
5. CI must be green for `lint`, `typecheck`, `test`, `security`,
   `import-linter`, and `container-scan` before merge.

## 6. Common friction

| Symptom | Likely cause | Fix |
| ------- | ------------ | --- |
| `make dev-up` hangs on Keycloak | Keycloak waits on Postgres readiness ~30 s on first boot | Be patient; subsequent boots are fast. |
| `make doctor` says "port 5432 in use" | A local Postgres is running | `brew services stop postgresql` (macOS) or `sudo systemctl stop postgresql` (Linux). |
| `uv` not found | Not installed | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `pre-commit` rejects your commit on `os.environ` | You read an envvar outside `config.py` | Move the read into the service's `config.py` Pydantic settings model. |
| Tests pass locally but `mypy --strict` fails in CI | Local mypy version drift | `uv run mypy --strict services/_template/src libs/...` |

## 7. Next steps

- Read [ADR-0003 (`Secret[T]`)](adr/0003-secret-typed-wrapper.md) and
  [ADR-0004 (`tenant_connection`)](adr/0004-rls-tenant-connection.md).
  Almost everything touches one or both.
- Skim the [glossary](glossary.md) and the
  [architecture notes](architecture/notes.md).
- Open `docs/onboarding-friction.md` and add anything that bit you.
