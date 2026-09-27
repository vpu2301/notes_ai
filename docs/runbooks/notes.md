# Runbook — Notes

Sprint-08 ships the central artifact of the product. This runbook lists
the operational fault-modes and their playbooks.

## Health checks

- `GET /healthz` on note-service returns 200 + JSON with db pool
  status.
- Grafana: `sprint-08-reports` dashboard (notes surface).
- Daily reconciler: cron 04:30 UTC; logs to `note-service/chain-reconciler`.

## Incident playbooks

### High autosave conflict rate

Alert: `NoteAutosaveConflictRateHigh` (> 5% of PUTs returning 409
for 10 minutes).

Likely causes (ordered):
1. **FE protocol drift** — a FE update changed the autosave cadence
   or stopped sending `expected_version` correctly. Check the FE
   release log; coordinate with frontend lead.
2. **Clock skew** — autosaves arriving out-of-order due to retry
   logic interpreting timestamps incorrectly. Check autosave-latency
   metrics for tail spikes.
3. **Two users editing the same draft** — sprint-08 doesn't
   support multi-author concurrent edit; conflict is the correct
   surface to the FE.

Mitigation:
- If protocol drift: roll back the FE.
- If genuine concurrent edit: educate; defer to sprint-future
  collaborative-editing work.
- If clock skew: investigate FE caching layer.

### Search performance issue

Alert: `NoteSearchLatencyHigh` (p95 > 500ms for 5 min).

1. SSH into a replica, `EXPLAIN ANALYZE` the slow query (use
   `pg_stat_statements` for the actual SQL).
2. If sequential scan appears on `note_versions.search_vector`:
   `REINDEX INDEX CONCURRENTLY note_versions_search_vector_idx;`
3. If GIN hit but still slow: check tenant has hit > 1M notes.
   See ADR-0021 for the partition trigger.
4. If RLS subquery showing N+1: the `EXISTS` predicate should push
   into the join. Investigate any recent migration that re-wrote the
   policy.

### Version chain break

Alert: `NoteChainIntegrityFailure` (critical; pages security lead).

**DO NOT auto-repair.** This is potentially a forensic event.

1. Pull the row from `audit.note_chain_failures` keyed by the alert
   payload's `note_id`.
2. Run `scripts/admin/note_chain_repair.py --note-id <uuid>` to
   dump the chain + history (read-only).
3. Open the security incident in the tracker.
4. Convene tech lead + DBA + security lead before any DB-level edit.
5. Manual repair: a single UPDATE with full notes in the incident
   record + manual hash-chained audit append.

### Code generation race

Symptom: two notes with identical `code` (`NOTE-{year}-{counter}`).

The advisory lock should make this impossible. If observed:
1. Check `pg_locks` for `pg_advisory_xact_lock` acquisition.
2. Confirm `note_code_counters` uniqueness constraint blocked the
   duplicate INSERT — only one of the two `RETURNING id` would have
   succeeded.
3. If somehow both succeeded, escalate to DB integrity incident.

### Stuck draft (> 30 days)

Idle-draft cleanup auto-archives at 30 days (`MDX_IDLE_DRAFT_DAYS`).
Since sprint 16 it runs in-process when `MDX_BACKGROUND_JOBS=true`
(interval `MDX_BACKGROUND_JOBS_INTERVAL_S`, default daily; ADR-0041),
or on demand:
`uv run --project services/note-service python -m note_service.jobs.idle_draft_cleanup`.
Each run audits `scheduler.job.completed` (global tenant) and
`note.cancelled` per archived draft.
For an urgent manual archive:

```sql
UPDATE notes
SET status='cancelled', cancelled_at=now(),
    cancelled_reason='manual_archive: <ticket>'
WHERE id=$1 AND status='draft';
```

Re-open within 90 days: the version chain is intact; INSERT a new
draft version and UPDATE `status='draft', cancelled_at=NULL`. Audit
this as `note.draft.updated` with payload `{manual_reopen: true}`.

### Stuck meeting state (Sprint 34, ADR-0055)

A meeting note is created when Record is pressed, so a crashed tab, a
killed app or a phone that went flat can leave `note_meetings` claiming
a capture is still `recording` or `uploading`. **Nothing is lost when
that happens** — the note holds whatever the author typed — but the
client shows a live capture that is not live.

`meeting_state_sweeper` moves `recording|uploading` older than
`MDX_MEETING_STALE_HOURS` (12 h) to `no_audio`. It runs in-process when
`MDX_BACKGROUND_JOBS=true`, or on demand:
`uv run --project services/note-service python -m note_service.jobs.meeting_state_sweeper`.
It **never deletes a note or a recording**; each run audits
`scheduler.job.completed` (global tenant) and counts
`mdx_note_meeting_state_swept_total`.

What each state means when triaging one note:

| state          | what is true                                             | what to do |
| -------------- | -------------------------------------------------------- | ---------- |
| `recording`    | no job bound yet; the client should still be capturing    | wait, or let the sweeper reclaim it |
| `uploading`    | the audio is on its way to asr-service                    | check the asr-service job list for the tenant |
| `transcribing` | `asr_job_id` is bound; ASR has not finished or no client has attached the result | when the job is `complete`, any client of the author attaching it fixes it (`POST /v1/notes/{id}/transcript`) |
| `ready`        | the transcript is in the note                             | nothing |
| `no_audio`     | discarded, never recorded, or swept                       | nothing — the typed note stands on its own |
| `failed`       | the transcription failed                                  | the asr-service runbook |

A capture stuck in `transcribing` with a `complete` job is **debt D-1**:
the server cannot chain transcription to generation by itself, so it waits
for a client. To unstick one by hand, have the author open any client, or:

