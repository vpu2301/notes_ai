# Cleanup sprint — left alone (owner decisions)

Not touched by the sprint (2026-10-22). Each row: what, why it stayed, recommendation.

## 1. Needs action (consequences of the sprint)

| Item | Why left | Recommendation |
|---|---|---|
| `infra/k8s/notes/values.yaml` (`dictation-service`, `autocomplete-service`, `keda` block), `values-prod.yaml` (`dictation-service`, `keda`), `templates/scaling.yaml`, `scripts/k8s/staging-up.sh` (2 image names, KEDA echo) | Editing the prod Helm chart was refused by the agent's permission check. | Remove these entries before the next staging/prod deploy — the chart still deploys two images that are no longer built. |
| Dev containers `notes-ai-dictation-service-1`, `notes-ai-autocomplete-service-1` | The agent does not stop containers. | `docker compose up -d --remove-orphans`. |
| `docs/api/asr-service-openapi.json` | Differs from the app because of the uncommitted Sprint S1 change (new drop reason + `segment_index`). | Run `make openapi-dump` with the S1 commit, or `make openapi-check` fails in CI. |
| `infra/prometheus/rules/templates.yml`, `infra/grafana/dashboards/templates.json` | Still query `mdx_dictation_section_switch*`; mixed files. | Drop the dictation panel and rule. |

## 2. Possible bugs found (not dead code)

| Item | Finding | Recommendation |
|---|---|---|
| `libs/diarization/src/diarization/http_engine.py:72` | `_per_audio_second` stored, never read → asr-worker's `diar_http_seconds_per_audio_second` has no effect. | Apply it to the HTTP diarizer timeout, or delete the setting. |
| Prometheus rules / Grafana panels on metrics nothing emits | note `generation_seconds`, `snapshots_swept`, `budget_blocked`; notification `fanout_latency_ms`; nlp punctuation_fallback / voice_commands / undo_rate / cache_hit_ratio. | Emit the metrics or delete the panels and alerts — today they can never fire. |
| `services/note-service/src/note_service/jobs/chain_reconciler.py` | No cron/k8s/compose entry: never runs. | Schedule it or delete it. |
| `scripts/jobs/billing_expiry.py` | No cron/k8s entry. | Schedule it or delete it. |
| `scripts/dev/tests`, `scripts/db/tests` | No Makefile/CI line collects them. | Add them to `make test`. |
| `tests/contract`-adjacent: `libs/auth` perms matrix, `docs/runbooks/auth.md`, note-move `note_instructions` gap, web `tests/evidence.test.tsx` | Pre-existing test failures (6 Python, 1 web). | Fix in a normal sprint; they predate the cleanup. |

## 3. Probably dead, kept for safety

| Item | Why left | Recommendation |
|---|---|---|
| `tests/fixtures/eval/notes/multilingual/` (24 files) | No reader since R0, but still a valid corpus via `CORPUS=`. | Keep if the multilingual critical suite comes back; else delete. |
| `docs/eval/notes-pipeline-2026-10-*.json` (21 files, ~118k lines) | Cited by glob in `docs/eval/routing-waivers.yaml`. | Delete together with those waivers when they expire. |
| `docs/eval/grid-2026-09-19-legacy.json` | Only record of the S28 no-ship verdict. | Keep. |
| `web/src/api/notes.ts` 8 unused wrappers + `PublicLink` type; macOS/iOS `APIClient` unused methods; `NoteCollaboration.dismissUnsent()` | Read-only client API layer. | Delete in a client sprint if the endpoints are not planned. |
| iOS `JobStatus` `tint`/`soft`/`label`, `Biometrics.symbol` | Only readers were removed; names are textually common and iOS tests cannot run here. | Delete, then run `ios/scripts/test.sh`. |
| Shared code whose only caller was dictation-service: diarization streaming/offline (`DiarizationStream`, `SharedDiarizationEngine`, `DiarizationConfig`), `crypto` CTR stream, parts of `asr_worker.inference` | Public lib surface. | Run one more dead-code pass now that dictation is gone. |
| Repository methods holding SQL (auth identity_repository ×3; note generation/glossary/meetings repos) | Persistence surface. | Delete with a DB-aware review. |
| Audit-kind constants, wire/error enum members, settings fields | Persisted, wire or config values. | Keep. |
| ~20 helpers used only by tests | Deleting means deleting tests. | Keep. |
| Unused workspace-lib deps in services (asr-worker `auth`, generation/nlp/notification `secret`, nlp/note `asr_models`) | Dockerfiles install them too. | Remove from pyproject and Dockerfile together. |
| `libs/db` `alembic` dependency | libs/db is read-only; migrations are raw SQL. | Remove with a libs/db change. |
| Operator tools: `auth_service/ops/onboard.py`, `scripts/ops/erase_*` (GDPR), `idx-provision-device.py`, `backfill_action_items.py`, `scripts/admin/note_chain_repair.py`, `scripts/ci/check-no-keycloak.py`, `scripts/dev/auth-test.sh`, `tests/load/shared_page.js`, `scripts/loadtest/auth-k6.js`, `tests/load/diarization/long_recording.py` | Hand-run by design. | Keep; delete `backfill_action_items.py` if pre-0037 data is gone. |
| `tests/load/` package | `make load-dictation` was its only runner (removed with dictation); remaining files are manual tools. | Keep as manual tools. |
| `infra/k8s/notes/files/*` copies of job scripts | Helm needs in-chart copies; drift-gated. | Keep. |
| Keycloak realm clients for dictation/autocomplete, `libs/auth` perms rows, `docs/auth/permissions.csv`, `dictation_sessions` + autocomplete tables and seeds, `docs/audit/event-kinds.md` kinds, notification `DICTATION_COMPLETED` | Auth config and data. | Keep until a data-retention decision; old dictation notes still replay. |
| Swift `DSBrandMark`, `SystemAudioSource.onDeviceChange`, `LegacyCredentials.exists/purge`, iOS VM methods the Mac uses | Cited reference / protocol requirement / Keychain / cross-app. | Keep. |
| Byte-identical twins (web↔PDF fonts, `middleware.py` pairs, macOS/iOS test twins), 449 jscpd near-duplicate blocks (7,700 lines macOS↔iOS) | Dedup needs a move or a new dependency edge. | Biggest remaining saving: move shared Swift into `clients/Shared` in its own sprint. |
| Stale prose after R0: `scripts/eval/notes_eval.py` comments, `routing-waivers.yaml:71`, `error-taxonomy.md:91`, `web/src/styles/components.css:255` (`DSSearchField`) | Comments/docs, not code. | Fix with the next docs pass. |
