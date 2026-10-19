# Sprint N0 — Model behaviour and writing style, set by hand (note-service + web + native read-only)

**Duration:** 1½ weeks · **Team:** 1 backend, ½ web, ¼ Swift
**Depends on:** nothing new. Reuses `workspace_model_settings` (migration `0053`), `routers/ai_settings.py` (`GET/PUT /v1/ai/settings`), `domain/ai_settings.py::WorkspaceSettings` (the cached settings source the worker refreshes before a run), `meeting_doc/pipeline.py::run` / `sizes_for`, `web/src/pages/settings/DataSettingsPage.tsx` view `writing`.
**Unblocks:** N1 (the compiled profile's `style` overrides the picker), N2 (the engine reads `ModelParams` and `style` through the same `Styling` object), N3 (the card layout).
**Concept:** `00-concept-note-instructions.md` §2a (style), §2b (model parameters).
**Priority:** P1 for the style picker (every workspace will touch it); P2 for the advanced parameters (admins who know what they are doing; off by default behind a disclosure).

## Sprint outcome

> In **Settings → Data & AI → Note writing** an admin picks the **writing style** of generated notes — **Business** (today's executive record), **Formal**, **Informal**, **Academic** — and, under **Advanced: model behaviour**, sets by hand the parameters the engine actually reads: the writer's temperature, the context window it may use, the output budget per call, parallel calls, the fact budget per window, the retry policy, and the temperature and answer length of "Ask this note". Every parameter shows its recommended value, its allowed range, what the model's configuration caps it at, and one sentence on what it does to the notes. **Reset to recommended** puts everything back. Every generation records which parameter set wrote it.

**Demo:** admin opens Note writing → Style → picks **Academic** → regenerates a lecture recording: hedged claims, "the speaker argues", no contractions, figure tables kept, longer headings. Switches to **Informal** on a team meeting: short headings, plain words, contractions, no figure tables. Opens **Advanced** → sets temperature 0.4 → the card says "Freer wording. Lines the verifier cannot support are dropped, so notes may get shorter; measured drop at 0.4 on the gold set: n %" (the number comes from N5; until then "not yet measured") → regenerate → status line "written with model settings v2". Sets context window to 65 536 on a backend configured with 32 768 → the field shows "capped at 32 768 by the model's configuration" and saves 32 768. **Reset** → v3, all defaults.

---

## Inspect first (stop and report if any is false on your branch)

1. `meeting_doc/pipeline.py`: every `provider.complete(...)` passes `temperature=0.0` literally — compose/detail sites `_model_names` L1091, `_figure_details` L1483, `_contact_details` L1537, `_person_details` L1591, `_context` L1626, `_block_capable` L1804, `_small_call` L1848, `_merge_headings` L2077, `_summary` L2236; and the extraction site `_extract` L1392, which stays at 0.0; `run()` takes `max_concurrency: int = 4` (L171) and `retry_budget_s` (L182); `sizes = sizes_for(provider)` at L194 and `sizes_for(provider, context_window=None)` (L1027–1039) derives `window_chars`, `extract_max_tokens`, `reduce_max_tokens`, `max_facts_budget` from the backend's `context_window`; `MAX_FACTS_BUDGET = 24` (L1205).
2. `libs/models/src/models/openai_compat.py::complete(prompt, schema, *, max_tokens, temperature=0.0, system)` sends `max_tokens` and `temperature` in the body (L201–202) and then `body.update(self.request_overrides)` (L216) — overrides are **per provider instance**, not per call. `max_concurrency` is a per-instance semaphore (L71).
3. `config/models.yaml` backends declare `context_window`, `max_concurrency`, `timeout_seconds`, `small_model`, `request_overrides` (e.g. `reasoning_effort`); `libs/models/src/models/registry.py::ResolvedBackend` carries `context_window`, `max_concurrency`, `timeout_seconds` (L81–84).
4. `domain/ai_settings.py::SettingsRow` has `provider, tier, generation_enabled, acknowledged, monthly_budget_cents`; `WorkspaceSettings.refresh(tenant_id)` reads the row before a generation and caches it 60 s; `worker.py::_Providers.warm` calls it (L91–94).
5. `jobs/generate_note.py::handle_generate` calls `pipeline.run(...)` at L159 without `max_concurrency` (default 4) and with `retry_budget_s=_retry_budget(deps, built)` (from `settings.note_coverage_retry_budget_s_per_hour`, `config.py` L220).
6. `domain/ask.py::AskService.answer` calls `provider.complete(prompt, None, max_tokens=self._max_tokens, temperature=0.2, system=SYSTEM_PROMPT)` (L157–159); `config.py` has `ask_max_tokens` (`MDX_ASK_MAX_TOKENS`, 700, L147).
7. `meeting_doc/prompts.py::REDUCE_SUMMARY_SYSTEM` / `BLOCK_SYSTEM` / `REDUCE_CONTEXT_SYSTEM` carry the register today in their own words ("in the style of an executive meeting record", "Third person or impersonal", "no adjectives that are not in the facts"); there is no style variable.
8. `routers/notes_generation.py::GenerationView` has `prompt_version`, `model_id`, `language`; `note_generations.stats` is a JSONB the worker writes.
9. `web/src/pages/settings/DataSettingsPage.tsx` view `writing` (L149–210) has the tier `Segmented` and the "Automatic note writing" checkbox; `settings.can_edit` gates edits; `putAiSettings` sends partial bodies.

---

## Scope

1. `writing_style` and `model_params` on `workspace_model_settings` (migration `0079` — N1's table then takes `0080`, N4's `0081`; renumber in those files when you get there).
2. `ModelParams` (closed, bounded) and `STYLES` (closed) in `domain/model_params.py` + `meeting_doc/styling.py` (`Styling` is introduced here; N2 extends it with the compiled profile).
3. Threading: `pipeline.run(..., params=ModelParams, style=…)`; `sizes_for(context_window=…)`; temperature on **compose and detail calls only**; `max_concurrency`; facts budget; retry policy; Ask's temperature and max tokens.
4. Style lines in the compose prompts (`prompts.style_lines(style, language)`), `PROMPT_VERSION` bump.
5. `GET/PUT /v1/ai/settings` extended; `GET /v1/ai/settings` returns `model_params_effective` (after caps) and `model_params_limits` (the ranges and the backend caps).
6. `note_generations.stats.model_params = {version, hash}`; `GenerationView.model_settings_version`.
7. No UI in this sprint: the page is N3 (`sprint-N3-note-writing-settings-page.md`). N0 ships the API shapes N3 renders (`writing_style`, `model_params`, `model_params_limits`, `model_params_effective`, `model_params_measured`, `model_params_version`, `reset_model_params`) and the eval arm.
8. Tests, audit, metrics, OpenAPI, docs.

## Explicit non-scope

- Per-backend `request_overrides` such as `reasoning_effort` (per provider instance in `openai_compat.py`, not per call; changing it is a config PR — the card says "set by the deployment"). NOT NOW: a per-call override seam in `libs/models`.
- Temperature for **extraction** (`_extract`, `reread`, `regenerate` hooks) and for classification, title, entity correction — locked at 0.0. Facts are precision work; the gate cannot repair a hallucinated quote.
- Choosing a model id or backend by hand (the tier picker and `config/models.yaml` own that — Sprint 37).
- Top-p, presence/frequency penalties, stop sequences, seeds (not every backend supports them; nothing in the engine reads them; adding them would be a settings page for nobody).
- Per-note or per-type parameters (parameters are a workspace matter; style per type comes with N4's instructions).
- Free-text instructions (N1–N5).

---

## Design decisions

**Only parameters the engine reads today, each bounded, each with a cap from the backend.** A parameter that nothing consumes is not offered. The ranges are the engine's own sanity limits; the backend's `context_window` and `max_concurrency` from `ResolvedBackend` cap the saved value (`effective = min(requested, cap)`) and the card shows both. **Rejected:** a free-form JSON "model options" field (unbounded, unmeasurable, and a prompt-injection surface through `request_overrides`).

**Temperature is split by step.** `ModelParams.temperature` applies to the compose and detail calls (`_context`, `_block_capable`, `_small_call`, `_merge_headings`, `_summary`, `_figure_details`, `_contact_details`, `_person_details`, `_model_names`); `extraction_temperature` is a constant `0.0` and not a field. The card explains the consequence once: the verifier drops what it cannot support, so a higher temperature can shorten notes. N5 measures the drop at 0.2 / 0.4 / 0.7 and the card shows the measured number.

**Style is a closed enum, not a prompt the admin writes.** `STYLES = {business, formal, informal, academic}`; each is a fixed set of lines per language appended to the compose prompts (same mechanism N2 uses for the compiled profile, introduced here as `prompts.style_lines`), plus a few code defaults (see table). `business` is today's behaviour and produces **no** added lines (so `PROMPT_VERSION` changes once, for the scaffolding, and the default output stays byte-identical — acceptance 1). Third person, facts-only, the gate: unchanged for every style. **Rejected:** `register` as a free string; styles that imply first person ("conversational"); a "custom" style (that is N1's instructions).

**Stored on the row the worker already refreshes.** Two columns on `workspace_model_settings`; `SettingsRow` gains `writing_style` and `model_params`; `WorkspaceSettings.refresh` already runs before each generation and the worker reads the row through `deps` — no second table, no second cache. The `PUT` route invalidates the cache as it does today.

**Every generation records what wrote it.** `stats.model_params = {"version": n, "hash": sha256(canonical params + style)}` and `GenerationView.model_settings_version`. The eval harness takes `--model-params file.json` (N0 T7) so a parameter set can be measured before an admin is told what it does.

---

## Data model — migration `0079_workspace_model_params.sql` (+ down)

```sql
ALTER TABLE workspace_model_settings
    ADD COLUMN writing_style TEXT NOT NULL DEFAULT 'business'
        CHECK (writing_style IN ('business','formal','informal','academic')),
    ADD COLUMN model_params JSONB NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(model_params) = 'object'),
    ADD COLUMN model_params_version INTEGER NOT NULL DEFAULT 0 CHECK (model_params_version >= 0);
```
No backfill (defaults = today's behaviour). RLS unchanged (same table). Down: drop the three columns. A workspace without a row keeps `SettingsRow` defaults (`business`, `{}`, `0`).

## `ModelParams` (`domain/model_params.py`)

| field | type / range | default | cap | what it does (card copy) |
|---|---|---|---|---|
| `temperature` | float 0.0–0.7 step 0.1 | 0.0 | — | "How freely the writer words a line. 0 = the same wording every time. Higher: more varied phrasing; lines the verifier cannot support are dropped, so notes may get shorter." |
| `context_window_tokens` | int 8 192–262 144 | backend's | backend `context_window` | "How much of the recording the writer reads at once. Larger: fewer passes, better cross-references, more memory and cost per call." |
| `max_output_tokens` | int 512–4 096 | `sizes_for(...).reduce_max_tokens` | — | "The longest answer one writing call may give. Too small cuts sections short; larger costs more." |
| `max_concurrency` | int 1–8 | 4 | backend `max_concurrency` | "Parallel calls per note. Faster notes, more load on the model." |
| `facts_per_window` | int 8–24 | 24 | — | "How many facts the reader may take from one pass. Fewer: sharper notes on noisy recordings; more: longer notes." |
| `retries` | `off` · `standard` · `thorough` | `standard` | — | "Whether a thin part of the recording is read a second time. Thorough: better coverage, slower." (`off` → `retry_budget_s=0`; `thorough` → 2× `note_coverage_retry_budget_s_per_hour`) |
| `ask_temperature` | float 0.0–1.0 step 0.1 | 0.2 | — | "How freely 'Ask this note' answers." |
| `ask_max_tokens` | int 200–2 000 | 700 | — | "The longest answer 'Ask this note' may give." |

`ModelParams.model_validate(row.model_params)` with `extra="forbid"`; an invalid stored object → defaults + `model_params.invalid` log (no values). `effective(params, backend: ResolvedBackend) -> ModelParams` applies caps. `canonical_hash(params, style)`.

## Styles (`meeting_doc/styling.py` + `prompts.STYLE_LINES[style][lang]`)

| style | prompt lines (en; de/uk equivalents, reviewed in N5) | code defaults |
|---|---|---|
| `business` | none (today's prompts already say "executive meeting record") | today's |
| `formal` | "Formal register: full forms, no contractions, no colloquial words; titles and surnames as the facts give them; one claim per sentence." | `heading_style=descriptive`, `figure_tables=on` |
| `informal` | "Plain, direct wording as a colleague would write it; contractions are fine; short sentences; no jargon unless the facts use it." | `heading_style=short`, `figure_tables=off`, `quote_children=on` |
| `academic` | "Precise, hedged wording: keep every qualifier the facts carry ('estimated', 'argued', 'suggested'); name who holds each position; prefer 'the speaker argues' over bare assertion; keep figures with their units." | `heading_style=descriptive`, `figure_tables=on`, `quote_children=on`, `summary_sentences` upper bound 6 |

The lines go where N2 puts the style block (compose prompts only), wrapped in the same `⟦ ⟧` preamble ("Author's preferences for the FORM of this note"). Third person and the gate are not mentioned because nothing changes there.

---

## API contract (extend `routers/ai_settings.py`)

### `GET /v1/ai/settings` — unchanged auth; body gains
```json
{"writing_style":"business",
 "model_params":{…requested…},
 "model_params_effective":{…after caps…},
 "model_params_version":2,
 "model_params_limits":{
   "temperature":{"min":0.0,"max":0.7,"step":0.1,"default":0.0},
   "context_window_tokens":{"min":8192,"max":262144,"default":32768,"cap":32768,"cap_source":"backend"},
   "max_concurrency":{"min":1,"max":8,"default":4,"cap":2,"cap_source":"backend"},
   …},
 "model_params_measured":{"temperature":{"0.2":null,"0.4":null,"0.7":null}}}
```
`model_params_measured` is read from `docs/eval/model-params-<version>.json` when present (N5 writes it); `null` until then. `cap` comes from the backend the workspace's `effective_tier` resolves to (`_registry().resolve(tid, "summarize")`).

### `PUT /v1/ai/settings` — same admin rule; `UpdateSettingsRequest` gains
`writing_style?: Literal[...]`, `model_params?: ModelParams` (whole object, validated; partial objects rejected with `400 validation_error` — the client always sends the full set), `reset_model_params?: bool`. Any change to either bumps `model_params_version` and audits `ai.settings_changed` with `{"writing_style", "model_params_changed": [field names], "model_params_version"}` (names, never values? — values are not content; **include** `temperature` and `context_window_tokens` values in the payload, they are operational settings an auditor should see). Cache invalidated as today.

Ask (`routers/notes_ask.py` → `AskService.answer`) reads `ask_temperature` / `ask_max_tokens` from the cached row through a small `params_for(tenant)` on `WorkspaceSettings` (sync, cached like `cached()`).

---

## Tasks (in order; each ends with its verify)

**T1 — Migration + row.** `0079`; `SettingsRow.writing_style`, `.model_params`, `.model_params_version`; `fetch`/`upsert` carry them; `WorkspaceSettings` keeps the row (it already does: `_rows`) and exposes `params_for(workspace_id) -> (ModelParams, style)` from the cache.
*verify:* `make migrate-up && make migrate-down && make migrate-up && make check-rls && uv run --project services/note-service pytest services/note-service/tests/unit/test_ai_settings.py -v`.

**T2 — `ModelParams` and caps.** `domain/model_params.py` + `tests/unit/test_model_params.py`: bounds, `extra="forbid"`, `effective()` caps by backend, hash stability, invalid stored object → defaults.
*verify:* the test file.

**T3 — Engine threading.** `meeting_doc/styling.py::Styling` (fields: `temperature`, `sizes: Sizes`, `max_concurrency`, `facts_cap`, `retry_budget_s`, `style`, `style_lines`, plus the N2 fields with defaults); `run(..., styling: Styling | None)`; replace the nine literal `temperature=0.0` compose/detail sites (not `_extract` L1392) with `styling.temperature`; `sizes_for(provider, context_window=styling.context_window)`; `fact_budget(window, max_budget=styling.facts_cap)`; `max_concurrency=styling.max_concurrency`; `prompts.style_lines(style, language)` appended at N2's five sites via `prompts.with_style` (introduce the helper here; N2 adds the profile lines to the same block); `PROMPT_VERSION` → `"2026-10-19.1"`, pin.
*verify:* `uv run --project services/note-service pytest services/note-service/tests/unit/test_meeting_doc_engine.py services/note-service/tests/unit/test_meeting_doc_prompts.py -v` + new `test_meeting_doc_styling.py`: `Styling.DEFAULT` run == plain run (identical sections/stats); `temperature=0.4` reaches every compose call and **no** extract call (scripted provider records kwargs); `context_window_tokens=16384` → `window_chars == 6000`, `65536` → `8000`; `facts_per_window=8` → extract budget ≤ 8; `style=informal` → `heading_style short`, no figure tables, style lines present in block/summary prompts and absent from extract.

**T4 — Worker + Ask.** `handle_generate`: `params, style = deps.params_for(tenant_id)` after `provider` is resolved; `effective(params, backend_of(provider))`; `Styling.from_params(...)`; `stats["model_params"] = {"version", "hash"}`; `GenerationView.model_settings_version`. `AskService.answer(..., temperature=, max_tokens=)` from the row.
*verify:* `uv run --project services/note-service pytest services/note-service/tests/unit/ -q -k "generate_note or ask"` + new cases: stats carry version+hash; Ask passes the row's values; a workspace without a row behaves as today.

**T5 — Routes.** `GET`/`PUT` extensions, `limits`, `measured` file reader (missing file → nulls), reset, audit payload, `docs/api/error-codes.md` (none new), `make openapi-dump`.
*verify:* `tests/unit/test_ai_settings.py` new cases: member GET sees params and limits; member PUT 403; admin PUT partial `model_params` → 400; admin PUT with `context_window_tokens` above the cap → saved capped, `effective` shows the cap, response says `cap_source: backend`; reset → version bumps, defaults; style change alone bumps version; audit payload has the listed keys only; tenant B unaffected (isolation as the existing tests).

**T6 — Web types only.** `web/src/api/types.ts`: `AiSettings` gains the N0 fields, `AiSettingsUpdate` gains `writing_style`, `model_params`, `reset_model_params`; `GenerationView.model_settings_version`, `GenerationView.writing_style`. No page work (N3).
*verify:* `cd web && npm run typecheck`.

**T7 — Eval arm.** `notes_eval.py --model-params file.json --style academic` → `Styling` built as the worker builds it; report `model_params: {hash, file, style}`; Makefile `MODEL_PARAMS=` `STYLE=`. One run per style on `eval/notes/v2` with `dev_mac`; commit the reports (numbers only).
*verify:* `make eval-notes BACKEND=dev_mac STYLE=academic` produces a report; `make check-routing-report` (new `PROMPT_VERSION` → reports or waivers).

**T8 — Native models only.** `AISettings` gains `writingStyle`, `modelParamsVersion`, `modelParamsEffective` (typed struct); `GenerationView.modelSettingsVersion`, `.writingStyle`; decoding tests. The screen is N3.
*verify:* `ios/scripts/check.sh && macos/scripts/make-app.sh`.

---

## Security review

- **Cost and load abuse:** every integer is bounded and capped by the backend's own limits (`max_concurrency` cannot exceed the semaphore the backend declares; `context_window_tokens` cannot exceed what the backend can take, so no `prompt is too long` loop); `max_output_tokens ≤ 4 096`; the monthly budget gate is untouched and still stops a workspace that spends more because of larger windows.
- **Privilege:** admin-only writes, as the tier. Members read (they should see how their notes are written).
- **No injection surface:** no free strings in `ModelParams`; `writing_style` is an enum; `request_overrides` are not reachable.
- **Audit:** values of operational parameters are in the payload on purpose; nothing in them is content.
- **Tenant:** same row, same RLS, same cache keyed by tenant.

## Failure scenarios

| Failure | Behaviour |
|---|---|
| Stored `model_params` invalid (older/newer schema) | defaults; log `model_params.invalid {tenant, version}`; the card shows "Reset needed" |
| Backend changes (tier switch) and the cap drops below a saved value | `effective` caps at run time; the card shows the cap; nothing is rewritten silently |
| Temperature 0.7 makes the summary fail its gate share | today's ladder (strict rung → composed sentences) runs unchanged; `stats.summary_ladder` says so; N5 reports the rate |
| `measured` file missing | nulls; the sentence says not yet measured |

## Observability

`generations{instructed, style}` label gains `style`; `stats.model_params.version/hash`; `note_generate.done` logs `temperature`, `context_window`, `max_concurrency` (numbers). Grafana row in N5.

## Acceptance criteria (binary)

1. A workspace with no row, and a workspace with `business` + default params, produce byte-identical sections and stats to `dev @ 6834d68` on every fixture with the scripted provider (golden test).
2. `temperature` from the row reaches every compose/detail `complete()` call and none of the extract/classify/title/entity calls (recorded kwargs, asserted per call site).
3. `context_window_tokens` above the backend cap is saved capped and reported with `cap_source: "backend"`; the run's `window_chars` follows the capped value.
4. Each of `formal`, `informal`, `academic` adds its lines to the block, summary and context prompts only, and the gold-set report per style exists under `docs/eval/` at `PROMPT_VERSION 2026-10-19.1` with `citation_precision` and `judge_unsupported_rate` within 1 point of `business`.
5. `GenerationView.model_settings_version` equals the row's version at the time of the run; a reset bumps the version.
6. `GenerationView` exposes `model_settings_version` and `writing_style`; web typecheck and both native builds pass with the decoding tests (the page itself is N3's acceptance).
7. `make lint`, `make lint-imports`, `make check-rls`, `make check-metric-names`, `make openapi-check`, `make check-routing-report` pass.

## Report back

State: the per-style numbers against `business` on `dev_mac`; the summary-fallback rate at temperature 0.0 / 0.4 / 0.7 on the gold set (one run each — N5 does the full grid); the `PROMPT_VERSION` pinned; any "Inspect first" fact that differed; debt found (candidates: the literal `temperature=0.0` at ten sites, the per-instance `request_overrides`).
