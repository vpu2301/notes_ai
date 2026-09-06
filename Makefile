.PHONY: smoke-ios test-egress check-no-vendor-import eval-smoke measure-turnaround dev-model hf-endpoints secret-scan dev-up dev-down dev-nuke dev-restart dev-logs smoke smoke-test lint lint-fix typecheck typecheck-all type-check test test-cov security security-scan ci ci-with-db doctor reset-db help pre-commit-install lint-imports check-no-os-environ check-no-direct-asyncpg dev-up-asr dev-up-gpu check-no-object-storage check-no-crypto check-no-demo-envvars-in-prod check-k8s-rendered k8s-render keycloak-test keycloak-export seed migrate-up migrate-down migrate-status openapi-dump openapi-check check-rls check-identity-grants check-identity-bridge check-auth-issuer-config check-audit-insert check-alert-rules check-metric-names check-notification-pii-free run-notification-digest validate-templates prepare-ecapa chaos-dictation chaos-asr load-dictation nightly-verify test-integration-db run-auth-service run-autocomplete-service run-generation-service run-notification-service web-e2e web-e2e-stack

COMPOSE = docker compose
COMPOSE_FILE = docker-compose.yml
# Kept ahead of the dev-stack Prometheus (v2.51.2) on purpose: promtool is
# only used to lint/test rule files, and the newer binary parses everything
# the older server does.
PROMTOOL_IMAGE = prom/prometheus:v2.54.1

##@ Local Development

dev-up: ## Start the full local stack (PostgreSQL, Redis, MinIO, Kafka, Keycloak, observability)
	$(COMPOSE) -f $(COMPOSE_FILE) up -d --wait
	@echo ""
	@echo "Stack is up. Service URLs:"
	@echo "  PostgreSQL   : localhost:5432"
	@echo "  Redis        : localhost:6379"
	@echo "  MinIO        : http://localhost:9000 (console: http://localhost:9001)"
	@echo "  Kafka        : localhost:9092"
	@echo "  Keycloak     : http://localhost:8088"
	@echo "  Jaeger UI    : http://localhost:16686"
	@echo "  Prometheus   : http://localhost:9090"
	@echo "  Grafana      : http://localhost:3000  (admin/admin)"
	@echo "  Loki         : http://localhost:3100"

# No `-v` on purpose: the Postgres volume holds every note, space and
# recording, plus the Keycloak realm. `dev-restart` runs this target, so a
# restart must never destroy data. Use `dev-nuke` for a clean slate, or
# `reset-db` to wipe just Postgres.
dev-down: ## Stop and remove all containers (named volumes are KEPT)
	$(COMPOSE) -f $(COMPOSE_FILE) down

dev-nuke: ## DESTRUCTIVE — stop containers AND delete all volumes (Postgres, MinIO, Kafka, …)
	@echo "This deletes every local note, space, recording and the Keycloak realm."
	@printf 'Type "nuke" to confirm: ' && read ans && [ "$$ans" = "nuke" ] || { echo "aborted"; exit 1; }
	$(COMPOSE) -f $(COMPOSE_FILE) down -v

dev-restart: dev-down dev-up ## Full restart of the local stack (data preserved)

dev-logs: ## Tail logs from all containers
	$(COMPOSE) -f $(COMPOSE_FILE) logs -f

smoke: ## Run smoke tests against the local stack (alias of smoke-test)
	@bash scripts/smoke-test.sh

smoke-test: smoke ## Legacy alias of `smoke`

keycloak-test: ## Smoke-test Keycloak: login → introspect → refresh → replay-rejected
	@bash scripts/dev/keycloak-test.sh

keycloak-export: ## Re-extract realm JSON from the running Keycloak container into infra/keycloak/
	@bash scripts/dev/keycloak-export.sh

seed: ## Seed the dev database with sample data
	uv run python scripts/seed/seed.py

run-auth-service: ## Run auth-service on :8000 for the SPA (needs dev-up + migrate-up + seed)
	# The SPA (VITE_AUTH_SERVICE_URL) expects auth-service at http://localhost:8000.
	# CORS allows the Vite dev origin (CORS_ALLOWED_ORIGINS); cookie is SameSite=lax.
	OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
	uv run --project services/auth-service uvicorn auth_service.main:app --host 0.0.0.0 --port 8000

run-autocomplete-service: ## Run autocomplete-service on :8007 (needs dev-up + migrate-up + seed)
	OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
	uv run --project services/autocomplete-service uvicorn autocomplete_service.main:app --host 0.0.0.0 --port 8007

