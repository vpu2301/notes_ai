# Isolation audit — where every word in a transcript and a note comes from (Sprint I1)

**Date:** 2026-09-25 · **Trigger:** incident memo "names from earlier notes appeared inside a new
transcript" (2026-09-25) · **Branch:** `isolation/I1` (on `engine-v2/Q1`) · **Scope:** read-only
audit plus a permanent two-workspace integration suite; no product change.

## Verdict

1. **The names came from the affected workspace's own glossary** (T1, below). The memo's root cause
   holds: the workspace glossary is the Whisper prompt of every recording, and Whisper wrote it back.
2. **No path was found by which one workspace's text, names, audio, prompts, cache entries or job
   state reaches another workspace's transcript, note, generation or search.** No finding is P0.
   The two-workspace suite (12 tests) passes, including the incident reproduced with an engine that
   echoes its prompt: workspace B's transcript carries B's glossary and none of A's.
3. What is open is **inside a workspace or inside the platform's own roles**: plaintext hints kept
   in the job queue, database roles that can read across tenants, content in logs, and two native
   paths that file one workspace's material into another of the same person. Twelve P1 findings,
   listed with owner and target sprint.

Escalation (memo, §Escalation) was **not** triggered: T1 found the terms in the workspace, and no
T3 test failed.

## T1 — the source of the names

Environment: the dev stack on the maintainer's Mac, which holds the affected workspace and the
Pardo 65 GT recording (note `fb45f4e6…`, created 2026-09-25 16:26 UTC). No production system exists
yet; these are the affected rows themselves, not a replica. Queries run as the database owner with
row security off, printing only the incident's own names.

**1. The glossary.**

```sql
SELECT term, kind, cardinality(heard_as), created_by, created_at, deleted_at IS NOT NULL
FROM workspace_glossary ORDER BY created_at;
```

7 rows, all in one workspace (`00000000-…-00a`), all `kind = person`, none deleted, all
`created_by = 0f000000-…-00f` (the author), created 2026-09-20 21:40 → 2026-09-22 20:07 UTC — the
days of the earlier podcast notes: "Moderator", "Gregor Gysi", "moderatorin", "narrator",
"speaker", "speaker background", "Moderator II". There are no other terms. `workspace_glossary`
has rows in exactly 1 of the 5 workspaces on the stack.

**2. The audit log.**

```sql
SELECT tenant_id, actor_sub, kind, created_at, payload_jcs FROM audit.events
WHERE kind LIKE 'glossary.%' ORDER BY created_at;
```

7 × `glossary.term_added`, same workspace, same actor (role `tenant_admin`), each within 20 ms of
its glossary row. Payloads carry `{kind, heard_as_count}` only — no term text, as designed.

**3. What the transcriber was told.** The job row does not store the hint (finding **F-1**:
`transcription_jobs` has no hint column, `JobEnqueuePayload.vocabulary_hint` is queue-only). The
job — `f663169c…`, same workspace, requester = the author, `language = auto`,
`detected_language = en`, finished 16:34 UTC — is linked to the note through `note_meetings`.
Reconstructed instead: `GET /v1/glossary/hint` orders terms by `(kind <> 'person'), lower(term)`,
giving `Gregor Gysi, Moderator, Moderator II, moderatorin, narrator, speaker, speaker background`.
The note's text has 4 passages of glossary words (the 2 transcript passages, each repeated once in
the note body); every one follows that order exactly (e.g. `Gysi | Moderator II | moderatorin |
narrator | speaker background`). Other workspaces' notes: 0 notes contain "Gysi" or "Moderator II".

## T2 — paths and verdicts

`isolated` = enforced in code and proven by a test; `by convention` = enforced, not tested
end-to-end; `open` = a path exists. No path is `unknown`.

