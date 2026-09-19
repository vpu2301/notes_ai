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

## Operational tunables

| envvar / setting                  | default | purpose                                       |
| --------------------------------- | ------- | --------------------------------------------- |
| `MDX_IDLE_DRAFT_DAYS`             | 30      | idle-draft auto-archive horizon               |
| `MDX_BACKGROUND_JOBS`             | false   | in-process scheduler (cleanup + reconciler)   |
| `MDX_BACKGROUND_JOBS_INTERVAL_S`  | 86400   | scheduler interval                            |
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
