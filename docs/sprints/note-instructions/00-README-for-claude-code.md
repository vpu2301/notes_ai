# Note instructions — build sprints for Claude Code

**What this is:** six work orders that give **Settings → Data & AI → Note writing** three controls over how notes are written: (1) the **writing style** — Business, Formal, Informal, Academic; (2) **Advanced: model behaviour** — the model parameters the engine actually reads (temperature, context window, output budget, parallel calls, fact budget, retries, and the same for "Ask this note"), set by hand within bounds; (3) **Note instructions** — an admin pastes plain-text instructions ("write for the CEO, five sentences, German business terms, no open-questions section, always foreground prices and deadlines") and from then on every generated note in the workspace follows them. The text is read like a skill file: the product tells the admin what it understood and what it will not do, and the engine applies it **to form only** — wording, emphasis, length, order, which optional sections appear — never to what is true. Later sprints add an override per meeting type and per note.

**Repo baseline (checked 2026-10-18): branch `dev` @ `6834d68` ("Merge pull request #10 from vpu2301/workspace-fixes").** None of this exists. What does exist and is reused: the Data & AI settings page (`web/src/pages/settings/DataSettingsPage.tsx`, view `writing`), its table and route (`workspace_model_settings`, migration `0053`; `routers/ai_settings.py`, `domain/ai_settings.py`), the permission pair `ai_settings.read` / `ai_settings.write` (`libs/auth/src/auth/perms.py` L48–50), the document engine (`services/note-service/src/note_service/domain/meeting_doc/`), the worker (`jobs/generate_note.py`), the linter (`meeting_doc/doclint.py`), the eval harness (`scripts/eval/notes_eval.py`, corpus `eval/notes/v2`) and the native Data & AI screens (`macos/…/Views/DataAndAIView.swift`, `ios/…/Views/DataAndAIView.swift`). Branch from `dev`.

**Read `00-concept-note-instructions.md` first.** It says what an instruction may and may not change, why, and where in the engine each dial lands. Three facts found in the code shape the whole plan:

1. **The engine cannot write in a language other than the one spoken.** The support gate (`pipeline.py::_Gate.reason`, L1276–1318) scores every composed line lexically against the facts it cites (`support.support_ratio`), and `verify.py` scores fact text against the verbatim quote. A German transcript written up in English would fail both. "Write in English" is therefore **not applied** (reason `language_locked`) until a cross-language gate exists. NOT NOW.
2. **First person is dropped by code, not by a prompt.** `_Gate.reason` returns `first_person` for any line `support.first_person()` matches (L1293–1294). An instruction "write as 'we'" would make the gate throw away most of the note. **Not applied** (reason `voice_locked`). Decided with the founder on 2026-10-18: keep third person.
3. **Length and section counts are a standard with bands, enforced after writing.** `doclint.py` repairs a note that falls outside `PARA2_WORDS (60,140)`, `POINTS_PER_SECTION (2,6)`, `WORDS_PER_MINUTE (8,18)` (L30–53) and `compose.VolumeBudget` sets the target before writing (`compose.py` L18–31). A "short" instruction must move **both** or the linter undoes it. N2 threads one scale through both.

| Sprint | Outcome you can see | Depends on | Length |
|---|---|---|---|
| `N0` | The style picker (Business · Formal · Informal · Academic) and the **Advanced: model behaviour** table in Note writing. Every parameter is bounded, capped by the model's configuration, explained in one sentence, and recorded on the generation that used it. Default = today's output, byte for byte. | — | 1½ weeks |
| `N1` | `PUT /v1/ai/instructions` with any text returns, within seconds, a structured **writing profile**, a list of plain sentences "Understood: …" and a list "Not applied: … because …". Nothing changes in generated notes yet. | — | 1 week |
| `N2` | A note generated in a workspace with instructions is visibly different in the ways the profile says (shorter, fewer sections, chosen terms, chosen emphasis) and **no worse** on the truth gates of the eval harness. | N1 | 2 weeks |
| `N3` | **The page.** Settings gets its own entry **Note writing** (`/settings/writing`): Style picker · Instructions (paste, **Check**, Understood / Not applied, **Save**, examples, guide) · Automatic writing · Advanced: model behaviour (tier + the parameter table). Every member reads it; an admin edits it; the note's status line names what wrote it. macOS and iOS show the same page read-only. Mockup: `mockups/note-writing-settings.html`. | N0, N1 (demo needs N2) | 2 weeks |
| `N4` | A different text per meeting type (client call, sales, 1:1 …) and "Write this note differently" on one note → regenerate. All three clients. | N2, N3 | 2 weeks |
| `N5` | Numbers: instructions are followed (per-dial compliance) and the notes stay true; a red-team corpus of hostile instructions adds no fact; starter presets; the in-product guide; the GA decision or the kill. | N2 (N3 for the preview UI) | 2 weeks |

