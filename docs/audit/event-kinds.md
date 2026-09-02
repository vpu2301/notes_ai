# Audit Event Kinds

Every event written through `AuditWriter` has a `kind` field — a
dotted-string identifier. This catalogue is the source of truth. The
constants live at `services/<service>/src/<pkg>/audit_kinds.py`
(per service); centralising them as a service-local module catches
typos at import.

| kind                              | severity | emitter                          | meaning                                                            |
| --------------------------------- | -------- | -------------------------------- | ------------------------------------------------------------------ |
| `auth.login`                      | info     | auth-service /auth/login         | Successful password-grant exchange                                 |
| `auth.login_failed`               | warn     | auth-service /auth/login         | Failed credential check.                                           |
| `auth.refresh`                    | info     | auth-service /auth/refresh       | Successful refresh-token rotation                                  |
| `auth.refresh_replay_detected`    | sec      | auth-service /auth/refresh       | Old refresh token replayed after rotation. Sessions force-revoked. |
| `auth.logout`                     | info     | auth-service /auth/logout        | Explicit logout (when Bearer header allowed tenant resolution)     |
| `auth.reauth_failed`              | sec      | auth-service re-auth surfaces    | Wrong password from a live session (e.g. `purpose=password_change`). Payload: purpose, kc_status. Repeated failures trip Keycloak's brute-force detector. |
| `auth.account_locked`             | sec      | auth-service /auth/login         | Keycloak rejected the login with account-locked detail             |
| `authz.denied`                    | sec      | every service's `requires()` dep | Role/scope check failed. Payload carries action + target_kind + reason. |
| `user.invited`                    | info     | auth-service /admin/users/invite | tenant_admin created a new user                                    |
| `user.deactivated`                | sec      | auth-service /admin/users/{sub}/deactivate | Sessions revoked, status flipped                         |
| `user.reactivated`                | sec      | auth-service /admin/users/{sub}/reactivate | Deactivated user re-enabled; status flipped back to active |
| `user.role_changed`               | sec      | auth-service PUT /admin/users/{sub}/roles | Realm roles changed by tenant_admin. Payload carries old_roles → new_roles. |
| `user.reset_mfa`                  | sec      | auth-service DELETE /auth/mfa/{sub} | S16 — MFA enrolment cleared by admin (secret attributes wiped, sessions revoked). Payload: sessions_revoked. |
| `user.mfa_reminded`               | sec      | auth-service POST /admin/users/{sub}/mfa-reminder | S21 — an access review asked a user to enrol MFA. The only write an `auditor` can make; it changes nothing about the account. Payload: reminder_count, first_reminded_at. Pairs with `auth.mfa.enrolled` to answer "how long did this account sit unprotected after we noticed". |
| `auth.mfa.enrolled`               | info     | auth-service POST /auth/mfa/verify | S16 — TOTP enrolment completed (first valid code). Resolves any open `mfa_reminders` row. |
| `auth.session.revoked`            | info/sec | auth-service logout / replay / deactivate / POST /auth/sessions/revoke-all | S16 — sid or sub pushed onto the revocation denylist (ADR-0040). Payload: reason (+ sid for logout). sec on refresh_replay / user.deactivated, info on plain logout. The self-service "sign out everywhere" in settings emits it with `scope=all, initiated_by=self`. |
| `auth.password.reset_requested`   | sec      | auth-service POST /auth/password/forgot | Password-reset link minted and queued. Payload: ip_hash (salted). **Emitted only for an address that resolves to an active account** — writing one for an unknown address would rebuild the enumeration oracle the endpoint's uniform 202 exists to prevent. |
| `auth.password.reset_completed`   | sec      | auth-service POST /auth/password/reset | A mailed token was redeemed and the password replaced. Every session revoked and all other outstanding tokens spent. Payload: ip_hash. |
| `auth.password.changed`           | sec      | auth-service POST /auth/password/change | A signed-in user changed their own password after re-entering the current one. Same tail as reset: sessions revoked, tokens spent, notification queued. Payload: ip_hash. A *wrong* current password emits `auth.reauth_failed` with `purpose=password_change`. |
| `auth.account.lockdown`           | sec      | auth-service POST /auth/security/lockdown | The "this wasn't me" button in the security-notification email. Highest-signal event this service emits: a user asserting their account was taken over. Payload: ip_hash, sessions_revoked (false = Keycloak or the denylist refused; investigate). |
| `tenant.created`                  | sec      | auth-service POST /tenants        | A new tenant/workspace was onboarded; actor becomes owner         |
| `tenant.updated`                  | info     | auth-service PATCH /tenants/{id}   | Tenant profile / branding / contact fields changed                |
| `tenant.logo_updated`             | info     | auth-service PUT /tenants/{id}/logo | Tenant logo uploaded / replaced                                   |
| `tenant.member_added`             | sec      | auth-service POST /tenants/{id}/members | A principal was linked to the tenant with a role             |
| `tenant.member_role_changed`      | sec      | auth-service PATCH /tenants/{id}/members/{sub} | Membership role changed (old → new in payload)        |
| `tenant.member_removed`           | sec      | auth-service DELETE /tenants/{id}/members/{sub} | Membership revoked                                    |
| `tenant.switched`                 | info     | auth-service POST /tenants/{id}/switch | User switched their active tenant                            |
| `audit.chain_verified`            | info/sec | nightly verifier (`scripts/jobs/nightly_verify.py`) | One per tenant per verify run. severity flips to `sec` on divergence |
| `asr.audio_uploaded`              | info     | asr-service POST /asr/jobs       | Audio file enveloped + persisted; row inserted in `audio_files`    |
| `asr.audio_deleted`               | sec      | retention tooling                | Crypto-shred of a recording: MinIO object + metadata row (its wrapped DEK) destroyed. Constant reserved; no runtime emitter today. |
| `asr.job_queued`                  | info     | asr-service POST /asr/jobs       | Job durably recorded + enqueued on Redis Streams                   |
| `asr.transcription_started`       | info     | asr-worker processor             | Worker picked the job up; row moved to `running`                   |
| `asr.transcription_complete`      | info     | asr-worker processor             | Inference + encrypted transcript stored; row moved to `complete`   |
| `asr.transcription_failed`        | error    | asr-worker processor             | Job failed with `error_kind` — the closed vocabulary in `asr_models.errors` (`docs/api/asr-job-errors.md`). Payload carries `error_kind` + a truncated `detail` |
| `asr.transcription_failed`        | warn     | asr-service reaper               | Same kind, `severity=warn`, `payload.actor="reaper"`: a job stranded by a dead worker (`worker_lost`) or a message that never reached one (`queue_lost`), closed out from outside the worker |
| `asr.transcript_accessed`         | info     | asr-service GET /asr/jobs/{id}/result | Plaintext transcript served (decrypt-and-return proxy; presigned URLs only ever serve ciphertext). Payload: audio_id, bytes |
| `asr.job_cancelled`               | info     | asr-service DELETE / worker      | Job cancelled by user or by worker honouring cancel_requested      |
| `asr.speakers_named`              | info     | asr-service PUT /asr/jobs/{id}/speakers | Someone named the diarized speakers of a job. Payload: the labels touched (`SPEAKER_N`), never the names — who a speaker is, is content (ADR-0031) |
| `asr.quota_exceeded`              | warn     | asr-service POST /asr/jobs       | Tenant hit the monthly upload cap                                  |
| `asr.key.master_missing`          | error    | asr-worker startup (fail-closed) | Master key absent/malformed at boot. **System-wide, pre-tenant** — emitted as a CRITICAL structured log, NOT a per-tenant audit-chain row (no tenant context exists). Worker exits non-zero; see runbook § master-key-missing |
| `dictation.session.started`       | info     | dictation-service WS handler     | New streaming session accepted (after auth + capacity)             |
| `dictation.session.resumed`       | info     | dictation-service WS handler     | Existing session reattached after a network drop                   |
| `dictation.session.finalized`     | info     | dictation-service finalize       | Session ended cleanly; transcript + audio persisted                |
| `dictation.session.abandoned`     | info     | dictation-service abandon timer  | Reconnecting > 30 min with no client; resources freed              |
| `dictation.session.failed`        | error    | dictation-service handler        | Worker_failed / opus_fatal / internal                              |
| `dictation.audio.uploaded`        | info     | dictation-service finalize       | End-of-session WAV encrypted + stored to MinIO                     |
| `dictation.audio.truncated`       | warn     | dictation-service finalize       | tmpfs ring wrapped; audio file shorter than total received         |
| `dictation.upgrade.failed`        | warn/sec | dictation-service ws upgrade     | Auth / rate-limit / subprotocol / origin rejection. sec on repeats |
| `voice_command.executed`          | info     | frontend (forwarded)             | Sprint 05 — the user's intent fired in the editor                  |
| `voice_command.undone`            | warn     | frontend (forwarded)             | Sprint 05 — the user undid the fired intent within 600 ms          |
| `voice_command.executed_failed`   | warn     | frontend (forwarded)             | Sprint 05 — command's referenced state (template section) gone     |
| `abbreviation.policy.set`         | info     | nlp-service PUT /nlp/abbreviations | Sprint 05 — tenant admin upserted an abbreviation rule           |
| `abbreviation.policy.deleted`     | info     | nlp-service DELETE /nlp/abbreviations/{id} | Sprint 05 — tenant admin removed an abbreviation rule    |
| `dictation.nlp_timeout`           | warn     | dictation-service NlpClient      | Sprint 05 — NLP call exceeded 200 ms; emitted raw Whisper text    |
| `template.created`                | info     | note-service POST /templates     | M1 — plain create of a tenant template (vs clone). Payload: code   |
| `template.cloned`                 | info     | note-service POST /templates/clone | Sprint 06 — tenant cloned a system or own template              |
| `template.updated`                | info     | note-service PUT /templates/{id} | Sprint 06 — cosmetic edit; same row, schema_version bumped         |
| `template.versioned`              | info     | note-service PUT /templates/{id} | Sprint 06 — structural edit; new row with parent_template_id       |
| `template.deprecated`             | info     | note-service DELETE /templates/{id} | Sprint 06 — soft-delete; status='deprecated'                    |
| `template.viewed_full`            | info     | note-service GET /templates/{id} | Sprint 06 — full schema_jsonb fetched                              |
| `template.rebound`                | info     | note-service POST /templates/{id}/rebind | Sprint 17 — one draft note moved to a successor template. Payload: note_id, from_template_id, to_template_id (ids only, no content) |
| `dictation.section_switched`      | info     | dictation-service WS handler     | Sprint 06 — section navigation; prompt swap for next window      |
| `dictation.nlp_timeout`           | warn     | dictation-service finalize       | Sprint 05 contract, wired in S14 — NLP pipeline unavailable at finalize; the raw transcript is persisted unchanged |
| `conversation.speaker_mapping.manual_set` | info | dictation-service WS handler | Sprint 14 — the client's manual speaker-name assignment. Payload: mapping |
| `conversation.draft.created`      | info     | dictation-service finalize       | Sprint 14 — note draft created from a conversation session via note-service POST /v1/notes. Payload: session_id, code, version_id, segments |
| `conversation.draft.create_failed`| warn     | dictation-service finalize       | Sprint 14 — draft creation skipped/failed; the transcript is already persisted. Payload: reason |
| `note.created`                    | info     | note-service POST /v1/notes (+ /from-transcript) | Sprint 08 — draft note created. Payload: code, version_id |
| `note.draft.updated`              | info     | note-service PUT /v1/notes/{id}/draft | Sprint 08 — autosave, AGGREGATED per dictation session (not per keystroke). Payload: version_number, dictation_session_id |
| `note.finalized`                  | info     | note-service POST /v1/notes/{id}/finalize | Sprint 08 — draft → finalized lifecycle transition. Payload: version_number |
| `note.completed`                  | info     | note-service POST /v1/notes/{id}/finalize | M1 — finalize completion summary (paired with `note.finalized`). Payload: version_number, section_count, low_confidence_count, source_session_id |
| `note.reverted`                   | info     | note-service POST /v1/notes/{id}/revert | Sprint 08 — finalized → draft inside the 1 h author window. |
| `note.cancelled`                  | info     | note-service POST /v1/notes/{id}/cancel | Sprint 08 — note cancelled. Payload: reason |
| `note.amended`                    | info     | note-service POST /v1/notes/{id}/amend | Sprint 08 — versioned amendment on a finalized note; status → amended. |
| `note.viewed_full`                | info     | note-service GET /v1/notes/{id} | Sprint 08 — non-author full read; carries the declared `purpose`. |
| `note.searched`                   | info     | note-service GET /v1/notes/search | Sprint 08 — search executed. Payload: q, has_q, result_count, filters. Results are never enumerated. |
| `note.chain_integrity_failure`    | sec      | note-service chain reconciler / property test | Sprint 08 — an append-only version chain anomaly was detected. Investigate immediately. |
| `note.pdf_rendered`               | info     | note-service GET /v1/notes/{id}/pdf | M1 — PDF rendered. Payload: version_number, size_bytes, purpose |
| `note.deleted`                    | info     | note-service DELETE /v1/notes/{id} | 0016 — soft delete by the author or a tenant_admin; the row stays, every public link is revoked. Payload: code, status |
| `note.visibility_changed`         | info     | note-service PUT /v1/notes/{id}/visibility | 0016 — `private` ↔ `workspace`. Payload: from, to |
| `note.shared`                     | info     | note-service POST /v1/notes/{id}/share | 0016 — a workspace member was given read access (they get a `note.shared_with_you` notification). Payload: with (sub), via |
| `note.unshared`                   | info     | note-service DELETE /v1/notes/{id}/share/{sub} | 0016 — access taken back. Payload: with (sub) |
| `note.link_created`               | info     | note-service POST /v1/notes/{id}/public-link | 0016 — an "anyone with the link" token was minted. Payload: link_id, expires_at. Never the token. |
| `note.link_revoked`               | info     | note-service DELETE /v1/notes/{id}/public-link | 0016 — public link(s) revoked. Payload: revoked (count) |
| `note.viewed_via_link`            | info     | note-service GET /v1/shared/{token}[/pdf] | 0016 — anonymous read through a public link; no actor. Payload: link_id, format |
| `note.synthesis_started`          | info     | note-service POST /v1/notes/{id}/synthesize | Spec item 1 — synthesis run begun (raw dictation → clean prose). Payload: section_count, language, provider |
| `note.synthesis_completed`        | info     | note-service POST /v1/notes/{id}/synthesize | Spec item 1 — synthesis run finished (paired with `note.synthesis_started`). Payload: job_id, section_count, language, provider |
| `note.field.extracted`            | info     | note-service POST /v1/notes/{id}/finalize | Sprint 13 — ONE aggregated row per finalized note: how many typed fields still carried machine-extracted values at finalize. Deliberately not per-utterance (chain pollution). Payload: field_types (list), section_count. **No values, no prose.** |
| `note.field.confirmed`            | info     | note-service PUT /v1/notes/{id}/draft | Sprint 13 — the author confirmed an extracted typed-field value (extracted→manual with the same value). Payload: section_key, field_type, and for CLOSED vocabularies only: selected (option slugs). **Never free text.** |
| `note.field.overridden`           | info     | note-service PUT /v1/notes/{id}/draft | Sprint 13 — the author REPLACED an extracted value with a different one; the extractor-quality signal behind step-08's override-rate dashboard. Payload: section_key, field_type, selected/was (slugs). **Never free text** — a free-text override records its section and type only. |

