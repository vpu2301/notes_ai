# Summary Engine v2 — build sprints for Claude Code

**Status (2026-09-25): stopped at Q6 T2 — not closed.** Q1–Q5 and the Q6 reconciliation, CI job, native labels and weekly report are built on `engine-v2/Q1`; gates in `docs/eval/notes-v2-closure-2026-09.md` (synthetic set: the faithfulness gates pass; recall, coverage, recording type, hedges, attribution, blind pairwise and staging latency do not). Decisions in ADR-0060. Open: the same table on `eval/notes/v2` with r01 and the blind rounds; merge to `dev`; staging drills and load; the production read (weekly notes-quality report, four weeks).

**What this is:** five work orders that take the document engine in `services/note-service/src/note_service/domain/meeting_doc/` from the output audited on 2026-09-22 (ZEIT "Was jetzt?" episode: 3 of 24 facts, one invented sentence, four distortions, wrong recording type, a rendering bug) to a document that beats a one-prompt baseline in blind review and never contains a claim the transcript does not support.

**Repo baseline (checked 2026-09-22): branch `summaries` @ `fbba745` ("Notes summaries (very unstable now").** The engine, the worker, `note_generations` / `note_generated_items` (migration `0052`), `POST/GET /v1/notes/{id}/generation`, `GET /v1/notes/{id}/generated-items`, the eval harness `scripts/eval/notes_eval.py` and the web status line all exist there. `dev` (`1427d7b`, 2026-09-16) has none of it. Branch from `summaries`.

**Read `00-concept-summary-engine-v2.md` first.** It maps every symptom in the audit to the line of code that causes it. Three findings change the plan the audit proposed:

1. **"Der Start im November bleibt das Ziel" is not a data leak.** It is the literal example sentence in the German summary prompt (`meeting_doc/prompts.py` L299–300, `REDUCE_SUMMARY_SYSTEM["de"]`), and "November launch" is in the extraction examples (L185–208). The model copied its instructions. No cross-tenant path exists: the reduce steps never see a transcript, and a job reads only its own snapshot under the generation id as AAD (`jobs/generate_note.py` L113–115). Q1 closes this with a prompt change and a test, not an incident.
2. **The eval gate has never measured the engine.** `notes_eval.py::as_asr_result` (L169–183) emits `turns[].text`; `windows.turns_from_result` (L106–107) reads only `turns[].paragraphs`. The pipeline arm gets zero turns and returns `empty_transcript`. Every "gate" number so far is vacuous. Q1 fixes the harness before any prompt is touched.
3. **Dates are rewritten upstream, not in the engine.** nlp-service `DateNormStage` runs on every read of a meeting result (`asr-service/routers/jobs.py` L836), anchored on the server's `date.today()`, weekdays always forward. Sprint G0 specified the fix on 2026-09-20; it is not on `summaries`. Q3 lands it.

| Sprint | Outcome you can see | Audit items | Depends on |
|---|---|---|---|
| `Q1` | A number for every metric in the audit, for our engine and for the one-prompt baseline, on a gold set that includes a news-podcast regression case. The "November" sentence cannot be produced again. | P0-1, eval plan | — |
| `Q2` | Both stories of the episode are in the note. No line is written that its cited facts do not support. Excluded speech ≤ 2 % and visible. | P0-2, P0-3 | Q1 |
| `Q3` | The note says "Podcast", not "Teambesprechung"; no Decisions section on a broadcast; one fact stated once; no "HTHinweis"; "heute" stays "heute"; "am Montag … gewesen" resolves to the Monday before. | P0-4, P0-5, P0-6, rendering | Q2 |
| `Q4` | Names come out right when the workspace knows them; every opinion names who holds it; long recordings keep their numbers, dates and actors. | P1-1 … P1-5 | Q3 |
| `Q5` | Every line opens the words and the audio behind it; forecasts read as forecasts; deadlines are a block with a calendar file; corrections feed the glossary. | P2-1, P2-2, P2-3, P2-5, P2-6, P2-7 | Q4 |

Q1 is one week. The rest are two-week sprints. P1-6 (chat with the transcript) is already shipped as "Ask this note" (`domain/ask.py`, `routers/notes_ask.py`) and is not in these files. P2-4 (positions map) and P2-8 (external enrichment) are NOT NOW — see the concept.

## How to run a sprint with Claude Code

One sprint = one branch = one session. From the repo root:

```
git checkout summaries && git pull && git checkout -b engine-v2/Q1
claude
```

Paste as the first message (change the file name per sprint):

```
Read docs/sprints/summary-engine-v2/00-README-for-claude-code.md and docs/sprints/summary-engine-v2/sprint-Q1-measure-first.md.
Do section "Inspect first" before writing code. If a listed fact is false in this checkout, stop and tell me which one.
Then do the tasks in order. After each task run its "verify" command and fix failures before moving on.
Do not do anything listed under "Out of scope". Do not refactor unrelated code.
Finish with the "Report back" block. Do not commit; leave the working tree for my review.
```

Copy this folder to `docs/sprints/summary-engine-v2/` first if it is not there.

## Repo rules the agent must follow (each is a CI gate or a convention in the code today)

