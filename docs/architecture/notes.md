# Notes architecture (sprint-08)

The central product artifact: a structured, versioned business note.
Sprint-08 establishes the data model, lifecycle, search, and diff
surface.

## Data model

```
notes ── 1:N ── note_versions
  (head)          (append-only)
  ├─ current_version_id ──────┐
  └─ status enum              │
                              │
   note_versions
     ├─ parent_version_id  ◄──┘  (chain link)
     ├─ version_number     (1..N contiguous)
     ├─ is_amendment       (true for amendments)
     ├─ content_jsonb      (Pydantic-validated)
     ├─ rendered_text      (FTS-indexed)
     ├─ diff_jsonb         (summary of changes vs parent)
     └─ metadata           ({body_hash: ...} for idempotency)
```

The two-step insert (ADR-0020) creates `notes` with NULL
`current_version_id`, inserts v1 in `note_versions`, then UPDATEs
the head. The FK is `DEFERRABLE INITIALLY DEFERRED` so the
constraint check happens at COMMIT.

A note belongs to a **tenant + author** (`primary_author_id` +
`co_author_ids`); there is no other subject entity.

## Status lifecycle

Allowed transitions (`domain/note_lifecycle.py`):

```
   ┌──────────┐   finalize   ┌──────────────┐   amend    ┌─────────┐
   │  draft   │─────────────►│  finalized   │───────────►│ amended │──┐
   └────┬─────┘ ◄────revert──└──────┬───────┘            └─────────┘  │ amend
        │     (1h, author)          │                         ▲       │ (again)
        │ cancel                    │ cancel                  └───────┘
        ▼                           ▼
   ┌──────────┐                ┌──────────┐
   │ cancelled│                │ cancelled│
   └──────────┘                └──────────┘
```

Finalize is a plain lifecycle transition with validation (required
sections present, typed-field completeness). Transitions are
single-statement UPDATEs with `WHERE status = expected_from`;
concurrent transitions are caught and 409'd. The revert window is 1
hour and limited to the primary author.

## Optimistic locking

`PUT /v1/notes/{id}/draft` requires `expected_version`. The
service:
1. row-locks the `notes` row,
2. compares `expected_version` to `current_version.version_number`,
3. mismatch → 409 with hint payload,
4. match → append new version, update `current_version_id`.

Idempotent retries use `metadata.body_hash`: same body + same
`expected_version` returns the prior version with `idempotent_replay:
true`.

## Amendments

`POST /v1/notes/{id}/amend` is allowed on finalized (or already
amended) notes. It creates a new `note_versions` row with
`is_amendment=true` and moves the note to `amended`; further
amendments keep appending versions.

## Chain integrity

`domain/chain_integrity.py` is a pure-Python verifier; it's called
by:
- The CI property test (`tests/property/test_amendment_chain.py`),
- The daily reconciler (`jobs/chain_reconciler.py`, cron 04:30 UTC).

Anomalies recorded both in `audit.note_chain_failures` (for the
dashboard) AND in the hash-chained `audit.events` log. The hash
chain (append-only versions, JCS canonical bytes via
`note_models.canonical_content_bytes`) is generic integrity — it
survives from the signing era with the e-signature flow removed.

## Search

`GET /v1/notes/search` — `simple` FTS config (ADR-0021), GIN
indexes on `notes.search_vector` (title/code) and
`note_versions.search_vector` (rendered_text). Filters (author,
status, created-date range) compose with AND. `simple`'s lack of
stemming is documented in the user-facing search tips screen
(sprint-15). Synonym query expansion (ADR-0038) reads the tenant's
`synonyms` table.

Cursor pagination on `(created_at DESC, id DESC)`. The cursor is
opaque base64 JSON.

Two standings reach the search: `note.read` (member / viewer) gets
the full list; `stats.read` alone (tenant_admin) gets the same rows
stripped of every content-bearing field — counts and timings for the
dashboard, no browsable content.

## Read purpose

Non-author full-read of `GET /v1/notes/{id}` requires
`?purpose=<value>`. Allowed: `review`, `audit`, `legal`, `export`,
`collaboration`. Captured into the `note.viewed_full` audit row.

## PII redaction in snippets

`domain/pii_redactor.py` runs on snippets returned to viewers who
are not authors of the note (primary_author, co_author). Conservative
regex sweep over personal identifiers (full names, national id
numbers, birth dates) — second line of defence behind the role check.

## Diff endpoint

`GET /v1/notes/{id}/diff?from=<v>&to=<v>` — both arguments accept a
`version_number` or a UUID `version_id`. `difflib.SequenceMatcher`
char-level diff; metadata diff for the title.

In-process LRU cache (`domain/diff_cache.py`) keyed by
`(note_id, from_id, to_id)`. Versions are immutable so cache hits
are always safe.

## PDF export

`GET /v1/notes/{id}/pdf` renders the current version through
Jinja2 + WeasyPrint (`domain/pdf.py`, deterministic byte-equal
output). Tenant branding (`domain/branding.py`) supplies the issuer
name from the `tenants` row. Draft notes always carry a bilingual
DRAFT watermark; `?variant=clean` is honoured only for
finalized/amended notes; cancelled notes are refused (409).

## Observability