## Autocomplete (sprint 10 — autocomplete-service)

Tenant-scoped, hash-chained. Constants in
`services/autocomplete-service/src/autocomplete_service/audit_kinds.py`
(also listed in `docs/audit/audit-kinds-sprint-10.md`).

| kind                                      | severity | emitter         | meaning                                              |
| ----------------------------------------- | -------- | --------------- | ---------------------------------------------------- |
| `autocomplete.phrase.created`             | info     | phrases router  | Personal/tenant phrase added (`source`, `language`).  |
| `autocomplete.phrase.updated`             | info     | phrases router  | Phrase changed (`source`, fields_changed).           |
| `autocomplete.phrase.deleted`             | info     | phrases router  | Phrase soft-deleted.                                 |
| `autocomplete.phrase.write_rejected_pii`  | sec      | phrases router  | Write rejected by the PII scrubber (`patterns`).     |
| `autocomplete.snippet.created`            | info     | snippets router | Snippet added (`source`, `trigger`).                 |
| `autocomplete.snippet.updated`            | info     | snippets router | Snippet changed (`trigger`).                         |
| `autocomplete.snippet.deleted`            | info     | snippets router | Snippet removed (`trigger`).                         |
| `autocomplete.rollup.completed`           | info     | roll-up job     | Nightly counter roll-up done (`rollup_date`, `phrases_updated`). |