```sql
-- Which captures are waiting, and on what.
SELECT note_id, state, asr_job_id, updated_at
FROM note_meetings
WHERE state IN ('recording','uploading','transcribing')
  AND updated_at < now() - interval '1 hour'
ORDER BY updated_at;
```

Do **not** hand-edit `state` to `ready`: the note would claim to hold a
transcript it does not have. Set `no_audio` if the recording is genuinely
gone.

### A correction did not stick (Sprint 35)

`dismiss`, `restore` and the owner/due `PATCH` all write an ordinary note
version, so a failure looks like any other write conflict.

| symptom | cause | what to do |
| ------- | ----- | ---------- |
| 409 `optimistic_lock_mismatch` | the note changed between load and correction (another device, or autosave) | the client reloads and retries; nothing was written |
| 404 on a key the client just showed | the line's BODY was edited, so its key changed | expected — the line is the author's now; the client reloads |
| 422 `key_would_change` | the owner/due change would rewrite the body | refuse is correct: it would orphan the recipient's responses |
| 409 `already_present` on restore | the line is back already (two devices) | nothing |
| 404 on restore | the line is older than the last 25 versions | the text is still in the chain; restore it by editing the note |

Corrections are append-only by policy (`note_item_corrections` has no
UPDATE or DELETE policy for `app_role`), so there is nothing to clean up
after a bad one — the *next* correction is the record.

```sql
-- What this note's author has been fixing, and why. No text by design.
SELECT item_key, kind, action, reason, created_at
FROM note_item_corrections WHERE note_id = $1 ORDER BY created_at DESC;
```

### The glossary taught the wrong spelling

A term is only ever added by an explicit yes to "Remember this?", so a
wrong one means somebody accepted a wrong correction. It is visible under
Workspace settings → Names and terms and deletable there by whoever added
it, or by an admin — that is the intended fix, not a DB edit.

A deleted term is soft-deleted, and the unique index only covers live
rows, so the same spelling can be added again afterwards.

```sql
-- The live vocabulary of a workspace.
SELECT term, kind, heard_as, created_at FROM workspace_glossary
WHERE tenant_id = $1 AND deleted_at IS NULL ORDER BY lower(term);
```

Terms are content: they are never logged, never audited (the payload is
the `kind` and a count) and never in the weekly CSV.

### A client saw something they should not have (Sprint 36, ADR-0057)

**Before Sprint 36 this was possible and is now fixed.** Every template
gained a `user_notes` section in Sprint 34, and the shared page and PDF
rendered every non-empty section — so recipient links created between
those two sprints rendered the author's private in-meeting scratchpad.

To find out whether a given link ever could have:

```sql
-- Notes with a live external link whose scratchpad is not empty.
SELECT n.id, n.code, l.id AS link_id, l.created_at
FROM notes n
JOIN note_share_links l ON l.note_id = n.id AND l.revoked_at IS NULL
JOIN note_versions v ON v.id = n.current_version_id
WHERE jsonb_path_exists(
        v.content_jsonb,
        '$.sections[*] ? (@.section_key == "user_notes" && @.text <> "")')
ORDER BY l.created_at DESC;
```

Those links are safe **now** — the page rebuilds from the client document
on every request, so nothing further is needed. Revoke only if the author
wants to, and tell them what was visible and for how long.

What reaches a client today, and nothing else: sections whose ROLE is in
`client_view.CLIENT_ROLES`, minus anything transcript-shaped, minus lines
marked `(internal)`. Check any note with:

    GET /v1/notes/{id}/client-version

That endpoint is the same builder the shared page uses, so it is the
authoritative answer to "what would they see".

### Carry-over is missing or wrong

| symptom | cause | what to do |
| ------- | ----- | ---------- |
| no "Still open" block | the meeting has no `series_key` — it did not start from a calendar event, or its title is generic | the author links it by hand ("This continues…", `POST /v1/notes/{id}/meeting/previous`) |
| block missing on the 2nd meeting of a series | the previous note is not viewable by THIS author (ADR-0057) — often a private note | expected; the author cannot be shown items from a note they cannot read |
| items carried from the wrong meeting | two series share a title and an attendee set | link by hand; calendar-based series are unaffected |
| an item is ticked that nobody did | only the author can tick today (`done_marked`); `done_mentioned` needs the generation engine | check the audit log for `note.carried_item_updated` |

```sql
-- What this meeting is carrying, and where from.
SELECT c.item_key, c.state, c.from_note_id, m.series_key, m.series_source
FROM note_carried_items c
JOIN note_meetings m ON m.note_id = c.note_id
WHERE c.note_id = $1 ORDER BY c.position;
```

### A note was never written (Sprint 33)

The engine runs in `note-worker`, a separate process of the same image.
A note with no generated content is one of five things:

| symptom | check | what it means |
| ------- | ----- | ------------- |
| no generation row at all | `MDX_NOTE_GENERATION_ENABLED`, and the object store | the enqueue never ran; the note is still a note |
| `queued` and not moving | is `note-worker` up? `SELECT * FROM jobs WHERE kind='note.generate'` | nothing is draining the queue |
| `waiting_on_model` on the job | the chat backend | scaling from zero; it retries by policy, no user action needed |
| `partial` | `failed_ranges` | some windows failed; the document is written from the rest and the client names the minutes |
| `complete` with empty sections | `stats.facts_dropped_quote` | nothing verified. Honest: no filler is written |

```sql
-- Where this note's generations got to.
SELECT id, status, step, windows_total, windows_done, windows_failed,
       error_kind, backend, model_id, created_at, finished_at
FROM note_generations WHERE note_id = $1 ORDER BY created_at DESC;
```

