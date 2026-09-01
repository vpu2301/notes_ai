# Audit kinds — Sprint 08 additions

Appends to the canonical catalogue in `docs/audit/event-kinds.md`.

| kind                                | emitter            | payload keys                              |
| ----------------------------------- | ------------------ | ----------------------------------------- |
| `note.created`                      | note-service       | `code`, `version_id`                      |
| `note.draft.updated`                | note-service       | **aggregated**: `dictation_session_id`, `autosave_count`, `start_at`, `end_at`, `final_version_number` |
| `note.finalized`                    | note-service       | `version_number`                          |
| `note.reverted`                     | note-service       | (none)                                    |
| `note.cancelled`                    | note-service       | `reason`                                  |
| `note.amended`                      | note-service       | `version_number`, `amendment_type`, `parent_version_id` |
| `note.viewed_full`                  | note-service       | `purpose` ∈ {review, audit, legal, export, collaboration, author}, `is_author` |
| `note.searched`                     | note-service       | `q`, `has_q`, `result_count`, `filters`   |
| `note.chain_integrity_failure`      | chain reconciler   | `anomaly_kind`, anomaly-specific detail   |

## Notes

- `note.draft.updated` is **aggregated per dictation session** (or
  flushed every 10 min). Not one event per PUT. This avoids audit
  volume blow-up during long dictation sessions.
- `note.viewed_full.purpose` is the read-purpose enum captured via
  `?purpose=` or `X-Read-Purpose`. Authors get `purpose=author` by
  default (no header required).
- `note.searched` records the *query string* and *result count*;
  individual results are NOT enumerated to keep the volume bounded.
  If the DPO needs a per-result trace, the search audit row + the
  user's subsequent `note.viewed_full` rows reconstruct the funnel.
- `note.chain_integrity_failure` is severity `sec` — pages security
  lead immediately.