N0 is independent and ships first. **All web UI lives in N3** — N0 and N1 are API-only (their `GET`/`PUT` shapes are what N3 renders), N4 adds the per-type tabs to N3's page and the per-note sheet, N5 adds the presets to N3's example menu. N3 can run in parallel with N2. Everything applies behind one flag, `MDX_NOTE_INSTRUCTIONS_ENABLED` (N1), off in production until N5 says GA.

## How to run a sprint with Claude Code

One sprint = one branch = one session. From the repo root:

```
git checkout dev && git pull && git checkout -b note-instructions/N0
claude
```

Paste as the first message (change the file name per sprint):

```
Read docs/sprints/note-instructions/00-README-for-claude-code.md and docs/sprints/note-instructions/sprint-N0-model-behaviour-and-style.md.
Do section "Inspect first" before writing code. If a listed fact is false in this checkout, stop and tell me which one.
Then do the tasks in order. After each task run its "verify" command and fix failures before moving on.
Do not do anything listed under "Explicit non-scope". Do not refactor unrelated code.
Finish with the "Report back" block. Do not commit; leave the working tree for my review.
```

Copy this folder to `docs/sprints/note-instructions/` first if it is not there.

## Repo rules the agent must follow (each is a CI gate or a convention in the code today)

| Rule | Where it comes from |
|---|---|
| Full app stack: `docker compose build && docker compose up -d`. `make dev-up` is infra only. `make dev-model` starts the local chat model. | `docker-compose.override.yml`, `config/models.yaml` |
| Tests run per package: `uv run --project services/note-service pytest services/note-service/tests/unit/ -v` (same shape for `libs/*`). | `Makefile` target `test` |
| Web: `cd web && npm run typecheck && npm test` (vitest; tests live in `web/tests/*.test.tsx`). | `web/package.json` |
| Native: `ios/scripts/check.sh`, `macos/scripts/make-app.sh`. **Build only — never launch the apps.** | `macos/CLAUDE.md`, `ios/CLAUDE.md` |
| Tenant data is read and written inside `tenant_connection(state.app_pool, tenant_id)` — one transaction per block. Never `asyncpg.connect` in a service. | `make check-no-direct-asyncpg`, `libs/db/src/db/tenant.py` |
| Every new table: `ENABLE` **and** `FORCE ROW LEVEL SECURITY` + the five policies of `infra/postgres/migrations/0053_workspace_model_settings.sql` L42–59 + `GRANT … TO app_role`. | `make check-rls` |
| Migrations: `infra/postgres/migrations/00NN_name.sql` + `.down.sql`; next free number is **0079** (N0 takes it; N1 → `0080`, N4 → `0081` — renumber if a sprint lands out of order). | folder listing |
| Environment variables are read only in a service's `config.py` (pydantic settings, alias `MDX_…`). | `make check-no-os-environ` |
| Model calls only through `libs/models` (`registry.resolve(tenant, op)` → `build_chat_provider` → `provider.complete(prompt, schema, max_tokens=…, temperature=…, system=…)`). Copy the pattern of `domain/ask.py::AskService._provider`. No vendor SDK imports. | `make check-no-vendor-import` |
| Errors are RFC 9457 problems with a machine `code` (`exc.problem_extras = {"code": …}` or `detail={"code": …}` as `routers/ai_settings.py` does). New codes go in `docs/api/error-codes.md`. | existing routes |
| Audit through `state.audit_writer.write_event(...)`; kinds in `audit_kinds.py` and `docs/audit/event-kinds.md`. Payloads: closed vocabulary and counts only. | `make check-audit-insert` |
| Metrics with `metrics.get_meter(...)`, names `mdx_…_total` / `mdx_…_seconds` (`unit="s"`), as `generation_metrics.py` does. | `make check-metric-names` |
| **Content never leaves the content tables.** The instruction text is admin-written configuration, but it is treated like content: never in logs, audit payloads, metric labels, `jobs.payload`, `note_generations.stats`, or eval reports under `docs/eval/`. Log ids, versions, counts, `error_kind`. | `audit_kinds.py` comments; `DocumentResult.stats` docstring |
| **Prompts contain no sentence that could be mistaken for a fact about a real meeting.** New prompt examples use the Quillhaven/Ferrytale vocabulary in `prompts.EXAMPLES`; `prompts.echoes_example` must keep catching copies. | `test_meeting_doc_prompts.py` |
| `PROMPT_VERSION` in `meeting_doc/prompts.py` changes whenever any prompt table or schema changes; pin the new fingerprint in `test_meeting_doc_prompts.py::PINNED` (L255–257). `make check-routing-report` then wants an eval report at the new version or a waiver in `docs/eval/routing-waivers.yaml`. | `prompts.py` L15, `Makefile` L135 |
| A new route changes `docs/api/note-service-openapi.json`: run `make openapi-dump` and include the file. | `make openapi-check` |
| Permission changes: `libs/auth/src/auth/perms.py::ALLOW` **and** `docs/auth/permissions.csv` (test_perms fails if they diverge). | `perms.py` docstring |
| Before "done": `make lint`, `make lint-imports`, the package tests, and — with the stack up — `make check-rls`. | `make ci`, `make ci-with-db` |