## Adding a new kind

1. Define the constant in `services/<service>/src/<service>/audit_kinds.py`.
2. Use it via `await audit_writer.write_event(kind=audit_kinds.X, ...)`.
3. Add a row to this table.
4. If the kind warrants its own dashboard panel or alert rule, add
   them in `infra/grafana/dashboards/` and `infra/prometheus/rules/`.

### Sprint 12 — notifications

| kind                              | severity | emitter                          | meaning                                                            |
| --------------------------------- | -------- | -------------------------------- | ------------------------------------------------------------------ |
| `notification.materialized`       | info     | notification-service ingest consumer | One event fanned out to N per-recipient rows. Payload: category, event_id, created/coalesced/duplicates counts. |
| `notification.coalesced`          | warn     | notification-service materialize | Storm cap tripped; same-category events folded into one row (E1). |
| `notification.delivered`          | info     | notification-service delivery worker | A channel dispatched successfully. Payload: channel, attempts. |
| `notification.suppressed`         | info     | notification-service materialize | A channel was deliberately NOT dispatched. Payload carries the reason (preference / quiet_hours / no_email_address / digest_deferred) — the auditable proof for E8. |
| `notification.delivery_failed`    | warn     | notification-service delivery worker | An attempt failed and will be retried with backoff. |
| `notification.dead_lettered`      | error    | notification-service delivery worker | Retries exhausted, or a permanently-undeliverable envelope. Someone will never be told something. |
| `notification.read`               | info     | notification-service feed router | User marked a notification read. |
| `notification.preferences_updated`| info     | notification-service preferences router | User changed their own notification preferences. |
| `notification.digest_sent`        | info     | notification-service digest job  | Daily digest email sent. Payload: digest_date, included count. |
| `note.audio_replayed`             | info     | note-service POST /v1/audio-clips | Sprint 15 (ADR-0037) — a replay clip was created. Payload: clip_id, source_kind, start_ms, end_ms, purpose, is_author. |
| `layer_c.completion.shown`        | info     | generation-service shown-audit buffer | Sprint 15 (ADR-0036) — AGGREGATED: one row per tenant per flush interval counting served inline completions. Payload: count. Per-keystroke rows would pollute the chain. |
| `layer_c.completion.filtered`     | warn     | generation-service POST /v1/completions/inline | Sprint 15 — the output safety filter dropped a completion that introduced a numeric value absent from the typed text. Payload: section_key, reason (pattern class), matched (the offending fragment — closed class, never prose), language. |
| `search.expanded`                 | info     | note-service search-audit buffer | Sprint 15 (ADR-0038) — AGGREGATED: one row per tenant per flush interval counting synonym-expanded searches. Payload: count, expanded_terms_total. Never the query text. |
| `synonym.group.created`           | info     | note-service POST /v1/synonyms | Sprint 15 — tenant synonym group added. Payload: group_id, term_count, language. Terms are closed-vocabulary dictionary entries, not prose. |
| `synonym.group.updated`           | info     | note-service PUT /v1/synonyms/{group_id} | Sprint 15 — tenant synonym group replaced. Payload: group_id, term_count, language. |
| `synonym.group.deleted`           | info     | note-service DELETE /v1/synonyms/{group_id} | Sprint 15 — tenant synonym group removed. Payload: group_id. |