| Path | Mechanism · where scoping is enforced | Proof | Verdict |
|---|---|---|---|
| Postgres tables | 59 tables; 56 with RLS + FORCE and a restrictive `app_role` tenant policy (`tenant_connection`, `libs/db/src/db/tenant.py:66-76`). Exempt: `voice_commands` (global catalogue), `autocomplete_rollup_progress` (counts), `autocomplete_telemetry` (ADR-0025 perf exception, **F-8**) | `make check-rls` (55 tables PASS); `libs/db/tests/integration/test_rls_isolation*.py` — `_ENTITY_TABLES` covers audio, jobs, dictation, templates, notes, share links, action items, responses; **not** the 0049–0060 tables (**F-11**) | isolated for the listed tables; by convention for 0049–0060; open for `autocomplete_telemetry` to `app_role` |
| SECURITY DEFINER functions | 24 functions, all with a pinned `search_path`; most return tenant ids or scalars to `app_role` | only `profile_of_subs` has an ACL test | by convention; **`jobs_claim_fair` open to every role (F-6)** |
| `tenant_connection` misuse | 243 call sites: `claims.tid` (142), membership-checked path ids (auth tenants routes), HMAC/hashed tokens (shared pages, unsubscribe, calendar OAuth state), job rows written from `claims.tid`, enumerator functions. None takes a tenant id from a body/path/query without an authorization check | unit tests with fakes (`test_tenants.py`, `test_session_native.py`); suite test 4 | isolated |
| Background jobs | `jobs_claim`/`jobs_claim_fair` lease rows; handlers run under `tenant_connection(job.tenant_id)`; snapshot AAD = generation id | `libs/jobs/tests/integration/test_queue_db.py::test_tenant_isolation_jobs_and_usage` | isolated (claim ACL: F-6) |
| Cross-tenant jobs and reports | sweepers via `active_tenant_ids()`; retention on `tenant_writer`; weekly reports on `funnel_reader`, aggregate counts | report SQL tests (`test_weekly_*`) | by convention; `funnel_reader` reads content (**F-7**); `share_retention` silently does nothing (**F-14**) |
| ASR queue and worker | payload `tenant_id`/`requester_sub` from the JWT (`asr-service/routers/jobs.py:341-354`); worker scopes by `payload.tenant_id`; audio key `{tid}/{audio}.enc`, result `{tid}/{job}.json.enc`; no temp dir (ffmpeg pipes); engine holds only the model; `initial_prompt` is a per-call argument | suite tests 2, 3 and the per-call prompt unit test | isolated; plaintext hint retained in the stream (**F-1**) |
| Object storage | `EncryptedObjectStore`: tenant KEK, AAD = tenant id ‖ object id, tenant check before decrypt; every key tenant-first except `dictations/{tid}/…` (**F-20**) and the global autocomplete archive | `test_object_store.py::test_wrong_tenant_rejected_before_crypto`, `test_envelope.py::test_cross_tenant_blob_swap_fails_at_gcm`; suite test 8 | isolated |
| Redis | tenant data under `workspace:{tid}:…` or with the tenant id in the key body (`autocomplete:trie:{tid}…`, `ai:budget:{tid}…`); unprefixed keys are streams, ids, per-user rate limits | suite test 7 scans every key against an allow-list with a reason per pattern | isolated |
| nlp-service cache | `mdx:nlp:cache:{sha256}`, hash over tenant id + language + reference date + text + … (`pipeline/orchestrator.py:208-265`), TTL 1 h | none asserts the tenant input (**F-3**) | isolated by construction; F-3 is benign across tenants |
| Model providers | one provider per backend, stateless per call (`openai_compat.py:112-222`); no per-tenant keys; workspace settings cache keyed by tenant | `test_openai_compat.py::test_error_message_never_echoes_prompt` (connect errors only) | by convention; llama.cpp `cache_prompt` is a timing channel only (**F-29**) |
| Prompts | engine reads everything under the job's tenant; glossary and known people are used by code, never put in a prompt; title and Ask read only their own note | `test_meeting_doc_q4.py::test_the_glossary_is_read_inside_the_generations_own_tenant`; `test_series_and_carry_over.py::test_a_colleagues_private_note_is_never_carried_from` | isolated |
| Glossary and hint | every route in `tenant_connection(claims.tid)`; unique per `(tenant_id, lower(term))`; workspace-wide by design (**F-2**) | suite tests 1–3 | isolated across workspaces; F-2 within one |
| Search | RLS on `notes`/`note_versions`, no results cache | `test_synonyms_rls_isolation`; suite test 5 | isolated; `total_estimated` is platform-wide (**F-17**) |
| Sharing, recipient links, client view | token hash → one `(tenant, note, link)` via `resolve_note_share_link`; everything after runs in that tenant | `test_shared_public.py` (unknown/revoked/cancelled → 404), `test_recipient_links.py`; suite test 4 covers 44 note-service and 11 asr-service id routes | isolated |
| Eval and reports | rows are ids, counts, ratios and indices; note text only under gitignored `scripts/eval/local/` | suite test 10 | isolated |
| Logs and audit | `pii_filter` drops/masks by key name; audit payloads carry kinds and counts | `test_pii_filter.py`; suite test 9 (no term or transcript in any record during both flows) | by convention: exception text and access logs bypass the filter (**F-9**, **F-10**) |
| Native local caches | recents/templates/notes scoped by `identity.tenant`; a new recording re-fetches the hint | `WorkspaceTests.swift` (recents) | isolated for new recordings; **open** for a recording spanning a switch (**F-4**) and for offline notes (**F-5**) |

