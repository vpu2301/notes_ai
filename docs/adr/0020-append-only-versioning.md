# ADR-0020 — Append-only versioning for notes

- Status: accepted
- Date: 2026-05-13
- Sprint: 08
- Deciders: tech lead, security lead, content lead, DPO

## Context

Sprint-08 stands up the central artifact of the product — the note.
Everything pivots on whether the note the author saw at a given moment
can be reconstructed. The model choices that anchor this are:

1. The **status lifecycle** (draft → finalized → amended / cancelled)
   is irreversible in the forward direction. (The lifecycle originally
   included a `signed` status; the e-signature flow was removed with
   the medical vertical, and finalize is now a plain validated
   transition.)
2. Every content change creates a **new immutable row**, never an
   in-place UPDATE.
3. The hash chain over versions attaches to specific version rows; the
   exact bytes that were hashed must be retrievable forever.

The shape we picked — `notes` (one head per logical note) +
`note_versions` (append-only history, with `current_version_id`
on the head) — leans on three load-bearing decisions made on day-1:

- Versions are JSONB blobs with strict Pydantic validation
  (`note_models.NoteContent`); the canonical bytes for hashing
  are deterministic (JCS, ADR-0024).
- `notes.current_version_id` is a deferrable FK so the
  two-step `INSERT notes` → `INSERT note_versions` → `UPDATE
  notes.current_version_id` pattern can run inside one
  serializable transaction (chicken-egg dependency resolved at
  COMMIT).
- `notes` denormalises a few columns (title, dates) that the search
  path filters/sorts on, so the primary index can be on `notes`
  alone — avoiding a costly join for the hot search path.

## Decision

Adopt append-only versioning with a head-row pointing at the current
version. Detailed rules:

- `note_versions` is INSERT-only.
- DELETE on either table is forbidden at the RLS-policy level; the
  soft-delete is `cancel`.
- `parent_version_id` carries the chain link. For non-amendment
  versions parent = previous version (linear); amendments also use
  the immediately previous version as parent (linear) — see the
  day-4 property test and the chain-reconciler verifier.
- `version_number` is 1..N contiguous per note. Gaps are an
  integrity bug (caught by the daily reconciler + the CI property
  test that re-runs the same verifier).
- Idempotency for autosave retries: the most-recent version row's
  `metadata.body_hash` is checked against the incoming body hash.
  Match + same `expected_version` → return the prior version, no
  new row. Different body, same `expected_version` → 409 (FE must
  reload).

## Consequences

Positive:
- Storage cost is linear in writes; not a concern at expected scale.
- Retrievability is absolute: any historical state can be reconstructed
  by walking the version chain.
- The amendment chain integrity is a property the verifier (one
  module, two callers — CI + cron) actively maintains.

Negative / accepted:
- Reads that need "the note as it looked at time T" require a JOIN
  to `note_versions`. Mitigated by `notes.current_version_id` for
  the hot read path.
- The two-step insert is a sharp edge; documented in
  ``services/note-service/src/note_service/domain/notes_repository.py``
  and gated behind the `create_note_with_v1` helper. Bypassing the
  helper is a CI lint that blocks PRs.

## Alternatives considered

- **Mutable rows + audit_log of diffs.** Rejected — audit_log carrying
  the canonical hashed bytes turns the audit log into an integrity
  oracle; we want integrity attached to a *specific row* in the data
  schema, not a side log.
- **OCC via row version (`xmin`).** Works for autosave but doesn't
  give us the chain semantics we need for amendments.
- **Event-sourced model.** Strictly powerful but operationally heavy;
  picking it now would have cost a second sprint of plumbing. May be
  revisited if a future export feature needs proper temporal
  semantics.

## Links

- Sprint-08 spec §3.1, §3.2.
- ADR-0021 (Postgres `simple` FTS) — search atop this model.
- ADR-0024 (JCS canonicalisation) — the hashing primitive.
- `services/note-service/src/note_service/domain/notes_repository.py`.
- `services/note-service/src/note_service/domain/chain_integrity.py`.
- `services/note-service/tests/property/test_amendment_chain.py`.
