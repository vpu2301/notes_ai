# IDX-B3 — Hardening, scheduled maintenance, observability & beta readiness

**Status:** delivered, with two items short — the load test could not be
run here, and the `users` view cleanup does not apply. See §"Not met".
**Branch:** S01 (uncommitted working tree).

## Inspect first

| Item | Finding |
| --- | --- |
| Scheduler pattern | ADR-0041: `observability.run_periodic(job_name, interval_seconds, fn, on_complete)`, hosted per service behind `MDX_BACKGROUND_JOBS`, no advisory lock, per-run audit row, `mdx_scheduler_job_*` metrics. Followed exactly; no second pattern added. |
| Alert-rule precedent | `services/autocomplete-service/tests/unit/test_alert_rules.py` — the metric-drift test the pack cites. Copied and extended. |
| k6 precedent | `scripts/loadtest/autocomplete-k6.js` + wrapper, grafana/k6 image, `host.docker.internal`, Prometheus scrape into a report. Copied. |
| CORS | `allow_headers=["Authorization", "Content-Type"]` — **`X-Client-Type` was missing.** See the defects below. |
| `auth_sessions` grants | SELECT/INSERT/UPDATE only. No DELETE — nothing had ever deleted a session. |
| `AUTH_SECRETS_KEKS_JSON` | Does not exist. IDX-A5 reused the `libs/crypto` envelope rather than a second key hierarchy, so "rotate the KEK" means "re-key through the envelope". |
| `users` compat view | Never created — IDX-B2 stopped short of dropping the `users` table, so there is no view to drop. |
| Argon2 / HIBP / `/auth/refresh` / `/auth/token` / invitations | None exist (IDX-A4, IDX-A2's remaining half, IDX-B1). |

## Two real defects found

* **`X-Client-Type` was not in CORS `allow_headers`.** A browser sending
  it triggers a preflight, and a preflight that is not allowed the header
  fails the whole call — so the SPA could declare its client type only by
  not declaring it. Fixed, along with `X-Request-Id`, and
  `Retry-After`/`X-Request-Id` added to `expose_headers` so a browser can
  actually read the rate-limit backoff it is given.
* **`expire-sessions` could not delete.** Migration 0024 never granted
  DELETE on `auth_sessions`, because until now nothing deleted a session —
  everything revoked one. Migration `0029` grants it deliberately, with
  the reasoning attached, rather than widening 0024 after the fact.

## Delivered

1. **Six maintenance jobs** (`auth_service/maintenance/`), each idempotent,
   batched and reporting its row count:
   `purge-challenges` (15 min), `expire-sessions` (hourly),
   `purge-deleted-identities` (daily), `sample-gauges` (5 min),
   `signing-key-status` (daily), `rotate-kek` (manual).
   Hosted by `run_periodic` behind `MDX_BACKGROUND_JOBS`, and each
   runnable as `python -m auth_service.maintenance <job>` — the **same**
   `run_job`, so a job run by hand emits the same metrics and does the
   same work. The CLI exits non-zero on failure; a cron that cannot fail
   is a cron nobody notices has stopped.
2. **The purge has one implementation.** `maintenance/purge_impl.py` is
   imported by both the scheduled job and
   `scripts/ops/idx-purge-deleted-identities.py`. An account deletion
   that behaved differently depending on who triggered it is the worst
   kind of bug to learn about from a subject-access request.
3. **Metrics** — `mdx_auth_maint_rows_total{job_name}`,
   `mdx_auth_maint_last_success_timestamp{job_name}` (set **only** on success,
   which is what makes the staleness alert mean anything),
   `mdx_auth_session_active`, `mdx_auth_device_active`, and
   `mdx_auth_denylist_push_failed_total` (added because a critical alert
   needed it — see below).
4. **Headers and limits** (`middleware/security_headers.py`) — `nosniff`
   and `no-referrer` everywhere; `no-store` on `/auth/*` and `/admin/*`
   via `setdefault`, so the JWKS keeps its `public, max-age=300` (it is a
   public key, and caching it is the point); `default-src 'none'` CSP plus
   `X-Frame-Options: DENY` on the HTML pages; 413 over 16 KiB.
5. **Nine new alerts** in an `auth-idx` rule group of their own, plus a
   drift test.
6. **Load test** — `scripts/loadtest/auth-k6.js` + `run-auth-loadtest.sh`,
   three scenarios, thresholds machine-enforced, report generator.
7. **Docs** — `docs/runbooks/idx-secrets.md` (inventory, rotation, leak
   response, where the TLS-dependent settings live),
   `docs/security/idx-pentest-checklist.md` (10 sections, ~60 executable
   items with pass criteria), a threat-model addendum, and an
   **"Alert response"** chapter in `docs/runbooks/auth.md` — one section
   per alert.

### The drift test earned its place immediately

The pack cites rules naming metrics nothing exports as the sprint-08/10
root cause. On first run the test found three:

* `mdx_auth_denylist_push_failed_total` — a **critical** alert I had just
  written against a metric IDX-A2 listed but never delivered. It would
  have sat green forever while revocations silently failed to reach the
  denylist. Now emitted from both push sites.
* `mdx_audit_chain_ok` / `mdx_audit_chain_last_verify_ts` — a false
  positive: they come from a Prometheus **textfile exporter**
  (`scripts/jobs/nightly_verify.py`), the exception
  `scripts/ci/check-metric-names.py` already documents. The test now
  scans the real producers rather than carrying an exemption list.

I then hardened it to check the runbook **anchor actually resolves to a
heading**, which found three pre-existing rules pointing into nothing and
two with no `runbook:` annotation at all. A link into nothing sends
whoever is paged at 3am to the top of a long document to search. All 15
rules now resolve.

## Verification

* auth-service unit **306 passed** (14 new: alert rules, headers/CORS).
* Integration **101 passed** (12 new maintenance tests — each job tested
  three ways: does the work, re-run is a no-op, **two concurrent runs
  converge**, which is the property ADR-0041 buys its no-lock simplicity
  with).
* The CLI exercised against the real database:
  `sample-gauges` reported `devices_active: 4` (B1b's seeded rooms),
  `purge-challenges` and `signing-key-status` ran clean, unknown job → exit 2.
* Migration `0029` applies and rolls back.
* `check-rls`, `check-identity-grants`, `check-alert-rules` (promtool),
  `lint-imports`, `check-metric-names`, `check-audit-insert`,
  `check-no-os-environ`, `check-no-crypto`, ruff, ruff format: green.

## Not met

| Criterion | Why |
| --- | --- |
| **Load-test report with measured numbers** | The `grafana/k6:0.57.0` image could not be pulled in this environment (timed out). The script and wrapper are written and syntax-checked, and the wrapper refuses to run against a service that is not in native mode — but **no numbers were measured**, so no report exists. Run `./scripts/loadtest/run-auth-loadtest.sh smoke` against a native auth-service to produce one. |
| **Jobs run for 3 days in staging** | Needs a staging deployment. Verified in-process and via the CLI here. |
| **Pen-test checklist executed internally** | Written, not executed. Roughly a third of it is already covered by automated tests (noted per row); the rest needs a person. |
| **Drop the `users` compat view** | Does not apply — IDX-B2 deliberately did not drop the `users` table, so no view exists. Belongs with B2's removal half. |
| **`check-no-keycloak.py` green** | 564 references remain. Gated on B2, which is gated on IDX-A4. |

## Adapted from the pack

* **Load-test targets.** The pack's table names `/auth/refresh`,
  `/auth/token` and Argon2 `/auth/login`. None exist. Measuring the
  Keycloak-backed login instead would produce a number describing
  software that is being deleted, so the script measures the native hot
  paths that do exist: `/auth/email/start` (Redis + DB + inline mail),
  `/auth/email/verify`, `/auth/oauth/token`, JWKS.
* **`expire-invitations`** — no invitations table (IDX-B1). Not stubbed.
* **`AUTH_SECRETS_KEKS_JSON` rotation** — replaced by the envelope re-key
  (`scripts/ops/idx-rekey-totp-secrets.py`), documented in the secrets
  runbook with the reasoning.
* **`HibpUnavailable` alert** — no HIBP integration (IDX-A4). Not added;
  an alert on a metric nothing emits is precisely what the drift test
  exists to prevent.

## Debt / NOT-NOW

- Grafana `auth-audit.json` panels were not updated. The alerts and the
  metrics behind them are in place; the dashboard is a follow-up and its
  panel queries should be checked against the new series names.
- `sample-gauges` publishes through the OTel meter, so the gauges only
  appear where the collector scrapes the service — a job run from cron
  exports nothing. That is fine for the in-process schedule and worth
  knowing before anyone alerts on a CLI run.
- WAF/CDN, SIEM, SOC2 evidence: NOT NOW (pack).