## T3 — two-workspace suite

`tests/integration/test_two_tenant_isolation.py`, `make test-isolation` (part of
`make ci-with-db`). Services run in process (auth, note, asr) and the asr-worker's own
`_process_one`, against the dev stack's Postgres, Redis and MinIO, on a private queue stream so the
running worker container never races it. Workspaces are real signups.

| Test | Result |
|---|---|
| B's `GET /v1/glossary/hint` has none of A's terms | pass |
| B's queued job payload: `tenant_id = B`, `vocabulary_hint` = B's hint, none of A's terms | pass |
| The worker with an **echoing engine** on B's job: the engine was given exactly B's hint; B's transcript contains B's term and none of A's | pass |
| One engine instance, two calls: each decoder call gets only its own `initial_prompt` (unit, mocked model) | pass |
| B on every note/job-id route of the committed OpenAPI dumps (44 + 11, required query filled): every GET 403/404, no other method 2xx, no A term in any body; A's versions, glossary and links unchanged; A opens the same ids | pass |
| B searches A's term: no hit (A finds its own note) | pass |
| A suspended: B's hint, search and 404s unchanged | pass |
| Every Redis key: `workspace:<tid>:` or an allow-listed pattern with its reason | pass |
| Every object written during both flows: key starts with (or names) its tenant | pass |
| Every log record during both flows: no term, no transcript text | pass |
| An eval report from B's meeting (scripted engine): no term text | pass |

Not in the suite: a user deleted (no deletion route exists yet; `purge_impl` suspends memberships),
the speaker-rename "Remember this?" flow (it is `POST /v1/glossary`, which the suite calls
directly).

## T4 — findings

Severity per the sprint: P0 = cross-tenant path open to a workspace user; P1 = convention without a
test, a content leak into logs/reports, or a cross-workspace path of the platform's own roles or of
one person's devices; P2 = hygiene. "Verified" = checked on the running dev stack; otherwise read in
code at the lines given.

### P1

| # | Finding | Owner | Target |
|---|---|---|---|
| F-1 | The ASR hint is not on the job row, so nothing records what the transcriber was told; and the plaintext hint (and `local_speaker_name`) stays in the shared `asr:jobs`/`asr:jobs:dlq` streams after ack — no `XDEL`, no tenant prefix, trimmed only at ~100k entries, untouched by erasure (`libs/messaging/.../redis_streams.py:65-95, 270-300`). Verified: no hint column. | asr | I2 (store the hint on the row; `XDEL` on ack) |
| F-2 | The glossary is workspace-wide by design: one member's "Remember" changes every member's transcriptions; any `note.write` member can merge a mishearing into another's term, without an audit event (`routers/glossary.py:131-135`). | note-service, native | I2 (visibility, audit on merge) |
| F-4 | macOS: a recording started in workspace A and stopped after switching to B (or signing out and in) uploads to B with A's hint, calendar context and audio, and creates its note in B (`CaptureViewModel.swift:232, 335-342, 386-392`; no recording guard in `AppState.switchWorkspace`, L1088). iOS pins the upload to the start workspace. A new recording always re-fetches the hint. | macos | I2 (pin tenant at start, as iOS) |
| F-5 | macOS and iOS: meeting notes typed offline are replayed into the **active** workspace, ignoring the stored `tenantId` (macOS `CaptureViewModel.swift:618-655`, iOS `587-623`; on macOS on every switch via `loadWorkspaceData`). | macos, ios | I2 |
| F-6 | `jobs_claim_fair` (0055) was never `REVOKE`d from PUBLIC: every database role (`funnel_reader`, `audit_reader`, `crypto_writer`, `tenant_writer`) can lease every workspace's jobs and receive the rows. `jobs_claim` (0022) is revoked correctly. **Verified** (`has_function_privilege`). | db | I2, first task (one-line migration) |
| F-7 | `funnel_reader` (the Grafana datasource, default password in `values.yaml`) has table-level SELECT with `USING (true)` on `notes` (titles, cancel reasons), `share_link_responses.comment`, `referrals.lead_email`, `note_share_links.recipient_email`, `tenants` (0040:18-24). 0046 and 0060 are column-level; 0040 is not, so 0060's header ("cannot read a note's text, a quote or a name") overstates the role's restriction. **Verified** for `notes.title` and `comment`. | db, ops | I2 (column-level 0040, rotate password) |
| F-8 | `autocomplete_telemetry` has no RLS and `app_role` can read it (0010:278, 306), exempted from the CI gate by name. **Verified.** | autocomplete | backlog (ADR-0025 revisit) |
| F-9 | Model output reaches logs through exception text: Pydantic `ValidationError` carries `input_value` (fact text/quotes) and is logged with `exc_info` (`pipeline.py:666-671, 699, 753, 871, 436`, `classify.py:88`, `note_title.py:227`, `generate_note.py:828`); the asr-worker logs `str(ValidationError)` of the queue payload with the hint (`processor.py:209, 218, 348`). `pii_filter` does not scrub tracebacks. | observability | I2 |
| F-10 | uvicorn access logs (on in every Dockerfile, `propagate=False`, outside the PII filter) record full URLs: search `?q=`, clip `?t=` tokens, OAuth `?code=`. | ops | I2 |
| F-11 | No DB-level isolation test for the tables of 0049–0060 (`note_meetings`, `note_user_line_times`, `note_item_corrections`, `workspace_glossary`, `note_carried_items`, `note_generations`, `note_generated_items`, `workspace_model_settings`), notifications, calendar connections, spaces. Policies are correct on reading. | db | I2 (extend `_ENTITY_TABLES`) |
| F-3 | nlp cache: the tenant is inside the hashed key (benign across workspaces), but the value is the enriched transcript in plaintext for 1 h and cannot be purged per workspace; no test asserts the tenant input to the key. | nlp | I2 (test) · backlog (retention) |
| F-12 | Suspending a workspace is enforced only when a token is minted: tokens already issued keep working until they expire — no resource service reads `tenants.status` (code: the only checks are in auth-service `session_service.py:483`, `routers/tenants.py:422`). The suite's suspension test covers B, not A's live token. | auth | backlog |