## Sprint-16 — KMS, schedulers

| kind | severity | emitter | meaning |
|------|----------|---------|---------|
| `kms.rewrap.completed` | sec | `scripts/kms/rewrap-tenant-keks.py` | one tenant KEK re-wrapped file→Vault (ADR-0011 amendment). Payload: from, to master ids. |
| `scheduler.job.completed` | info | note-/autocomplete-service job loops (ADR-0041) | one scheduler iteration finished; written under the reserved global tenant. Payload: per-job counts. |
| `scheduler.job.failed` | warn | same | an iteration raised; the loop survives and retries next interval. |

## Payload conventions

The `payload` arg to `write_event` is the caller-supplied dict that lands
*inside* the canonicalised event record under the `payload` key. Keep it
shallow (no deeply nested objects) and pre-convert non-JSON types
(UUID → str, datetime → ISO-8601). The writer's `_normalize_payload`
handles UUID/datetime/bytes for you.

Sensitive values (passwords, raw OTP codes, note content, transcript
text) **must not** appear in the payload. Audit is for *who did what
when* — the *what* references IDs, not contents.

## Sprint-13 reconciliation (2026-07-23)

The three typed-field kinds above are all **info**, including
`note.field.overridden` — an override is a quality signal about
the extractor, not a security event, and filing it as `sec` would
dilute the security severity's meaning.

### Deviation: typing-path lookups are metrics-only

Endpoints that sit in a typing path (autocomplete suggest, picker-style
searches) fire on substantially every keystroke; a hash-chained,
append-only row per keystroke is chain pollution that would bury the
meaningful events around it. Such paths are instrumented with metrics
instead, which answer the same operational questions — volume, latency,
zero-result rate — without touching the audit chain. What *is* audited
is the meaningful act of a value entering a note (`note.field.confirmed`
/ `note.field.overridden`). Searching is not the act; choosing is.