**Never hand-edit a note's sections to "fix" a generation.** The writer
decides what it may rewrite by comparing against
`stats.section_hashes`; a section edited by hand becomes the author's and
stops being rewritten — which is correct behaviour, and confusing if you
did it yourself while debugging. Use `POST /v1/notes/{id}/generation`.

Stuck live generation (worker killed between the lease expiring and the
reaper running) — the unique index refuses a new one:

```sql
UPDATE note_generations SET status='failed', error_kind='manual_reset',
       finished_at=now()
WHERE note_id=$1 AND status IN ('queued','running');
```

## Model tiers, budgets and retention (Sprint 37)

### generation-failures

A fifth of generations failing in half an hour. Look at the backend
first: `ModelBackendUnavailable` / `ModelBackendAuth` fire before this one
when the cause is the endpoint, and `docs/runbooks/model-backends.md` has
those. When the backend is healthy, the failures are per-note:

```sql
SELECT error_kind, count(*) FROM note_generations
WHERE created_at > now() - interval '1 hour' AND status = 'failed'
GROUP BY 1 ORDER BY 2 DESC;
```

`snapshot_unreadable` in bulk means the object store, not the model —
check `S3_ENDPOINT` and the bucket, not the endpoint.

### generation-slow

p95 over ten minutes. In order: queue depth
(`SELECT status, count(*) FROM jobs WHERE kind='note.generate' GROUP BY 1`),
worker replicas, then the backend's own latency. One worker replica draws
two jobs at a time (`BATCH` in `worker.py`) and at most
`MDX_NOTE_GENERATION_PER_TENANT` from any one workspace, so a backlog of
one workspace's uploads does NOT explain a slow queue for everyone —
that is the fair claim doing its job (migration 0055).

### budget

