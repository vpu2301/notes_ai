# Sprint N3 — The **Note writing** settings page (web; macOS and iOS read-only)

**Duration:** 2 weeks · **Team:** 1 web, ½ Swift (iOS + macOS), ¼ floating (copy)
**Depends on:** N0 (style + model parameters API on `/v1/ai/settings`), N1 (`/v1/ai/instructions`). N4's per-type API adds the scope tabs to this page later without changing its shape. End-to-end demo needs N2 merged.
**Unblocks:** N4 (adds tabs and the per-note sheet), N5 (presets land on this page).
**Concept:** `00-concept-note-instructions.md` §2a, §2b, §3, §4, §10.
**Priority:** P1.
**Mockup:** `mockups/note-writing-settings.html` in this folder (static, clickable; the states below are the ones it shows).

## Sprint outcome

> Settings gets a new entry under **Workspace**: **Note writing** (`/settings/writing`). It is one page, top to bottom: **Style** (Business · Formal · Informal · Academic), **Instructions** (paste text like a `CLAUDE.md`, **Check**, read what was understood and what will not be applied, **Save**; a guide and "start from an example"), **Automatic writing** (the toggle that lives in Data & AI today), and a closed **Advanced: model behaviour** disclosure (tier, temperature, context window, output budget, parallel calls, fact budget, retries, Ask). Every member can read the page; an admin can change it. The note's status line says which style, instructions version and model settings wrote it. macOS and iOS show the same page read-only with "Edit on the web".

**Demo:** admin opens Settings → Note writing. Picks **Academic** (saved on click, toast). Pastes the "Executive brief" text, presses **Check** → "Understood: Shorter than standard… · The summary has at most 4 sentences. · Left out: topic sections, open questions. · Style: Business — from your instructions (overrides the picker)" and nothing under Not applied; adds "Always write in English" → Check → appears under **Not applied** with the server's sentence; removes it, **Save** → "Instructions saved (v1)". Opens **Advanced**, drags temperature to 0.4 → the row says "Freer wording; lines the verifier cannot support are dropped, so notes may get shorter. Not yet measured." → Save → "Model settings saved (v2)". Regenerates a note → status line "Written in Academic style · workspace instructions v1 · model settings v2". A member opens the page: everything visible, nothing editable, one line at the top: "Only a workspace admin can change these."

---

## Inspect first (stop and report if any is false on your branch)

1. `web/src/pages/settings/SettingsLayout.tsx` renders the nav from hard-coded `SettingsLink`s in two groups (Account, Workspace) with `HEADINGS` / `TAB_TITLES` maps (L15–33) and gates manager rows with `manages` (L38–40); `web/src/App.tsx` mounts the settings routes under `<Route path="/settings" element={<SettingsLayout />}>` (L189–200).
2. `web/src/pages/settings/DataSettingsPage.tsx` has three views (`processing`, `writing`, `spend`) through `useSettingsView(VIEWS)`; the `writing` view (L149–210) holds the tier `Segmented` and the "Automatic note writing" checkbox; `save()` sends partial `putAiSettings` bodies and reloads on error.
3. `web/src/components/Segmented.tsx`, `ConfirmDialog.tsx`, `Toaster.tsx` (`useToast`), `lib/errorCopy.ts` (`messageFor`), `lib/useSettingsView.ts`, `lib/useDocumentTitle.ts` exist and are what the other settings pages use.
4. `web/src/components/GlossarySection.tsx` + `web/tests/glossary.test.tsx` is a self-contained settings section with its own API calls and tests — the pattern for each section component here.
5. `web/src/components/GenerationStatus.tsx` renders the engine status line from `GenerationView` and polls while live (`POLL_MS`, `REASONS` L13–22).
6. N0's `GET/PUT /v1/ai/settings` returns `writing_style`, `model_params`, `model_params_effective`, `model_params_limits`, `model_params_version`, `model_params_measured`, `tier`, `generation_enabled`, `can_edit`; N1's `GET/PUT/DELETE /v1/ai/instructions` and `POST …/preview` return `text, version, understood[], guidance[], not_applied[{text,reason,message}], compile_status, can_edit, max_chars`. `GenerationView` has `instructions {scope, version} | null` (N2) and `model_settings_version` (N0). If N4 is merged, `GET /v1/ai/instructions` also returns `scopes[]` and `/v1/ai/instructions/{scope}` exists.
7. `ios/…/Views/DataAndAIView.swift` and `macos/…/Views/DataAndAIView.swift` are opened from each platform's `SettingsView.swift` (iOS L49, macOS L48); `APIClient.aiSettings()` decodes `AISettings` (`Models.swift` L2487).