- Metrics: `mdx_notes_autosave_conflicts_total`,
  `mdx_notes_search_latency_ms_histogram{has_q}`,
  `mdx_notes_search_expansion_total{hit}`,
  `mdx_notes_diff_cache_lookups_total{hit}`,
  `mdx_notes_chain_integrity_check_failures_total`,
  `mdx_field_confirmed_total{field_type}` /
  `mdx_field_overridden_total{field_type}` (extractor quality),
  `mdx_audio_clips_created_total{source_kind,outcome}`.
- Dashboard: `infra/grafana/dashboards/notes.json`.
- Alerts: `infra/prometheus/rules/notes.yml`.

## Related surfaces

- **Create-from-transcript**: `POST /v1/notes/from-transcript` turns a
  completed batch transcription into a draft note; template selection
  is deterministic keyword scoring (`domain/template_match.py`) with a
  `meeting_notes` fallback. `GET /v1/notes/by-source-job` powers the
  jobs-list "already assigned" badge.
- **Dictation sessions**: sessions create drafts via `POST /v1/notes`;
  finalize can backfill `source_session_id`.
- **Audio replay (ADR-0037)**: per-section segment listing under
  `/v1/notes/{id}/sections/{key}/audio-clips` plus the ephemeral
  clip pipeline under `/v1/audio-clips`.
- **Synthesis**: `POST /v1/notes/{id}/synthesize` runs the
  deterministic mock engine by default (`MDX_SYNTHESIS_PROVIDER`);
  results live in `note_synthesis_jobs`.
- **Templates**: CRUD/clone/rebind under `/v1/templates`;
  cosmetic-vs-structural edit classification is
  `template_models.classify_edit` (ADR-0016). The browse facet is
  `templates.category`.
- **Idle-draft cleanup** (sprint-16, ADR-0041): in-process scheduler,
  `MDX_BACKGROUND_JOBS`.

## `field_specific_metadata` — the normative key registry (sprint 13)

The dict stays `dict[str, Any]` on `NoteSection` — the hash chain
commits to canonical bytes, so the storage shape never depends on the
registry. Discipline is enforced at the **write path**: note-service
validates every non-empty dict against the section's template
`field_type` (`note_models.validate_field_metadata`), and the nlp
extractor constructs metadata via the typed models in
`note_models.field_metadata` — raw-dict assembly is forbidden.

| `field_type` | allowed keys |
| --- | --- |
| `choice` | `{selected: <option value>, confidence?: float 0..1, source: "extracted"\|"manual"}` |
| `multi_choice` | `{selected: [<option values>, ≥1 unique], confidence?, source}` |
| `numeric_with_unit` | `{value: number, unit: str, confidence?, source}` |
| `date` / `date_with_note` | `{date: "YYYY-MM-DD" (real calendar date), confidence?, source}` |
| `free_text` (and any other) | none — an empty dict only |

Common rules (enforced by the typed models):

- **An empty dict is always valid** — every pre-S13 note.
- **`source` is required** whenever any other key is present.
  `extracted` = a pipeline proposal (FE renders it as such);
  `manual` = user-confirmed. Nothing ever auto-promotes
  extracted → manual; promotion is exclusively an explicit user action
  arriving as a draft PUT.
- **`confidence` is required for `extracted`** (the extractor always
  knows it) **and must be omitted for `manual`** — a user
  confirmation is not a probability. Confirming a choice therefore
  writes `{selected, source: "manual"}`.
- **Unknown keys are unwritable**: note-service rejects them with
  `422 field_metadata_invalid` (section-addressed). A `selected` value
  that is not one of the section's template option `value`s is
  `422 choice_value_unknown`.
- Sprint-15 (note review) adds its keys by extending
  `META_MODEL_BY_FIELD_TYPE` in `note_models.field_metadata` — never
  by bypassing it.

## Typed finalize completeness (sprint 13)

`min_chars` measures prose, so it says nothing about a `choice`
section whose answer lives in `field_specific_metadata`. Each typed
field type gets its own "filled" rule. Free-text sections behave
exactly as they did in sprint 08 — zero change for existing templates.

| `field_type` | filled when | violation code |
| --- | --- | --- |
| `free_text` | `min_chars` (unchanged) | `missing_required_section` / `below_min_chars` |
| `choice` | metadata `selected` present (any `source`) | `choice_not_selected` |
| `multi_choice` | `selected` non-empty (any `source`) | `choice_not_selected` |
| `numeric_with_unit` | metadata `value` **and** `unit` present | `numeric_not_filled` |
| `date` / `date_with_note` | metadata `date` present; `date_with_note` also applies `min_chars` to the note | `date_not_filled` (+ `below_min_chars`) |

All violations travel in the existing sprint-08 `FinalizeProblem`
shape at **422** (409 stays reserved for status/version conflicts);
the codes are registered in `_REASON_BY_CODE`.

An `extracted` value satisfies "filled": the author saw the proposal
and chose to finalize, which is acceptance.

### Provenance in finalized content

A non-required typed section may carry `source: "extracted"` into a
finalized note. That is deliberate and honest: the hash chain covers
the content including its provenance marker, so a reader can always
tell which values a machine proposed and the author left standing,
versus which they entered or confirmed themselves.