Not an incident. A workspace is over `monthly_budget_cents` (or its
plan's `ai_cents_per_month`), so nothing is enqueued for it and its
admins were told once for the month. Their notes still work; the missing
part is the written-up document.

```sql
-- What this workspace has spent, and what it is allowed.
SELECT * FROM model_usage_monthly WHERE tenant_id = $1 AND month = date_trunc('month', now());
SELECT monthly_budget_cents, generation_enabled FROM workspace_model_settings WHERE tenant_id = $1;
```

Raising it is the admin's own action on **Settings → Data & AI**. Do it
for them only on a written request, and record it.

### snapshot-sweep

Nothing swept in 48 hours while notes were being written. The transcript
snapshot is a second copy of a whole meeting, kept only for the minutes a
generation needs it, so this is a retention breach rather than untidiness.

* is `MDX_BACKGROUND_JOBS` on for the API deployment (not only the worker)?
* are the deletes failing? `snapshot_sweeper.delete_failed` in the logs.

```sql
-- What is still pointing at an object it should have released.
SELECT count(*) FROM note_generations
WHERE snapshot_key IS NOT NULL AND created_at < now() - interval '24 hours';
```

The sweep is idempotent; running it by hand is safe:

    uv run --project services/note-service python -m note_service.jobs.snapshot_sweeper

### writer-conflicts

The writer never overwrites a person: it compares a section against
`stats.section_hashes` and skips what changed. A sustained spike means it
is losing every race — usually an autosave loop on a client, occasionally
two generations for one note. Check for the second first:

```sql
SELECT note_id, count(*) FROM note_generations
WHERE status IN ('queued','running') GROUP BY 1 HAVING count(*) > 1;
```

### noise-overridden

Summary Engine v2 (Q2). The extractor flags lines as noise; code confirms
each flag (`verify.confirm_noise`: short and empty, provably another
language, or a duplicate) and a cap overrides everything but language and
duplicate exclusions when a run would leave out more than 2 % of the
speech. This alert means overrides happen in more than one generation in
ten — the model is calling real speech background, the failure the
2026-09-22 audit found ("a whole story nicht berücksichtigt"). Notes are
still complete; the model is drifting.

1. Did `PROMPT_VERSION` or the `summarize` route change? Per generation:
   ```sql
   SELECT prompt_version, backend, count(*),
          avg((stats->>'noise_overridden')::int) AS overridden,
          avg((stats->>'excluded_ms')::float / NULLIF((stats->>'speech_ms')::float, 0)) AS excluded_share
   FROM note_generations WHERE created_at > now() - interval '6 hours'
   GROUP BY 1, 2 ORDER BY 3 DESC;
   ```
2. Run the eval on the same backend: `make eval-notes BACKEND=<backend>` —
   `excluded_speech` and the r01/m06 checklists show it without real data.

### unsupported-lines

Summary Engine v2 (Q2). Every summary sentence, topic bullet and framing
sentence passes a support gate against the facts it cites (`meeting_doc/
support.py`); a failing line is dropped, and a summary where more than
30 % fail is retried once strictly with a skeleton of fact ids, then
composed by code from the most specific facts (`stats.summary_ladder`:
`model` / `strict` / `composed`; F3 amendment after r03). The overview is
never a key-point list. The gate's threshold is per language
(`support.LINE_SUPPORT_BY_LANGUAGE`, en 0.5, de/uk 0.4, provisional until
calibrated with `scripts/eval/support_calibration.py`). A fifth of lines
failing means notes are getting thinner, not wrong. Break it down by reason:

```sql
SELECT prompt_version, backend,
       sum((stats->'lines_unsupported'->>'name')::int) AS name,
       sum((stats->'lines_unsupported'->>'number')::int) AS number,
       sum((stats->'lines_unsupported'->>'unsupported')::int) AS unsupported,
       sum((stats->'lines_unsupported'->>'example')::int) AS example,
       count(*) FILTER (WHERE stats->>'summary_ladder' = 'composed') AS composed
FROM note_generations WHERE created_at > now() - interval '6 hours'
GROUP BY 1, 2;
```

`example` above zero is a prompt example copied into a note — see
`docs/security/2026-09-22-november-sentence.md`. Anything else: compare the
backend against the committed eval baseline (`docs/eval/notes-baseline-*.md`).

### copied-facts

Sprint F2 (ADR-0063). A fact whose `text` is its quote copied is kept as
**evidence** — other lines may cite it, its row has `placement =
'evidence'` (migration 0064) — but it is never a line of the note. A window
with any copy among its verified facts is extracted once more with the restate suffix and no more facts than the
first answer had; restated facts that cite the same line replace the copies.
`NoteGenerationCopiedFacts` fires when a third of kept facts are still
copies after that: the note is thin because the model is transcribing.

Code also drops, before a fact is stored, a remark that informs nobody
(`dropped_no_information`: nothing but judgement words — "This boat is
incredible.") and keeps a line in the speaker's own voice as evidence only
(`dropped_first_person`). Lines the reduce steps write pass the same three
rules (`lines_unsupported.copied|no_information|first_person`).

```sql
SELECT prompt_version, backend,
       sum((stats->>'facts_copied')::int) AS copied,
       sum((stats->>'windows_restated')::int) AS restated,
       sum((stats->'restate_outcomes'->>'improved')::int) AS improved,
       sum((stats->>'dropped_no_information')::int) AS chatter,
       sum((stats->>'dropped_first_person')::int) AS first_person
FROM note_generations WHERE created_at > now() - interval '6 hours'
GROUP BY 1, 2;
```

`improved` near `restated` means the restate works and only the first
answer copies — a prompt or backend change. `improved` near zero means the
model copies whatever it is told; compare the backend against the committed
eval baseline before raising the threshold (`pipeline.RESTATE_COPY_SHARE`, 0 since the
2026-09-26 eval).

### figures

Sprint F3 (ADR-0064). A `figure` is kept only when its value was said
(digits or words) and its unit was said; otherwise it is dropped and
counted (`mdx_note_generation_facts_total{outcome="figure_dropped_value"|
"figure_dropped_unit"}`, `stats.figures_dropped_*`). A rise in
`figure_dropped_value` with no model change is the number-word reader
(`meeting_doc/numbers.py`) missing a form — look at the language:

```sql
SELECT stats->>'language' AS language, prompt_version,
       sum((stats->>'figures_kept')::int) AS kept,
       sum((stats->>'figures_dropped_value')::int) AS no_value,
       sum((stats->>'figures_dropped_unit')::int) AS no_unit,
       sum((stats->>'qualifiers_cleared')::int) AS qualifiers_cleared
FROM note_generations WHERE created_at > now() - interval '1 day'
GROUP BY 1, 2;
```

Two rows for one quantity are a conflict the speaker made (both flagged
`figure_conflict`), never averaged. A converted value (feet said, metres
written) is dropped by design.

### overview-and-topics

F3 amendment after r03 (ADR-0064). Every note opens with two paragraphs of
prose: what the recording is (code) and what it says (the summary ladder).
Headings come from the topics pass; over 40 facts it runs block by block.
When it fails on a recording over 10 minutes, the note is chaptered by time
("07:40 — Alex Karp") instead. Nightly gates: `composed` ≤ 5 % of notes,
`topics_failure` ≤ 5 % of podcasts and lectures.

```sql
SELECT prompt_version, backend,
       count(*) FILTER (WHERE stats->>'summary_ladder' = 'composed') AS composed,
       count(*) FILTER (WHERE stats->>'topics_fallback' = 'chapters') AS chaptered,
       count(*) FILTER (WHERE stats->>'topics_failure' = 'provider_error') AS provider_error,
       count(*) FILTER (WHERE stats->>'topics_failure' = 'schema_invalid') AS schema_invalid,
       count(*) FILTER (WHERE stats->>'topics_failure' = 'too_few_topics') AS too_few,
       count(*) FILTER (WHERE stats->>'topics_failure' = 'all_bullets_unsupported') AS unsupported,
       sum((stats->>'adverts_cut')::int) AS adverts_cut,
       count(*) AS notes
FROM note_generations WHERE created_at > now() - interval '1 day'
GROUP BY 1, 2;
```

`provider_error` or `schema_invalid` is the backend. `all_bullets_unsupported`
rising with `composed` is the support gate: check the language, then the
calibration. An advert that reached a note means a cue is missing from
`windows.AD_CUES`; a presenter line naming a trailer voice means the
dominant-speaker rule (`pipeline.PRESENTER_MIN_SHARE`) did not hold.

### document-lint

D1 (ADR-0065). Every generation is linted for form; findings are counted by
taxonomy code and rule, never with text. A code climbing after a deploy
points at the prompt or the render; see the rule table in ADR-0065.

```sql
SELECT prompt_version, key AS code, sum(value::int) AS findings, count(*) AS notes
FROM note_generations, jsonb_each_text(stats->'lint')
WHERE created_at > now() - interval '1 day'
GROUP BY 1, 2 ORDER BY 3 DESC;
```

### Deploying the engine (Summary Engine v2)

**Migrate first, then the workers.** Order (Q6 T5):

1. Migrations **0058** (recording types), **0059** (generated lines),
   **0060** (weekly notes-quality reader) — `make migrate-up` or the
   migration job. 0057 (note titles, ADR-0059) must already be applied.
   Before deploying to a database that has ever run an engine branch,
   check `SELECT version FROM schema_migrations ORDER BY 1 DESC LIMIT 5`:
   the migrations were never numbered differently in this repository, but
   an applied migration is never renamed — a mismatch gets a corrective
   migration.
2. note-service (API).
3. note-worker.
4. web.

0058 widens `note_meetings.meeting_type_detected`; 0059 adds the line
columns to `note_generated_items` (`cites`, `certainty`, `attributed_to`,
`corrections`, `mentions`) and a kind vocabulary. A worker from Q5 on writes
those columns: started against a database without 0059, every generation
fails at its item insert. Rolling back: workers first, then `migrate-down`
0060 → 0059 (it deletes the line rows it added; fact rows stay) → 0058.

Config: `MDX_NOTE_ENTITY_MODEL_TIER` is `true` in staging (to measure it on
real recordings) and `false` in production (`values-prod.yaml`) until an
eval report shows `model_tier_precision ≥ 0.9` on `eval/notes/v2`
(ADR-0060). `MDX_NOTE_GENERATION_PER_TENANT` is unchanged.

### Drills (Q6 T5)

Run on staging with a fixture tenant, never a customer recording. One line
per run: date, outcome, who.

| Drill | Expected | Runs |
|---|---|---|
| Chat backend paused 10 min during generations | jobs `waiting_on_model`, no failed notes; resume completes them; classify/name fall back and the document still writes | **not run** — no staging deployment yet |
| nlp-service down | transcripts served raw (`_structured`), generation runs, dates unresolved (no wrong dates) | **not run** |
| Migration 0059 rolled back with a Q5 worker running | worker `error_kind = schema_mismatch`, alert fires, note untouched; roll forward fixes | **not run** |
| Model flags every line as noise (fixture tenant / shadow config) | `NoteGenerationNoiseOverridden` fires; note still has content | **not run** |

### Glossary hygiene (Sprint I2)

The workspace glossary is the transcriber's prompt on every recording.
Since I2 only vocabulary goes: a term whose words are all role words or
ordinals ("Moderator II", "speaker background") is refused on `POST
/v1/glossary` (`term_not_vocabulary`) and, if stored before the rule, is
left out of `GET /v1/glossary/hint` and shown on the glossary page as "not
sent" with a banner. `scripts/admin/glossary_audit.py` lists the affected
workspaces (counts; `--show-terms` prints the terms to the terminal for one
support case). The tables are `tests/fixtures/glossary/role_words.json`;
add a language there and in `domain/glossary.py`, `RememberableName`
(macOS/iOS) and `web/src/lib/glossaryRule.ts` — each has a test against
the fixture.

### Weekly notes quality (Q6 T8)

`make weekly-notes` (host cron `infra/compose/cron/weekly-notes.cron`, chart
CronJob `mdx-weekly-notes`, Mondays 06:45 UTC) runs
`scripts/ops/notes_quality.sql` as `funnel_reader` and writes
`notes-quality-YYYY-WW.csv`: per week, by recording type and language, across
all workspaces — kept-line rate (7 d), dismiss rate by kind with the reason
histogram, regenerate rate, share-without-edit, minutes to first share,
corrections accepted, type and title changed. Counts only: the role reads
metadata columns, and the two text comparisons are 0060's SECURITY DEFINER
functions that return ids and integers.

The job prints the last complete week next to the meeting-document
concept's thresholds: **kept-line < 50 % or regenerate > 40 % after four
pilot weeks → the document is not trusted; share-without-edit not above the
baseline week → not send-ready.** The first production run is the baseline
week; the four-week read is a calendar entry.

Approximations: a kept line is its text, word for word, still in the note
7 days later (an edited owner or date counts as not kept — a lower bound);
`type_changed` loses a note once a regeneration records the author's type.
Evidence opened per line is not reported: no evidence-opened event exists.

### Changing which model writes notes

The routing table (`config/models.yaml`) is the only place, and the
procedure is in `docs/runbooks/model-backends.md#tier-flip`: eval parity →
shadow → flip → rollback. Nothing in note-service needs redeploying for a
tier change; a workspace that has not acknowledged the new processor
stays where it was.

## Operational tunables

| envvar / setting                  | default | purpose                                       |
| --------------------------------- | ------- | --------------------------------------------- |
| `MDX_IDLE_DRAFT_DAYS`             | 30      | idle-draft auto-archive horizon               |
| `MDX_BACKGROUND_JOBS`             | false   | in-process scheduler (cleanup + reconciler)   |
| `MDX_BACKGROUND_JOBS_INTERVAL_S`  | 86400   | scheduler interval                            |
| `MDX_NOTE_GENERATION_ENABLED`     | true    | the document engine; off = notes are the transcript in a section, as before Sprint 33 |
| `MDX_NOTE_GENERATION_PER_TENANT`  | 3       | concurrent generations per workspace (soft cap, enforced in the claim — migration 0055) |
| `MDX_NOTE_GENERATION_SNAPSHOT_HOURS` | 24   | how long a transcript snapshot may outlive its generation before the sweep deletes it |
| `MDX_NOTE_GENERATION_SHADOW_BACKEND` | ""   | run a candidate backend beside the real one and keep only counts; empty = no shadow runs |
| `MDX_NOTE_GENERATION_SHADOW_PERCENT` | 5    | share of generations shadowed, sampled on the generation id |
| `MDX_MEETING_STALE_HOURS`         | 12      | how long a capture may claim to be recording/uploading before the sweeper calls it `no_audio` |
| `MDX_CLIPS_PER_USER_PER_HOUR`     | 60      | audio-replay clips per user (raised from 30 in Sprint 35: playing the seconds behind a cited line is ordinary reading, not a spot-check) |
| `MDX_TEMPLATE_CACHE_MAXSIZE`      | 5000    | in-process template cache entries             |
| `MDX_TEMPLATE_CACHE_TTL_SECONDS`  | 60      | template cache TTL                            |
| `MDX_FFMPEG_PATH`                 | ffmpeg  | audio-clip pipeline binary (ADR-0037)         |
| `MDX_EMAIL_PROVIDER`              | mock    | `smtp` to actually send share mail            |
| `MDX_NOTE_SMTP_HOST` / `_PORT`    | localhost / 1025 | relay for share mail (Mailpit in dev) |
| `MDX_NOTE_EMAIL_FROM` / `_FROM_NAME` | notes@notes-ai.local / Notes AI | envelope sender; must match the SMTP username on Gmail |
| `MDX_NOTE_EMAIL_REPLY_TO`         | notes@notes-ai.local | fallback reply path when the sharer has no address on file |
| `MDX_APP_BASE_URL`                | http://localhost:5173 | origin the mailed links point at |
| `MDX_SHARE_EMAILS_PER_USER_PER_HOUR` | 60   | per-sender cap, counted in recipients         |
| `MDX_SHARE_EMAIL_MAX_RECIPIENTS`  | 10      | recipients per send                           |

(Autosave min-interval 5 s and diff-cache 1024 entries are in-code
defaults — `domain/autosave_rate_limit.py`, `domain/diff_cache.py`.)

## Calendar connections (0019)

The home page's **Coming up** list reads the user's calendar through
note-service. Two ways in, both stored in the same table and read by the
same clients:

- **Google account (OAuth)** — needs a Google OAuth client on the
  deployment (below). Lists every calendar of the account; the user picks.
- **Calendar link (0020)** — needs nothing on the deployment. The user
  pastes the calendar's private iCal address; see *Calendar links* below.

### Google account

Nothing on the Google path works until the deployment has an OAuth client:

1. Google Cloud Console → *APIs & Services* → enable **Google Calendar API**.
2. *Credentials* → **OAuth 2.0 Client ID**, type *Web application*. Add
   `GOOGLE_CALENDAR_REDIRECT_URI` (default
   `http://localhost:8006/v1/calendar/google/callback`) as an authorised
   redirect URI — scheme, host, port and path must match exactly.
3. Set `GOOGLE_CALENDAR_CLIENT_ID` and `GOOGLE_CALENDAR_CLIENT_SECRET` on
   note-service (compose reads them from the shell / `.env`). Leave them
   empty and both clients hide the connect button (`available: false`).
4. Consent screen: scopes `openid`, `email`,
   `https://www.googleapis.com/auth/calendar.readonly` — read-only; the
   service never writes to a calendar. While the app is in *Testing* status
   only listed test users can connect, and Google expires their refresh
   tokens after 7 days.

Storage: `calendar_connections`, one row per (user, account). Tokens are
envelope-encrypted with the tenant KEK (`token_blob`); a dump is useless
without the master key. Rows are personal — every read filters on the
caller's `sub` on top of tenant RLS.

### Calendar links (0020)

`POST /v1/calendar/ics/connect {url}` adds a calendar by its private
subscription address — no Google client, no OAuth, and it works for
Outlook and iCloud feeds too. Where users find the address:

- Google Calendar → Settings → the calendar → *Integrate calendar* →
  **Secret address in iCal format**.
- Outlook.com → Settings → Calendar → *Shared calendars* → **Publish a
  calendar** (ICS link).
- iCloud Calendar → share icon → **Public calendar** (the `webcal://` link).

How it works: the service fetches the feed once at add time (a wrong link
fails right there), then again on every `GET /v1/calendar/events` (no
cache — Google itself only refreshes a secret address every few hours, so
the feed is the bottleneck, not us). The ICS is parsed in
`domain/ics_calendar.py` (RRULE/EXDATE/RECURRENCE-ID expansion via
`python-dateutil`), and events come out shaped like the Google ones.

Storage: the same `calendar_connections` row with `provider = 'ics'`. The
URL **is** the credential (anyone holding it reads the calendar), so it
is sealed in `token_blob` like a token; `account_email` carries the feed's
display label (its `X-WR-CALNAME`, or the host); `feed_fingerprint` is
sha256(url) so the same link added twice updates the row.

Fetching a user-supplied URL is SSRF surface. Policy (`normalize_feed_url`,
`assert_public_host`): https only (`webcal://` rewritten), no credentials
in the URL, host must resolve to public addresses only — checked before
the request and after every redirect, at most 5 hops — body capped at
5 MB, and the response must contain `BEGIN:VCALENDAR`. There is no
allow-list of hosts on purpose: any calendar product qualifies.

Link symptoms:

- **"The link no longer works"** (`last_error = feed_gone`, HTTP 401/403/
  404/410 from the feed) — the user reset the secret address in Google
  Calendar, or the published calendar was unpublished. They add the new
  link; the old row is disconnected from the ⋯ menu.
- **Times off by hours** — the feed uses a `TZID` zoneinfo does not know
  (Windows names from some Outlook exports). The parser falls back to the
  feed's `X-WR-TIMEZONE`, then UTC, and logs `calendar.ics.unknown_tzid`.
- **Connect answers 400 "private network"** — the address resolves to a
  loopback / RFC 1918 / link-local host. Expected; there is no override.
- **Event missing that Google shows** — the secret address lags the UI by
  up to a few hours on Google's side; nothing to do server-side.

Google symptoms:

- **"Google asked to sign in again"** — the refresh token died
  (`needs_reauth = true`, `last_error = needs_reauth`). Password change,
  revoked at myaccount.google.com, or the 7-day testing-mode expiry. The
  user reconnects; nothing to do server-side.
- **`?calendar=error&reason=no_refresh_token`** — Google skipped the
  consent screen. The connect URL always sends `prompt=consent`; check that
  a proxy is not rewriting the query.
- **`reason=redirect_uri_mismatch`** — the registered redirect URI differs
  from `GOOGLE_CALENDAR_REDIRECT_URI`. Compare character by character.
- **Connect answers 400 `return_to`** — the client's origin is not in
  `CORS_ALLOWED_ORIGINS` (or `MDX_CALENDAR_RETURN_TO_EXTRA`). The Mac app's
  `notesai://` scheme is always allowed.

## Secrets

None specific to the notes surface beyond the shared master-key mount
(`MDX_MASTER_KEY_PATH`) used by the audio-clip pipeline.

## Sprint-08 wrap

This runbook is the operational contract for the notes surface. If
a playbook step turns out wrong in practice, update this file in the
same PR as the fix.

## audio-clip-failures

`AudioClipFailuresHigh` (sprint 15, ADR-0037): the decrypt→slice→encode
pipeline on `POST /v1/audio-clips` is erroring (`outcome="pipeline_error"`,
502s to callers). 410s are NOT failures — they are the honest retention
answers (`no_audio_source` / `audio_not_retained` / `audio_erased` /
`audio_partially_retained`).

1. Is ffmpeg present in the note-service image? (`MDX_FFMPEG_PATH`,
   Dockerfile installs it since S15.) A missing binary fails EVERY clip.
2. `mdx_audio_clip_pipeline_latency_ms` p95 climbing toward the ffmpeg
   timeout → the source objects are huge (long sessions) or the host is
   CPU-starved; the whole-object GCM decrypt (~2 MB/min of audio) is
   expected cost, not a leak.
3. Corrupt source WAV (`unexpected WAV layout` in logs): the session was
   written by a pre-S04 build or the object was truncated — check
   `audio_files.sha256` against the object.
4. Object-store lifecycle: clips live 5 min (Redis registry) with a 1-day
   bucket ILM backstop on `mdx-audio-clips`; a full bucket is never the
   explanation — check the bucket's 1-day expiry lifecycle rule is set.

## Spaces (0021)

A **space** is a personal folder for notes: `GET/POST /v1/spaces`,
`PUT/DELETE /v1/spaces/{id}`, and `PUT /v1/notes/{id}/space` with
`{"space_id": …}` (`null` unfiles). Spaces are scoped to the caller's
`sub` on top of tenant RLS — colleagues see the same notes but file them
their own way — and need only `note.read`. A note is in at most one space
per user. Deleting a space stamps `deleted_at` and unfiles its notes
(`note_spaces`, `note_space_items`; no hard deletes). The Mac and iOS apps
read the same list; the web app does not use spaces yet.

## Sharing a note by e-mail

`POST /v1/notes/{id}/share/email` takes `{recipients, message, lang,
expires_in_days}` and sends a branded HTML mail per recipient, inline.
Recipients split two ways: a workspace member is granted read access and
mailed a link to the note in the app (plus the usual content-free
`note.shared_with_you` notification); anybody else gets their own
recipient link (one per address, reused on a resend, expiring after
`expires_in_days` clipped to the workspace ceiling) and is mailed that,
so the sender sees who opened it and can turn one off without the
others. The public link is never mailed. The reply reports `sent` /
`rejected` / `failed` per address (the outcome is also recorded on the
link, for the sheet's Sent / Retry chips), so one dead mailbox never
loses the rest of the batch, and the audit event `note.link_emailed`
records counts only — never the addresses.

**"Nothing arrives."** In order:

1. **Is note-service pointed at a real relay?** The most common cause,
   and the one with no error anywhere: `MDX_NOTE_SMTP_*` is SEPARATE from
   the `MDX_AUTH_SMTP_*` block that carries sign-in codes. Set only the
   auth one and codes reach real inboxes while every share is delivered
   to Mailpit — a clean 250, `sent` for every recipient, "Sent to ..." in
   the UI, and nothing in the recipient's mailbox. `docker compose exec
   note-service env | grep MDX_NOTE_SMTP` is the check; if it says
   `mailpit`, the mail is at http://localhost:8025 and never left the box.
2. Is `MDX_EMAIL_PROVIDER=smtp`? The `mock` provider accepts every
   message and drops it (and refuses to start in production/staging, so
   this only bites in dev).
3. Check the service log for `note.share_mail.send_failed` —
   `error_class` distinguishes a timeout from a refusal.
4. Delivered but not in the inbox? Look in spam. Every share mail carries
   `Date` and `Message-ID` (`adapters/email.py`); a relay that strips or
   a build that omits either gets the message filed as suspicious.

**"The link in the mail 404s."** `MDX_APP_BASE_URL` is not the origin the
SPA is served from. The server builds `<base>/notes/<id>` and
`<base>/s/<token>`; nothing else in the pipeline knows the browser's URL.

**"Every recipient comes back `rejected`."** A 5xx from the relay,
usually authentication: on Google Workspace `MDX_NOTE_SMTP_PASSWORD` must
be a 16-character App Password, and the From address must match the SMTP
username.

**"A sender is stuck on 429."** The hourly cap is counted in recipients,
not calls — `MDX_SHARE_EMAILS_PER_USER_PER_HOUR`. The counter is a Redis
key per sender per hour (`note:share-mail-rl:<sub>:<bucket>`) and fails
OPEN if Redis is down, so a 429 means the cap was genuinely reached.

## Recipient links (Sprint 19)

Migration 0035 lets a note carry many live links: the one `public` link
from 0016 plus any number of `recipient` links, each labelled, expiring
(90 days by default, `MDX_RECIPIENT_LINK_DEFAULT_DAYS`) and revocable on
its own. Routes: `POST/GET /v1/notes/{id}/links`, `DELETE
/v1/notes/{id}/links[/{link_id}]`. The anonymous page
(`GET /v1/shared/{token}`) now also serves the sender's logo
(`/logo`) and counts the product CTA (`/cta` → 302 to
`MDX_APP_BASE_URL/join?ref=<ref_code>`), and every `/v1/shared/*` route
is rate-limited per IP (60/min), per link (300/h) and per IP on the CTA
(20/h). Keys: `note:shared-rl:{ip|link|cta}:<subject>:<window>`.

**"Can a draft be shared?"** Yes — since 0042 a note is a living
document with no finalize step, and any live note can be shared. The
recipient sees the current text plus a "what changed" strip when it
moved since their last visit.

**"Every reader gets 429."** The per-IP bucket collapsed to one address:
the service sits behind a proxy that is not in `TRUSTED_PROXY_CIDRS`, so
every request looks like it came from the proxy. Set the CIDR (same
variable auth-service uses); the alert `SharedPageRateLimitHigh` is the
usual way this is noticed. With Redis down the caps fail OPEN and the
log carries `ratelimit.backend_error` + `note.shared_rate_limit_degraded`.

**"The CTA lands on the wrong host."** `MDX_APP_BASE_URL` is the only
thing the redirect is built from — the same setting share mails use.

**Erasing a recipient's data (data-subject request).** Two places hold a
recipient's address and nothing else does:

1. `note_share_links.recipient_email` in the sender's tenant — revoking
   the link (`DELETE /v1/notes/{id}/links/{link_id}`, or the sheet's
   "Turn off") sets it to NULL; the label the sender typed stays.
2. `referrals.lead_email` (auth-service, global) — the `/join` fake door.
   `uv run python scripts/ops/erase_lead.py <email>` deletes every lead
   row for the address (needs `DB_TENANT_WRITER_DSN`).

Audit payloads never carry the address, the token or the ref code
(`note.link_created`, `note.viewed_via_link`, `note.cta_clicked`,
`lead.captured` — see `docs/audit/event-kinds.md`).

**Rolling back 0035** refuses to run while any note has more than one
live link; revoke recipient links first (`DELETE /v1/notes/{id}/links`).

## Recipient responses (Sprint 20)

Migration 0037 adds `note_action_items` (derived from the section text
the first time a version is read — see `docs/architecture/notes.md`) and
`share_link_responses` (what a recipient did on the shared page).
Anonymous writes: `PUT/DELETE /v1/shared/{token}/items/{key}/response`
and `…/sections/{key}/flag`, capped at 60 per link per hour
(`MDX_SHARED_RL_WRITE_PER_HOUR`, key `note:shared-rl:write:<link>:<window>`)
on top of the Sprint 19 per-IP cap. The author team is notified
(`note.recipient_responded`) once per link per
`MDX_RESPONSE_NOTIFY_DEBOUNCE_S` (600 s; Redis key `note:resp-notify:<link>`).

**Warming items after deploying 0037.** Items are derived on first
read, so nothing is required; `uv run python scripts/ops/backfill_action_items.py`
(idempotent; `--tenant <uuid>` for one workspace) only pre-computes them.

**"An abusive or wrong comment shows on the note."** The author clears
it from the Responses tab (`POST /v1/notes/{id}/responses/{rid}/clear`);
the row stays with `cleared_by`/`cleared_at` for audit and disappears
from every read. Turning the link off (`DELETE /v1/notes/{id}/links/{link_id}`)
stops further writes from that recipient. Comments never reach an
e-mail — the digest carries the link label and the kind only.

**"A recipient says their confirmation vanished."** The line was edited
in an edit, so its `item_key` changed and the response stayed on
the old wording (by design). The Responses tab with `?include_cleared`
still lists it; the recipient re-confirms the new text.

**Dispute rate alert (`SharedPageDisputeRateHigh`).** More than 20% of
acted-on items disputed over 7 days is the concept doc's kill signal:
stop scaling distribution and look at extraction quality (the
"check owner" items and the `parsed_owner`/`parsed_due` panel) before
anything else.

## Recipient mail from the product (Sprint 22, ADR-0049)

`POST /v1/notes/{id}/links/{link_id}/send` (and `POST …/links` with
`send: true`) mails a recipient link inline through the same SMTP
adapter as `/share/email` (`MDX_NOTE_SMTP_*`, `MDX_EMAIL_PROVIDER`). The
outcome is on the link row: `delivery_status`, `sent_at`, `send_count`,
`last_send_error` (an error class). Caps: 3 per link, 50 per sender,
200 per workspace per day (`MDX_SHARE_MAIL_*_PER_DAY`, Redis keys
`note:share-mail:{link|user|tenant}:…`).

**"Nothing arrives."** Same checklist as the share mail section above
(`MDX_NOTE_SMTP_*`, not the auth block). The mail's unsubscribe link is
built from `MDX_API_PUBLIC_BASE_URL` — if that is `localhost` in a
deployed environment, recipients cannot opt out.

**"Send answers 409 `recipient_opted_out`."** The address is on the
global suppression list (`share_mail_suppressions`, hashed). The sender
can still copy the link. To honour a recipient who changed their mind,
delete the row as `tenant_writer`: compute the hash with
`note_service.domain.recipient_mail.email_hash(address)` (needs the
deployment's `MDX_SHARE_MAIL_SUPPRESSION_PEPPER_HEX`) and
`DELETE FROM share_mail_suppressions WHERE email_hash = $1`. The same
lookup answers a data-subject request: the row is the only trace.

**"Every send from one workspace is 429."** The daily workspace cap —
usually a script, occasionally a big team. Raise
`MDX_SHARE_MAIL_TENANT_PER_DAY` deliberately; the counter
`mdx_recipient_mail_sent_total` shows the volume.

**Funnel.** `scripts/jobs/weekly_funnel.py` writes the weekly CSV as
`funnel_reader`; Grafana's "Funnel" datasource uses the same role
(migration 0040). If the panel is empty, the role has no policy on a
table the query touches — `check-rls` lists policies per table.