### P2

| # | Finding | Owner |
|---|---|---|
| F-13 | `check-rls-policies.py` checks only `relkind='r'`: not views (0053's owner-rights view bypassed RLS until 0054), predicates, `USING (true)` grants or definer-function ACLs. | db |
| F-14 | `share_retention.py` and `chain_reconciler` read `tenants` as `app_role` without a tenant scope → 0 rows: recipient e-mails and OTPs are never purged. | ops |
| F-15 | `nightly_verify` runs as the postgres superuser (`nightly_verify.py:60-63`, `values.yaml`). | ops |
| F-16 | Notification WebSocket fan-out is keyed by user, not by the socket's workspace: one person signed into A receives B's notifications (same person). | notification |
| F-17 | Search `total_estimated` is `pg_class.reltuples` — the platform-wide note count (`search.py:228`). | note-service |
| F-18 | Audio-clip streaming checks the workspace, not the user or the note's visibility (`routers/audio_clips.py:211-236`) — intra-workspace. | note-service |
| F-19 | `workspace:{tid}:asr:suggestion_offered:…:{name}` puts a person's name in a key for 30 days; `job_erasure` has no production caller and would not remove it, the stream entries or nlp cache entries. | asr |
| F-20 | Dictation audio key is `dictations/{tid}/…`, not tenant-first. | dictation |
| F-21 | Audit payloads carry the raw search query (`notes_search.py:210`) and free-text cancel reasons (workspace-scoped). | note-service |
| F-22 | iOS post-upload steps (poll, attach, create note) use the active token, not the bound tenant. | ios |
| F-23 | Web `localStorage` capture titles/links and tab `sessionStorage` invitee names are not scoped or cleared on logout. | web |
| F-24 | MCP connector Keychain items are device-global. | macos |
| F-25 | `note_share_links.note_id`, `note_carried_items.from_note_id`, `note_meetings.previous_note_id` reference `notes(id)` without the tenant; `resolve_note_share_link` does not check `l.tenant_id = n.tenant_id` (harmless today: links are created under RLS). | db |
| F-26 | `app_role` has `CREATE` on schema `public`. | db |
| F-27 | Calendar OAuth state nonce is not single-use (replayable within its TTL). | note-service |
| F-28 | ASR validator writes the plaintext upload to the system temp dir with `delete=False` (unlinked in `finally`; a crash leaves it). | asr |
| F-29 | llama.cpp `cache_prompt` and hosted prefix caches are a cross-workspace timing channel (no content). | models |
| F-30 | `vocabulary_hint` has no token cap or special-token strip on the batch path (`jobs.py:180` → `inference.py:410`). | asr (I2 hint work) |

Observed, outside isolation (for the owners): model routing ignores `effective()` acknowledgement
(`ai_settings.py:286`); shadow-run cost is billed to the workspace; Ask never refreshes workspace
settings in the API process.

## Method

Code read by path (four parallel read-only passes, then spot-verified), queries on the dev stack,
and the suite. Line numbers are from `isolation/I1` at the time of writing.