## Decisions already made (do not reopen in a sprint)

1. **Instructions change form, never truth.** They reach the compose steps (`_context`, `_reduce_block`, `_summary`) and the renderer. They never reach `_extract`, `verify.py`, `_Gate`, or the quote. Every line still passes the same gate it passes today. If an instruction can only be honoured by weakening a gate, it is *not applied* and the admin is told so.
2. **Compile at save time, apply at generation time.** One model call turns the text into a `WritingProfile` (closed schema, N1) when the admin saves or previews; the worker reads the stored profile and makes **no** extra model call per note. Generation stays as deterministic and as cheap as it is today; what the admin saw in the preview is exactly what runs.
3. **"Understood" is rendered by code from the profile, not written by the model.** The preview is a truthful readout of the stored dials. The model's only free text in the profile is the `guidance` lines, which are shown verbatim under "Also passed to the writer as wording guidance".
4. **The compiler uses the writing model** — `registry.resolve(tenant, "summarize")` — so no new processor appears in the acknowledgement list (`ai_settings.required_processors`) and the budget gate stays one table.
5. **Third person stays; the spoken language stays; attendees are never listed; the title is not instructable (yet).** Each has a closed `not_applied` reason. See the concept §4.
6. **Length is one scale, applied before and after writing.** `compose.VolumeBudget` and `doclint`'s bands read the same `scale` (0.6 / 1.0 / 1.4). No instruction may push a note below 2 bullets per section or above the engine's maxima.
7. **Terminology is applied by code after the gate and the linter, to composed lines only.** Never to a quote, a child with `quote_of`, a known name, or author-written text. Word-boundary, case-preserving, recorded as a flag.
8. **Resolution is most-specific-wins, compiled as one text** (N4): a per-type or per-note text is compiled *together with* the workspace text, so a specific profile is always complete and the worker reads exactly one profile.
9. **One flag, off in production until N5.** `MDX_NOTE_INSTRUCTIONS_ENABLED` gates the routes (404 `not_available`) and the worker's application. Dev and staging on.
10. **Style is a closed enum; raw model parameters are bounded and capped by the backend.** `writing_style ∈ {business, formal, informal, academic}` is a fixed set of prompt lines plus a few code defaults; `business` adds nothing (today's output). `ModelParams` offers only what the engine reads (`pipeline.run`, `sizes_for`, `fact_budget`, `AskService.answer`), each with a range and a cap from `ResolvedBackend`. Extraction temperature stays 0.0 (facts are precision work). Per-backend `request_overrides` (e.g. `reasoning_effort`) are per provider instance and stay a config PR.
11. **The existing `TemplateSection.synthesis_prompt` is not this feature.** It is per-section, unused by the engine ("Editing it is cosmetic", `libs/template_models/src/template_models/schema.py` L136) and stays untouched. Sprint 36 B-7 (custom-section selection) remains separate and NOT NOW.

## NOT NOW (named so nobody builds them by accident)

Output-language override (needs a cross-language support gate); first-person voice; temperature for extraction, classification, title or entity steps; top-p / penalties / seeds / stop sequences; choosing a model id by hand (the tier and `config/models.yaml` own that); per-call `request_overrides`; title format instructions (`domain/note_title.py` stays as is); instructions that add sections the family does not offer; per-member personal instructions in a team workspace; a marketplace or sharing of instruction texts between workspaces; learning instructions automatically from edits (corrections stay an eval signal, PO OS §24); applying instructions to "Ask this note" (`domain/ask.py`), the follow-up draft, the client version or the PDF; a template editor.

## After N5 (not in these files)

If N5 says GA: the guide translated to de/uk; instructions for the follow-up draft (Sprint 26) and the client version; a "suggest an instruction" prompt when the same edit recurs on three notes (an eval question first).
