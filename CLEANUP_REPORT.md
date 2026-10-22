# Cleanup sprint — report

2026-10-22 · branch `cleaning-branch` · base `ce7f25a` · no commits by the agent (owner commits).
Uncommitted Sprint S1 work (6 files) is excluded from every figure below.

## Result

| Metric | Baseline | Final | Δ |
|---|---:|---:|---:|
| Tracked files (`git ls-files`) | 2,153 | 1,950 | −203 |
| Code lines, all languages (cloc) | 577,008 | 552,907 | −24,101 |
| Python code lines | 136,476 | 123,482 | −12,994 |
| Swift code lines | 51,044 | 50,868 | −176 |
| TypeScript code lines | 32,206 | 32,171 | −35 |
| JSON lines | 179,104 | 169,897 | −9,207 |
| Markdown files | 39 | 31 | −8 |
| Services | 10 | 8 | −2 |
| `git diff --shortstat` | | 275 files | +23 / −29,127 |

cloc counts code only (no blanks/comments); the diff counts every line.

| Package | Deleted lines | Notes |
|---|---:|---|
| services/dictation-service | 10,808 | removed (owner decision) |
| services/autocomplete-service | 5,175 | removed (owner decision) |
| docs (eval reports, 2 openapi snapshots, 8 .md) | 6,755 | |
| infra (3 alert-rule files + test, 3 dashboards, compose overlays) | 1,793 | k8s untouched |
| tests (fixtures, dead test, dictation chaos/load) | 1,538 | |
| eval (`eval/instructions/v1` corpus) | 815 | |
| scripts | 782 | |
| services/note-service | 596 | |
| uv.lock | 233 | no version changes |
| macOS / iOS / clients/Shared | 173 / 36 / 5 | |
| other services + libs | 245 | |
| root files (pyproject, Makefile, README, compose override) | 131 | |
| web | 42 | bundle unchanged |

### Dependencies

| Package | Runtime | Dev |
|---|---|---|
| libs/audit | 3 → 2 (pydantic) | 5 → 4 (hypothesis) |
| libs/auth | 6 → 6 | 6 → 5 (pytest-cov) |
| libs/jobs | 7 → 6 (pydantic) | 5 → 5 |
| libs/ratelimit | 1 → 0 (redis) | 4 → 4 |
| services/asr-service | 24 → 23 (aioboto3) | 5 → 5 |
| services/asr-worker | 25 → 24 (aioboto3) | 4 → 4 |
| services/nlp-service | 17 → 16 (httpx) | 5 → 4 (httpx) |
| services/note-service | 29 → 29 | 7 → 6 (hypothesis) |
| services/notification-service | 18 → 18 | 7 → 4 (httpx, fakeredis, hypothesis) |
| services/dictation-service, autocomplete-service | removed | removed |
| third-party packages in `uv.lock` | `marisa-trie`, `opuslib` dropped | |
| web | unchanged | unchanged |

## Phases

| Phase | What |
|---|---|
| 0 | Inventory, baseline numbers, API oracle (8 × OpenAPI + route tables), baseline checks |
| 1 | 8 unreferenced `.md` files (457 lines) |
| 2 | 5 parallel analyses (ruff, vulture, deptry, knip, ts-prune, depcheck, jscpd, periphery) → 108-item plan |
| 3 Python | 49 files (code, R0-orphaned fixtures, eval reports, orphan corpus), 49 unused functions/constants, 15 dependency lines |
| 3 web | 7 unused exports |
| 3 macOS | 23 unused symbols |
| 3 iOS + Shared | 11 unused symbols |
| owner | dictation-service + autocomplete-service removed: no web/macOS/iOS/service caller. nlp-service kept: asr-service enriches every transcript read through it; note-service calls it for field extraction |
| 4 | 3 identical simplifications (`asr_scoring._parse_de`, `audio_io` return, one test fake) |
| 5 | Final verification, this report |

## Verification (final = baseline)

| Target | Result |
|---|---|
| Python | ruff, format, `make typecheck`, `make lint-imports` pass; 3,624 passed / 6 failed / 143 skipped. Baseline 3,888 passed: −264 = dictation (180) + autocomplete (81) suites + 3 dictation rows in `tests/contract`. The 6 failures are the baseline's |
| API | 6 remaining services: OpenAPI + route tables byte-identical to the baseline (12/12) |
| Monitoring gates | `make check-alert-rules` rc 0; `check-metric-names` OK (174 instruments) |
| web | typecheck, no-danger, build pass; vitest 668 passed + the baseline's 1 failure; build hashes unchanged (`index-CQwMYsBW.js`, `index-CAztQtXe.css`) |
| macOS | `swift build` ok; `swift test` 304 tests, 1 skipped, 0 failures |
| iOS | `scripts/check.sh`, `scripts/build-sim.sh`, `build-for-testing` succeed; `scripts/test.sh` not run (boots a simulator) |
| Invariants | 0 renames; no change under `infra/postgres`, `libs/db`, `infra/k8s`, `.github`, `.env*`, entitlements, xcconfig; Dockerfiles changed only by deleting the two removed services' own |

Pre-existing failures (unchanged): note-move check (`note_instructions`), `libs/auth` perms matrix, auth-service runbook anchor (`docs/runbooks/auth.md` missing), `tests/unit/test_check_note_move_tables.py` ×4, web `tests/evidence.test.tsx`.

## Not run

DB integration / isolation / RLS suites (they wipe the dev DB), web e2e (needs the e2e stack), iOS simulator tests, k8s render gate (chart unchanged).

## Reverted

None. One edit rewritten before it landed: `notes_assert.py:216` (Phase 4) — the identical form fails the repo lint (SIM118), so the line stayed.

## Owner actions

1. Remove dictation/autocomplete/KEDA from `infra/k8s/notes/values*.yaml`, `templates/scaling.yaml`, `scripts/k8s/staging-up.sh` (the agent's edit was refused).
2. `docker compose up -d --remove-orphans` to stop the two removed dev containers.
3. With the S1 commit: `make openapi-dump` (asr-service snapshot).
4. Commit, push, open the PR.

Everything left alone, with a recommendation each: [`CLEANUP_UNSURE.md`](CLEANUP_UNSURE.md).
