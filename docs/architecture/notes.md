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

A note is a living document. It is `draft` from creation until it is
cancelled; there is no "done" state (migration 0042 retired the
finalize → amend lifecycle and moved every frozen row back to
`draft`; `finalized_at` is kept as history). The one transition
(`domain/note_lifecycle.py`):

```
   ┌──────────┐   cancel    ┌───────────┐
   │  draft   │────────────►│ cancelled │
   └──────────┘             └───────────┘
```

It is a single-statement UPDATE with `WHERE status = expected_from`;
a concurrent transition is caught and 409'd. Every edit appends a
version (see below), sharing works on any live note, and action
items are derived lazily from whichever version is current when it is
first read (`domain/action_items.py::ensure_items`).

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

## Amendments (retired)

`POST /v1/notes/{id}/amend` was removed with the finalize lifecycle
(0042). The `is_amendment` / `amendment_type` / `amendment_reason`
columns on `note_versions` remain as history and are still returned
on version listings; every new version is an ordinary autosave.

## Chain integrity

`domain/chain_integrity.py` is a pure-Python verifier; it's called
by:
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
name from the `tenants` row. The output is clean by default;
`?variant=draft` adds the bilingual DRAFT watermark when the author
wants a copy marked provisional; cancelled notes are refused (409).

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
- **Dictation sessions**: sessions create drafts via `POST /v1/notes`
  and stamp `source_session_id`.
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

## Typed-field provenance (sprint 13)

A typed section may carry `source: "extracted"` in its metadata. That
is deliberate and honest: the hash chain covers the content including
its provenance marker, so a reader can always tell which values a
machine proposed and the author left standing, versus which they
entered or confirmed themselves. (Sprint 13's finalize completeness
rules were retired with finalize itself, 0042.)

## Action items as a derived projection (Sprint 20, migration 0037)

`note_action_items` is **derived** from the `action_items` / `next_steps`
section text of one `note_versions` row, materialised the first time
that version is read — author items view or shared page
(`domain/action_items.py::ensure_items`) — and never edited directly
except for `status`. The section text stays
canonical: the version hash chain, the editor, PDF, Markdown and search
are unchanged, and nothing can drift from the prose.

**Line grammar** (deterministic, no model): `[bullet] [Owner:] task [— [by|due] date]`.
An explicit `Name:` prefix (≤ 4 words) is the owner with confidence 1.0;
two leading capitalised words are an *inferred* owner at 0.5, shown to
the author as "check owner". The date goes through `parse_due` — ISO,
`DD.MM[.YYYY]`, `18 Sep`, `Sep 18`, month names in en/uk/de, weekdays,
today/tomorrow/next week — anchored to today in the tenant's time zone.
Unparseable text keeps `due_text` with no `due_date`.

**`item_key`** = first 16 hex of sha256(normalised task text without
owner/date/bullets, lower-cased). It is the identity a recipient's
response attaches to: an unchanged line keeps its key — and its
responses and status — across an edit; an edited line starts clean,
because the recipient confirmed *that* wording. Duplicate lines within
one version collapse to the first.

`share_link_responses` holds what a recipient did (`confirm` / `done` /
`dispute` on an item, `flag` on a section) keyed by link and target, one
live row per (link, target); a new stance replaces the old one, which is
cleared rather than deleted. The comment is text, capped at 280
characters, refused if it carries a URL, and rendered as text only —
never Markdown, HTML or an e-mail body.

The extractor is a seam (`ActionItemExtractor`); `rules` is the only
implementation. A model-backed extractor would replace the parser, not
the projection.