run-generation-service: ## Run generation-service on :8009 (needs dev-up + a llama-server/Ollama backend, see ADR-0036)
	OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
	uv run --project services/generation-service uvicorn generation_service.main:app --host 0.0.0.0 --port 8009

run-notification-service: ## Run notification-service on :8004 (needs dev-up + migrate-up + seed)
	OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 \
	uv run --project services/notification-service uvicorn notification_service.main:app --host 0.0.0.0 --port 8004

doctor: ## Diagnose local environment issues
	@bash scripts/doctor.sh

##@ Models (DEP-S0 — libs/models, config/models.yaml)

dev-model: ## Start/verify the model servers on this Mac: `make dev-model` (start+verify), `make dev-model ARGS=verify`, `ARGS=stop`
	@bash scripts/dev/dev-model.sh $(ARGS)

eval-smoke: ## Smoke eval (5 synthetic meetings) against one backend: `make eval-smoke BACKEND=dev_mac`
	uv run --project libs/models python scripts/eval/smoke_eval.py --backend $(BACKEND)

test-egress: ## Prove the worker egress allowlist: example.com blocked, model endpoints reachable (needs staging/compose up)
	RUN_EGRESS_TEST=1 uv run pytest tests/integration/test_worker_egress.py -v

hf-endpoints: ## HF Inference Endpoints from deploy/hf/endpoints/*.yaml: `make hf-endpoints ARGS="plan --env staging"` (validate|plan|apply|status|pause|resume|delete)
	uv run python scripts/models/hf_endpoints.py $(if $(ARGS),$(ARGS),validate)

secret-scan: ## Scan the repo history for committed secrets (gitleaks; CI runs the same config)
	@command -v gitleaks >/dev/null || { echo "gitleaks not installed: brew install gitleaks"; exit 1; }
	gitleaks git --config .gitleaks.toml --redact --no-banner .

measure-turnaround: ## ASR turnaround on a fixture: `make measure-turnaround FIXTURE=10min_de BACKEND=dev_mac_asr` → docs/eval/turnaround-<date>-<backend>-<fixture>.json
	uv run --project libs/models python scripts/eval/measure_turnaround.py --fixture $(FIXTURE) --backend $(BACKEND)

##@ Code Quality

lint: ## Run ruff linter across all packages
	uv run ruff check .

lint-fix: ## Run ruff with auto-fix
	uv run ruff check --fix .

typecheck: ## Run mypy --strict over the CI-gated foundation packages (mirrors .github/workflows/ci.yml)
	uv run --with "mypy>=1.10" mypy --strict services/_template/src/ libs/observability/src/ libs/secret/src/ libs/auth/src/ libs/db/src/ libs/audit/src/ libs/messaging/src/

typecheck-all: ## Run mypy --strict over ALL packages (non-blocking; tracks feature-service typing debt)
	uv run --with "mypy>=1.10" mypy --strict services/_template/src/ libs/models/src/ libs/jobs/src/ services/asr-service/src/ services/asr-worker/src/ services/dictation-service/src/ services/nlp-service/src/ services/note-service/src/ libs/observability/src/ libs/secret/src/ libs/auth/src/ libs/db/src/ libs/audit/src/ libs/messaging/src/ libs/crypto/src/ libs/storage/src/ libs/asr_models/src/ libs/diarization/src/ libs/template_models/src/

type-check: typecheck ## Legacy alias of `typecheck`