| Rule | Where it comes from |
|---|---|
| Full app stack: `docker compose build && docker compose up -d`. `make dev-up` is infra only. `make dev-model` starts the local chat model; on the host set `DEV_MAC_MODEL_URL=http://localhost:11434/v1`. | `docker-compose.override.yml`, `config/models.yaml` |
| Tests run per package: `uv run --project services/note-service pytest services/note-service/tests/unit/ -v` (same shape for `services/asr-service`, `libs/*`). | `Makefile` target `test` |
| Web: `cd web && npm run typecheck && npm test`. | `web/package.json` |
| Native: `ios/scripts/check.sh`, `macos/scripts/make-app.sh`. **Build only — never launch the apps.** | `macos/CLAUDE.md`, `ios/CLAUDE.md` |
| Tenant data is read and written inside `tenant_connection(state.app_pool, tenant_id)` — one transaction per block. Never `asyncpg.connect` in a service. | `make check-no-direct-asyncpg`, `libs/db/src/db/tenant.py` |
| Every new table: `ENABLE` **and** `FORCE ROW LEVEL SECURITY` + the five policies of `infra/postgres/migrations/0052_note_generation.sql` L97–130 + `GRANT … TO app_role`. | `make check-rls` |
| Migrations: `infra/postgres/migrations/00NN_name.sql` + `.down.sql`; next free number is **0057**; apply with `make migrate-up`. | folder listing |
| Environment variables are read only in a service's `config.py` (pydantic settings with `alias="MDX_…"`). | `make check-no-os-environ` |
| Object storage only through `storage.EncryptedObjectStore` (`state.transcripts_store`, `state.audio_store`, `state.clips_store`). | `make check-no-object-storage` |
| Model calls only through `libs/models` (`registry.resolve(tenant, op)` → `build_chat_provider` → `provider.complete(prompt, schema, max_tokens=…, temperature=…, system=…)`). The engine calls it through the `ChatLike` protocol in `meeting_doc/pipeline.py`. No vendor SDK imports. | `make check-no-vendor-import` |
| Errors are RFC 9457 problems with a machine `code` (`exc.problem_extras = {"code": …}`). | existing routes, `docs/api/error-codes.md` |
| Audit through `state.audit_writer.write_event(...)`; kinds in `audit_kinds.py` and `docs/audit/event-kinds.md`. | `make check-audit-insert` |
| Metrics with `metrics.get_meter(...)`, names `mdx_…_total` / `mdx_…_seconds` (`unit="s"`); alert rules and dashboards must reference declared names. | `make check-metric-names` |
| **Content never leaves the content tables.** No transcript text, quote, generated line, entity or person name in logs, audit payloads, metric labels, `jobs.payload`, `jobs.result`, `jobs.last_error`, `note_generations.stats`, or the eval JSON reports in `docs/eval/`. Log ids, counts, durations, `error_kind`. | `audit_kinds.py` comments; `_common.py` report writer; `DocumentResult.stats` docstring |
| **Prompts contain no sentence that could be mistaken for a fact about a real meeting.** Examples use the placeholder vocabulary in `prompts.EXAMPLE_PHRASES` (Q1); a test fails when any example phrase appears in an output line. | Q1 T1 |
| A new route changes `docs/api/note-service-openapi.json`: run `make openapi-dump` and include the file. | `make openapi-check` |
| `PROMPT_VERSION` in `meeting_doc/prompts.py` changes whenever any prompt text or schema changes. It is stored on `note_generations.prompt_version`, in `stats`, and in every eval report. | `prompts.py` L30, `generation_repository.py` L112–130 |
| Before "done": `make lint`, `make lint-imports`, the package tests, and — with the stack up — `make check-rls`. | `make ci`, `make ci-with-db` |

## Decisions already made (do not reopen in a sprint)

1. **Extract → verify → compose stays.** No single-prompt rewrite. The baseline arm of the harness is the single-pass architecture we must beat (ADR-0058; concept §4 of the meeting-document plan).
2. **Code decides what is true.** Every written line must be traceable to verified facts, and verification is deterministic code in `meeting_doc/verify.py`. A model judge is an *eval* instrument in Q1–Q4; it enters production only if Q4's numbers say the deterministic gate leaves > 2 % unsupported lines.
3. **The model is whatever `registry.resolve(tenant, "summarize")` returns.** No new processor, no new provider seam. A tier change is a config PR plus an eval report (Sprint 37 rules).
4. **The quote is sacred.** `note_generated_items.quote` is verbatim transcript text and is never corrected, normalised or translated. Corrections (names, dates) apply to the rendered line and are recorded as flags.
5. **Empty means empty.** No section, heading, placeholder or label is written for content the recording does not have. A broadcast has no Decisions section because the family does not offer the kind.
6. **The transcript is the transcript.** The engine, the Transcript tab, quotes and the eval all read the same text. Date resolution is an annotation, never a rewrite of the words.
7. **No external knowledge base call carries recording content.** Entity correction uses the workspace glossary, calendar attendees, ASR name candidates and the model's own knowledge under a bounded-similarity rule (Q4). Wikidata/web lookups are NOT NOW.
8. **Benchmarking against Granola's product is a counsel question, not an engineering task** (Granola Platform Terms §3.4). The blind comparison in Q1–Q5 is against the single-pass baseline and human reference summaries. If counsel clears a third-party evaluation, it is added as a second column without changing the gates.
9. **One write per section family stays** (`generate_note.py` writes items first, then the document). Nothing here changes the writer's ownership rule: text a person typed is never replaced.

## After Q5 (not in these files)

Positions map for contested topics (P2-4), external context enrichment (P2-8), a production model judge, native evidence UI on macOS/iOS beyond what Sprint 33C/35 specify, and the model bake-off (Sprint 37 B-2) that Q4's numbers may trigger.