---

## Scope

1. Route `/settings/writing`, nav entry **Note writing** (every non-guest member; edit controls gated by `can_edit`), page title "Note writing", `HEADINGS`/`TAB_TITLES` entries.
2. The tier `Segmented` and the "Automatic note writing" checkbox **move** from Data & AI's `writing` view to this page; Data & AI keeps `processing` and `spend` (its `VIEWS` loses `writing`; links to `/settings/data?view=writing` redirect to `/settings/writing`).
3. Sections, in order: Style · Instructions · Automatic writing · Advanced: model behaviour. Each is its own component with its own load/error/busy state and tests.
4. Status line suffix on the note.
5. macOS + iOS: a **Note writing** row in Settings opening a read-only screen with the same four sections.
6. Copy for every control (English), the guide panel, the "start from an example" menu (one example until N5 adds the rest).

## Explicit non-scope

- Per-note instructions sheet (lives in the note; N4). Scope tabs per meeting type appear on this page when N4's API exists (N4 W-1 adds them to `InstructionsSection`); this sprint builds the single-scope section so that adding tabs is a prop, not a rewrite.
- Native editing (read-only; "Edit on the web").
- Translating the page.
- Markdown rendering of the instruction text.

---

## The page (wireframe; the mockup is the same)

```
Settings ▸ Note writing                                           [admin sees controls; member sees values]

┌ Style ───────────────────────────────────────────────────────────────────────────────┐
│ How generated notes read. Facts, evidence and the third person never change.         │
│ ( Business ) ( Formal ) ( Informal ) ( Academic )        ← Segmented, saves on click  │
│ Business — an executive meeting record: outcomes, no adjectives, headed sections.    │
│ ⓘ Overridden by your instructions (they say: Academic)   ← only when profile.style   │
└──────────────────────────────────────────────────────────────────────────────────────┘

┌ Instructions ─ v3 · updated 2 days ago by Olena ─────────────────────────────────────┐
│ Tell the writer how this workspace writes. Plain text, like a CLAUDE.md.             │
│ [ Start from an example ▾ ]                              What you can ask for ▸      │
│ ┌──────────────────────────────────────────────────────────────────────────────────┐ │
│ │ # Reader                                                                         │ │
│ │ The CEO. Thirty seconds.                                                         │ │
│ │ # Length                                                                         │ │
│ │ Short. Four summary sentences at most.                                           │ │
│ │ …                                                                                │ │
│ └──────────────────────────────────────────────────────────────────────────────────┘ │
│                                                                    1 240 / 8 000     │
│ [ Check ]  [ Save ]  [ Cancel ]                                  Clear instructions  │
│                                                                                      │
│ Understood                                   Preview — not saved yet                 │
│  • Shorter than standard — about 60 % of the usual length.                           │
│  • The summary has at most 4 sentences.                                              │
│  • Left out: topic sections, open questions.                                         │
│  • Put first and never leave out: money, dates, decisions, risks.                    │
│  Also passed to the writer as wording guidance                                       │
│  • Write for a reader who has thirty seconds.                                        │
│ Not applied                                                                          │
│  • "Always write in English" — Notes are written in the language spoken in the       │
│    meeting.                                                                          │
└──────────────────────────────────────────────────────────────────────────────────────┘

┌ Automatic writing ───────────────────────────────────────────────────────────────────┐
│ [x] Write notes automatically after a recording                                      │
└──────────────────────────────────────────────────────────────────────────────────────┘

▸ Advanced: model behaviour  (v2)                                   ← <details>, closed
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Quality tier   ( Standard ) ( Premium )   The premium tier uses a larger model…      │
│ Parameter            Value                 Recommended   Cap            What it does  │
│ Temperature          [====o-----] 0.4      0.0           —              Freer wording…│
│                      Not yet measured on the gold set.                               │
│ Context window       [ 32768 ] tokens      32 768        32 768 (model) How much of…  │
│ Output budget        [ 1536 ] tokens       1 536         —              The longest…  │
│ Parallel calls       [ 4 ]                 4             2 (model)      Faster notes…│
│ Facts per pass       [ 24 ]                24            —              How many…     │
│ Retries              ( Off ) ( Standard ) ( Thorough )                 Whether a…    │
│ Ask: temperature     [==o-------] 0.2      0.2           —              How freely…   │
│ Ask: answer length   [ 700 ] tokens        700           —              The longest…  │
│ [ Save model settings ]   [ Reset to recommended ]                                   │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

Member view: identical layout, no inputs — values as text, the picker shown with the chosen option highlighted and disabled, one `help` line under the page title: "Only a workspace admin can change these." The page never hides a section from a member (they should know how their notes are written).

---

## Web

### W-1 Route and nav

`App.tsx`: `<Route path="writing" element={<NoteWritingSettingsPage />} />`; `SettingsLayout.tsx`: `SettingsLink to="/settings/writing" label="Note writing" icon={<PenIcon />}` (add `PenIcon` to `components/icons` in the house style) in the Workspace group right after Data & AI, visible to every non-guest; `HEADINGS.writing = "Note writing"`, `TAB_TITLES.writing = "Note writing settings"`. `DataSettingsPage`: remove the `writing` view; `useSettingsView` with `?view=writing` → `Navigate` to `/settings/writing`.

### W-2 `pages/settings/NoteWritingSettingsPage.tsx`

Loads `getAiSettings()` and `getAiInstructions()` in parallel (`Promise.allSettled`); a 404 `not_available` from instructions hides the Instructions section only; any other failure renders that section's error line, never the whole page's. Passes `canEdit = settings.can_edit` down. Composes the four sections.

### W-3 `components/writing/StyleSection.tsx`

`Segmented` over `STYLES` (`business`, `formal`, `informal`, `academic`) with one help sentence per option from a constant table (the concept §2a wording). Click → `putAiSettings({writing_style})` → toast "Notes will be written in the {label} style." Overridden note: when the instructions readout contains a `style` line (N1's understood line starts with "Style:"), show `ⓘ Overridden by your instructions (they say: {Style})` and keep the control enabled.

### W-4 `components/writing/InstructionsSection.tsx`

Props: `scope` (default `"workspace"`; N4 adds tabs above and passes the scope), `canEdit`, `maxChars`, initial `AiInstructions`.
States: `view` → `editing` → `checking` → `checked` → `saving`; `failed` banner when `compile_status === "failed"` ("Your text was saved but could not be read right now. Notes are written as usual until you press Check again." + **Try again**).
Controls: header "v{version} · updated {relativeTime} by {name or 'an admin'}" (from `updated_at`, `updated_by` resolved through the members list already cached in `AuthContext` if available, else omitted); **Start from an example** menu (one entry "Executive brief" from `noteInstructionsPresets.ts`; inserts only into an empty textarea, else disabled with the title "Clear the text first"); **What you can ask for** `<details>` (concept §10, `NoteInstructionsGuide.tsx`); `textarea` (monospace, `spellCheck`, `maxLength`, `aria-describedby` counter; counter turns `danger-text` within 200 of the limit; ⌘/Ctrl+Enter = Check); **Check** → `previewAiInstructions({text})`, readout replaced, chip "Preview — not saved yet"; **Save** → `putAiInstructions({text})` (disabled when trimmed text equals stored); **Cancel** restores stored text and readout; **Clear instructions** → `ConfirmDialog` → `deleteAiInstructions()`.
Readout (`InstructionsReadout.tsx`, shared with the native copy of the layout): **Understood** list (empty + non-empty text → "Nothing specific — the notes are written as usual."), **Also passed to the writer as wording guidance** (`guidance[]` verbatim), **Not applied** rows "“{text}” — {message}" styled `help`, never `danger-text`.
Toasts: "Instructions saved (v{n}). The next note written in this workspace follows them." · "Instructions cleared." · `429 too_many_previews` → "Too many checks — try again in {Retry-After} s." · `429 budget_exceeded` → the Spend view's sentence. `beforeunload` guard while dirty.

### W-5 `components/writing/AutomaticWritingSection.tsx`

The checkbox moved verbatim from Data & AI (same `save({generation_enabled})`, same toast copy).

### W-6 `components/writing/ModelBehaviourSection.tsx`

`<details>` with summary "Advanced: model behaviour (v{model_params_version})"; opens when the URL has `advanced=1`. Inside: the tier `Segmented` moved from Data & AI (with its acknowledgement dialog and `may_choose_premium` rule — move, do not copy, the `pendingTier` logic); then the parameter table driven entirely by `model_params_limits` (never hard-code a range): `temperature`/`ask_temperature` as `input type="range"` + number (step from limits), ints as number inputs with `min`/`max`, `retries` as `Segmented`; the **Cap** column shows "{cap} (model)" when `cap` is set and the effective value differs; the **What it does** column from `PARAM_COPY` (concept §2b sentences; temperature adds the measured sentence from `model_params_measured` or "Not yet measured on the gold set."). **Save model settings** sends the full `model_params` object (`disabled` when unchanged); **Reset to recommended** → `ConfirmDialog` → `putAiSettings({reset_model_params: true})`. Member: values as text.

### W-7 Status line

`GenerationStatus.tsx`: on a finished run append " · written in {Style} style" when `view.writing_style` is set (N0 adds it to `GenerationView` — if absent on your branch, omit this clause and note it), " · workspace instructions v{n}" when `view.instructions`, " · model settings v{n}" when `view.model_settings_version > 0`; one `Link` to `/settings/writing`.

### W-8 Tests (`web/tests/noteWritingSettings.test.tsx`)

| Test | Expected |
|---|---|
| nav as member / admin / guest | link present / present / absent; route renders |
| `/settings/data?view=writing` | redirects to `/settings/writing` |
| member view | four sections, zero inputs/buttons, the admin-only line |
| style click | `putAiSettings({writing_style:"academic"})` once; toast |
| overridden note | shown when readout has a "Style:" line |
| Check → readout replaced; Cancel → restored | preview called once; stored readout back |
| Save identical text | button disabled; no request |
| Save | put once; toast with version from response |
| not_applied | DOM contains the mocked `message` verbatim |
| instructions 404 `not_available` | section absent; others render |
| `compile_status: failed` | banner; Try again sends the same text |
| 429 Retry-After 30 | toast contains "30" |
| model table | inputs' `min/max/step` equal `model_params_limits`; cap column shows "(model)" when capped |
| Save model settings | full object sent; unchanged → disabled |
| Reset | confirm → `reset_model_params: true` |
| status line | suffixes for style / instructions / model settings, one link |
| `npm run typecheck` | clean |

---

## macOS and iOS (read-only)

- **M-1 / I-1** `APIClient.aiInstructions() -> AIInstructions?` (404 `not_available` → `nil`), models `AIInstructions`, `NotApplied`; `AISettings` gains `writingStyle`, `modelParamsVersion`, `modelParamsEffective` (typed struct, N0).
- **M-2 / I-2** `Views/NoteWritingView.swift` on both platforms, opened from `SettingsView` as a new row **Note writing** right after Data & AI: Style (chosen option highlighted, others muted), Instructions (text in a scrollable monospace block capped at 12 lines + "Show all"; Understood / guidance / Not applied as lists; "v{n} · Edit on the web"), Automatic writing (value), Model behaviour (collapsed `DisclosureGroup`; the effective values as a two-column list). `compileStatus == "failed"` → the web's warning sentence.
- **M-3 / I-3** `NoteView` status suffix (same three clauses, no link).
- **M-4 / I-4** Decoding tests from the OpenAPI examples; `ios/scripts/check.sh`, `macos/scripts/make-app.sh` pass. **Build only — never launch the apps.**

---

## Security review

- Read for every member, write for `tenant_admin` only — enforced by the API (`ai_settings.write`); the page's `canEdit` is a convenience, as `SettingsLayout`'s `manages` is. A guest has no Workspace group and the API refuses anyway.
- The instruction text is rendered only in a `textarea` / text nodes; never as HTML or Markdown.
- Presets and copy are bundle constants; nothing fetched is executed or rendered as markup.
- No client computes a version, a cap or a readout: all three come from the server, so what the admin reads is what runs.

## Failure scenarios

| Failure | Behaviour |
|---|---|
| `getAiSettings` fails | page shows the error line in Style/Automatic/Advanced; Instructions still loads |
| `getAiInstructions` fails (not 404) | Instructions section error line; rest of the page works |
| Check times out / 503 | toast; text kept; stored readout stays |
| Save returns `compile_status: failed` | saved; banner; Try again |
| Unsaved edits on navigation | prompt |
| Native offline | last fetched screen cached in memory for the session; "Couldn't load" line otherwise |

## Acceptance criteria (binary)

1. `/settings/writing` exists, is in the Workspace nav for every non-guest member, and `/settings/data?view=writing` redirects to it; Data & AI no longer renders the tier or the automatic-writing toggle.
2. The demo path runs end to end in the browser on a dev stack with N0, N1 and N2 merged (style click, Check with a Not-applied row, Save, Advanced save, status-line suffixes).
3. A member's page makes exactly two `GET`s and renders no input, button or slider.
4. Every range, step and cap in the Advanced table comes from `model_params_limits` (test asserts the DOM attributes against the mocked limits); every `not_applied` message is the server's verbatim.
5. `npm run typecheck && npm test` pass; both native builds pass with decoding tests; the native screen shows the same four sections read-only.
6. The mockup `mockups/note-writing-settings.html` and the built page show the same sections in the same order with the same labels (a reviewer checks by eye; list any deliberate deviation in the report).

## Implementation order

1. W-1 → 2. W-2 skeleton with four empty sections → 3. W-3 → 4. W-5 + W-6 (moves from Data & AI, with the tier dialog) → 5. W-4 → 6. W-7 → 7. W-8 → 8. M/I-1…4 → 9. demo.

## GitHub issues

| # | Title | Depends |
|---|---|---|
| N3-1 | Route, nav entry, redirect, page skeleton | — |
| N3-2 | `StyleSection` | N0 |
| N3-3 | Move tier + automatic writing out of Data & AI; `ModelBehaviourSection` table from limits | N0 |
| N3-4 | `InstructionsSection` + readout + guide + example menu | N1 |
| N3-5 | Status-line suffixes | N0, N2 |
| N3-6 | Web tests | N3-2…N3-5 |
| N3-7 | iOS `NoteWritingView` + models + tests | N0, N1 |
| N3-8 | macOS same | N0, N1 |

## Report back

State: screenshots of the admin and member views and of the Advanced table; the exact Not-applied messages the real compiler returned for the demo text; any copy changed from the concept and why; any deviation from the mockup; `npm test` and both native check outputs; any "Inspect first" fact that differed.