test: ## Run pytest across services and libs
	# Each package has its own pyproject [tool.pytest.ini_options] (testpaths,
	# asyncio_mode). Several have a tests/__init__.py + tests/conftest.py.
	# pytest's pluggy registers conftests by module name; two `tests.conftest`
	# files in one invocation collide, so run each package separately.
	uv run --project services/_template pytest services/_template/tests/ -v
	uv run --project libs/secret pytest libs/secret/tests/ -v
	uv run --project libs/observability pytest libs/observability/tests/ -v
	uv run --project libs/db pytest libs/db/tests/unit/ -v
	uv run --project libs/messaging pytest libs/messaging/tests/ -v
	uv run --project libs/auth pytest libs/auth/tests/ -v
	uv run --project libs/audit pytest libs/audit/tests/unit/ -v
	uv run --project services/auth-service pytest services/auth-service/tests/ -v
	uv run --project libs/crypto pytest libs/crypto/tests/unit/ -v
	uv run --project libs/storage pytest libs/storage/tests/unit/ -v
	uv run --project libs/asr_models pytest libs/asr_models/tests/unit/ -v
	uv run --project libs/diarization pytest libs/diarization/tests/unit/ -v
	uv run --project libs/models pytest libs/models/tests/unit/ -v
	uv run --project libs/jobs pytest libs/jobs/tests/unit/ -v
	uv run --project libs/ratelimit pytest libs/ratelimit/tests/unit/ -v
	uv run pytest tests/unit/ -v
	uv run pytest tests/contract/ -v
	uv run --project services/asr-service pytest services/asr-service/tests/unit/ -v
	uv run --project services/asr-worker pytest services/asr-worker/tests/unit/ -v
	uv run --project services/dictation-service pytest services/dictation-service/tests/unit/ -v
	uv run --project services/nlp-service pytest services/nlp-service/tests/unit/ -v
	uv run --project libs/template_models pytest libs/template_models/tests/unit/ -v
	uv run --project libs/note_models pytest libs/note_models/tests/unit/ -v
	uv run --project services/note-service pytest services/note-service/tests/unit/ -v
	uv run --project libs/notification_events pytest libs/notification_events/tests/unit/ -v
	uv run --project services/notification-service pytest services/notification-service/tests/unit/ -v
	uv run --project services/autocomplete-service pytest services/autocomplete-service/tests/unit/ -v
	uv run --project services/generation-service pytest services/generation-service/tests/unit/ -v

test-cov: ## Run pytest with coverage report (gate ≥ 80%)
	uv run pytest services/_template/tests/ \
		--cov=template_service \
		--cov-report=term-missing \
		--cov-report=xml \
		--cov-fail-under=80

security: ## Run bandit (SAST) + pip-audit + semgrep
	# bandit: applies [tool.bandit] config (excludes tests, skips B101) and the
	# same confidence filter as CI. MEDIUM is informational; HIGH is blocking.
	uv run --with "bandit[toml]>=1.7.8" bandit -c pyproject.toml -r services/ libs/ --severity-level medium --confidence-level medium --exit-zero
	uv run --with "bandit[toml]>=1.7.8" bandit -c pyproject.toml -r services/ libs/ --severity-level high --confidence-level medium
	uv run --with pip-audit pip-audit || true
	uv run --with semgrep semgrep --config p/owasp-top-ten --error || true

security-scan: security ## Legacy alias of `security`

lint-imports: ## Verify architectural contracts (import-linter)
	# import-linter is not a venv dependency — pull it in for the run.
	uv run --with "import-linter>=2.0" lint-imports --config pyproject.toml

# The custom gates sweep APPLICATION SOURCE only (services/*/src, libs/*/src) —
# the domain where architecture rules #7/#8 bind. Integration tests, the
# migration runner, and operational scripts legitimately use raw asyncpg / env
# and are out of scope (the scripts' own exclusions cover config.py/tests too).
APP_SRC = git ls-files '*.py' | grep -E '^(services|libs)/[^/]+/src/'

check-no-os-environ: ## CI gate — os.environ/os.getenv reads only in config.py
	$(APP_SRC) | xargs uv run python scripts/dev/check-no-os-environ.py

check-no-direct-asyncpg: ## CI gate — raw asyncpg only in libs/db (use tenant_connection)
	$(APP_SRC) | xargs uv run python scripts/dev/check-no-direct-asyncpg.py

reset-db: ## Wipe and recreate the dev Postgres volume (also re-imports the Keycloak realm)
	$(COMPOSE) -f $(COMPOSE_FILE) down -v postgres
	$(COMPOSE) -f $(COMPOSE_FILE) up -d --wait postgres
	# Keycloak stores its realm in the SAME Postgres server (db `keycloak`).
	# Wiping the volume drops Keycloak's schema; without this recreate it keeps
	# a dead connection and every token request fails with `unauthorized_client`.
	# Force-recreate so it rebuilds schema + re-imports.
	$(COMPOSE) -f $(COMPOSE_FILE) up -d --force-recreate --wait keycloak

migrate-up: ## Apply pending SQL migrations against the dev DB
	uv run python scripts/db/migrate.py up

migrate-down: ## Roll back the most-recently-applied migration
	uv run python scripts/db/migrate.py down

migrate-status: ## Show applied + pending migrations
	uv run python scripts/db/migrate.py status

openapi-dump: ## Refresh docs/api/*-openapi.json from the running apps
	uv run python scripts/dev/dump-openapi.py

openapi-check: ## CI gate — fail if any committed OpenAPI snapshot drifts
	uv run python scripts/dev/dump-openapi.py >/dev/null
	@if [ -n "$$(git status --porcelain docs/api/*-openapi.json 2>/dev/null)" ]; then \
	    echo "OpenAPI snapshot is stale. Run: make openapi-dump"; \
	    git diff --no-color docs/api/*-openapi.json | head -80; \
	    exit 1; \
	fi
	@echo "OpenAPI snapshots are up to date."

check-rls: ## CI gate — every user-schema table has RLS+FORCE enabled
	uv run python scripts/ci/check-rls-policies.py

check-identity-bridge: ## CI gate (needs DB) — every active identity has its bridge `users` row (BE-1)
	uv run python scripts/ci/check-identity-bridge.py

check-audit-insert: ## CI gate — no direct audit.events writes outside libs/audit
	uv run python scripts/ci/check-no-direct-audit-insert.py

check-no-object-storage: ## CI gate — no direct boto3/aioboto3/minio outside libs/storage
	uv run python scripts/ci/check-no-direct-object-storage.py

check-no-crypto: ## CI gate — no direct cryptography.hazmat outside libs/crypto
	uv run python scripts/ci/check-no-direct-crypto.py

check-identity-grants: ## CI gate — app_role must not reach identity/credential secrets
	uv run python scripts/ci/check-identity-grants.py

check-auth-issuer-config: ## CI gate — services verify against AUTH_ISSUERS_JSON, never a literal issuer (FND-1)
	uv run python scripts/ci/check-auth-issuer-config.py

check-no-demo-envvars-in-prod: ## CI gate — demo/dev escape hatches never enabled in prod configs
	uv run python scripts/ci/check-no-demo-envvars-in-prod.py

check-dev-keys: ## CI gate — the dev-only auth signing key (infra/dev) never appears in a non-dev config (IDX-A2)
	uv run python scripts/ci/check-dev-keys.py

check-no-vendor-import: ## CI gate — no model-vendor SDK (anthropic/openai/huggingface_hub/…) outside libs/models (DEP-S0)
	uv run python scripts/ci/check-no-vendor-import.py

check-k8s-rendered: ## CI gate — chart renders; prod render secret-clean; vendored ops files drift-checked
	uv run python scripts/ci/check-k8s-rendered.py

k8s-render: ## Render the Helm chart (staging + prod) to temp files for inspection
	helm template notes infra/k8s/notes > /tmp/notes-render-staging.yaml
	helm template notes infra/k8s/notes -f infra/k8s/notes/values-prod.yaml > /tmp/notes-render-prod.yaml
	@echo "rendered: /tmp/notes-render-staging.yaml /tmp/notes-render-prod.yaml"

check-notification-pii-free: ## CI gate (BLOCKING) — no email template may render note content or personal data
	uv run python scripts/ci/check-notification-pii-free.py

run-notification-digest: ## Run the daily notification digest once (cron entrypoint)
	uv run --project services/notification-service python -m notification_service.jobs.digest

smoke-notes: ## Exercise every note operation end to end against the running stack (docker compose up)
	uv run --project services/note-service python scripts/smoke/notes_e2e.py

smoke-ios: ## IOS-0 — web-created account → sign in as the phone does → 1s capture → note (needs the stack up)
	@# Not run by CI, for the same reason `web-e2e` is not: it needs the
	@# whole stack including an asr-worker that bakes whisper-large-v3
	@# (2.7 GiB), and the iOS job runs on a macOS runner with no Docker.
	@# Point it at a stack that is already up — `make dev-up`, or
	@# `make web-e2e-stack` if you also want the Mailpit half.
	uv run --project services/note-service python scripts/smoke/ios_signup_e2e.py $(ARGS)

web-e2e-stack: ## Bring the stack up in the shape the browser tests need (native identity + Mailpit)
	@# `MDX_IDP_MODE=native` is the whole point: `/auth/email/*` is mounted
	@# only in that mode, so under the default `keycloak` every one of these
	@# tests would 404 at the first step. The SMTP override is the other
	@# half — a developer with a real relay in their `.env` must not have a
	@# test suite mailing sign-in codes to the internet.
	MDX_IDP_MODE=native \
	MDX_EMAIL_PROVIDER=smtp \
	MDX_AUTH_SMTP_HOST=mailpit \
	MDX_AUTH_SMTP_PORT=1025 \
	MDX_AUTH_SMTP_USE_TLS=false \
	MDX_AUTH_EMAIL_FROM=sales@notes-ai.local \
	$(COMPOSE) -f docker-compose.yml -f docker-compose.override.yml up -d --wait \
	    postgres redis minio mailpit auth-service note-service asr-service asr-worker
	@echo ""
	@echo "auth-service is in native mode. Mailpit inbox: http://localhost:8025"
	@echo "Put it back with: make dev-up"

web-e2e: ## Run the Playwright first-use suite (needs `make web-e2e-stack`)
	@# Not depending on web-e2e-stack: recreating four containers on every
	@# run turns a 40-second suite into a four-minute one, and the stack is
	@# the slow half. Bring it up once, iterate on the tests.
	cd web && npm ci && npx playwright install --with-deps chromium && npm run test:e2e

validate-templates: ## CI gate — validate every note-template seed JSON
	PYTHONPATH=libs/template_models/src uv run python scripts/validate-templates.py

check-alert-rules: ## CI gate — promtool syntax check + alert unit tests
	@# Syntax alone is not enough: a valid rule that never fires reads as
	@# "no problem" on a green dashboard. rules/tests/ proves each alert
	@# actually fires on the failure it claims to watch.
	@# --entrypoint sh: docker run does not expand globs (no shell), and
	@# promtool takes explicit paths only.
	docker run --rm -v "$(PWD)/infra/prometheus/rules:/rules:ro" \
	    --entrypoint sh $(PROMTOOL_IMAGE) -c \
	    'promtool check rules /rules/*.yml && promtool test rules /rules/tests/*.yml'

check-metric-names: ## CI gate — exported metric names must match the declared instruments
	uv run python scripts/ci/check-metric-names.py

prepare-ecapa: ## Fetch + checksum-verify the pinned ECAPA speaker-diarization model (ADR-0034)
	uv run python scripts/models/prepare_ecapa.py

chaos-dictation: ## Run dictation chaos scenarios (needs dev stack + token)
	RUN_DICTATION_CHAOS=1 uv run --project services/dictation-service pytest tests/chaos/dictation_chaos.py -v

chaos-asr: ## Run batch-ASR worker chaos (SIGKILL reclaim; needs dev stack + asr-service + CPU model + token)
	RUN_ASR_CHAOS=1 uv run --project services/asr-service pytest tests/chaos/asr_chaos.py -v

load-dictation: ## Run dictation load test (needs dev stack + token)
	RUN_DICTATION_LOAD=1 uv run --project services/dictation-service pytest tests/load/ -v

dev-up-asr: ## Start base + dev overlay (no GPU) — useful on laptops
	$(COMPOSE) -f infra/compose/base.yml -f infra/compose/dev.yml up -d --wait

dev-up-gpu: ## Start base + dev + GPU overlay (requires NVIDIA toolkit)
	$(COMPOSE) -f infra/compose/base.yml -f infra/compose/dev.yml -f infra/compose/gpu.yml up -d --wait

nightly-verify: ## Run the audit-chain nightly verifier once and emit Prom textfile
	PROM_TEXTFILE=/tmp/audit_chain.prom uv run python scripts/jobs/nightly_verify.py

test-integration-db: ## All integration tests against the live dev DB (needs migrate-up)
	RUN_DB_INTEGRATION=1 uv run --project libs/db pytest libs/db/tests/integration/ -v
	RUN_DB_INTEGRATION=1 uv run --project libs/audit pytest libs/audit/tests/integration/ -v
	RUN_DB_INTEGRATION=1 RUN_KEYCLOAK_INTEGRATION=1 uv run --project services/auth-service pytest services/auth-service/tests/integration/ -v
	RUN_DB_INTEGRATION=1 uv run --project libs/jobs pytest libs/jobs/tests/integration/ -v

ci: lint typecheck test security lint-imports check-no-os-environ check-no-direct-asyncpg check-audit-insert check-no-object-storage check-no-crypto check-no-demo-envvars-in-prod check-no-vendor-import check-k8s-rendered check-notification-pii-free validate-templates check-alert-rules check-metric-names ## Mirror CI gates locally

ci-with-db: ci check-rls check-identity-bridge openapi-check ## Full CI mirror — needs `make dev-up && make migrate-up`

pre-commit-install: ## Install the pre-commit hook into git
	@command -v pre-commit >/dev/null || (echo "Install pre-commit: pip install pre-commit"; exit 1)
	pre-commit install
	pre-commit install --hook-type commit-msg

##@ Misc

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)
