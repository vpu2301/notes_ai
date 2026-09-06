# Sprint 02 Threat Model — Identity, Isolation, Auditability

**Scope:** the auth-service, libs/auth, libs/audit, the Keycloak realm,
and the Postgres tables (`tenants`, `users`, `audit.events`). Other
data planes (Whisper, notes, exports) are out of scope until their
respective sprints.

**Methodology:** STRIDE per data-flow, then a per-property summary.

---

## Trust boundaries

```
[browser] ─https→ [auth-service] ─REST→ [Keycloak] ─JDBC→ [keycloak DB]
                  ↓
                  ↓ asyncpg
                  ↓
            [Postgres /notes/]
                 ├── public.tenants (RLS)
                 ├── public.users   (RLS)
                 └── audit.events   (RLS + immutability trigger + audit_writer role)
```

External: browsers (untrusted), partner systems via service tokens
(semi-trusted, capability-bounded by scopes — sprint 17 enforcement).

Internal: services trust each other within the cluster; the
trust boundary is the Postgres role + RLS combo, not the network.

---

## Identity threats

| Threat                                            | Mitigation                                                                                       |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Forged JWT (no signature)                         | RS256-only allowlist in `libs/auth.verifier`. `alg=none` rejected. Test: `test_alg_none_fails_closed` |
| Algorithm-confusion (HS256 with public key)       | Same — only RS256 alg is accepted from the JWKS                                                  |
| Stolen access token, replay                       | Short-lived (15 min) **plus, since sprint 16, the revocation denylist (ADR-0040)**: logout/deactivation/replay push the sid/sub to Redis and `current_user` rejects it fleet-wide (`MDX_SESSION_REVOCATION_ENABLED`). Fail-open on Redis outage — degraded mode equals the old 15-min window |
| Stolen refresh, replay                            | Rotation on every refresh + Keycloak server-side single-use tracking. Replay → `auth.refresh_replay_detected` audit (sec); sessions force-revoked |
| Refresh cookie exfiltrated by XSS                 | HttpOnly cookie. Sprint-16 frontend adds CSP                                                     |
| CSRF on refresh / logout                          | Refresh cookie path-restricted to `/auth/*`; access token in Authorization header — no double-submit needed |
| Unknown / typo'd `iss` claim                      | `JwksCache` rejects unknown issuers before any HTTP fetch (defence in depth against `iss` confusion) |
| `is_admin: true` injected via misconfigured realm | `Claims.extra="forbid"` — every claim must be enumerated in the model. Test: `test_extra_claim_is_admin_rejected` |
| Clock skew abuse                                  | 30 s leeway, configurable per service                                                            |
| MFA bypass (post-enablement)                      | `requires_mfa()` dep gates admin routes when `MDX_REQUIRE_MFA=true`. Today MFA disabled by pilot policy — risk accepted in writing |

---

## Authorization threats

| Threat                                              | Mitigation                                                                       |
| --------------------------------------------------- | -------------------------------------------------------------------------------- |
| Privilege escalation by adding a role to one's token | Roles come from Keycloak; tokens are signed; `extra="forbid"` rejects unlisted claims |
| Drift between code's authz checks and the matrix    | `docs/auth/permissions.csv` is reviewed; `libs/auth.tests.test_perms` fails CI if CSV / code diverge |
| Forgotten permission check on a new endpoint        | Code review. Sprint-17 adds an AST scanner that asserts every route has a `requires(…)` dep |
| Scope-token caller exceeds intended capability      | Scope-narrowing mechanism wired in Day 7; not yet enforced in sprint 02 (no service tokens issued) |

---

## Isolation threats (RLS)

| Threat                                              | Mitigation                                                                       |
| --------------------------------------------------- | -------------------------------------------------------------------------------- |
| Missing `WHERE tenant_id = ?` in app code           | Not possible — code never filters by `tenant_id`. RLS does                       |
| Future table created without RLS                    | CI gate `check-rls-policies.py` queries `pg_class`, fails on `relrowsecurity=false` or `relforcerowsecurity=false` |
| Future PERMISSIVE policy too loose                  | RESTRICTIVE policy on `users` and `audit.events` enforces tenant match regardless |
| Superuser bypasses RLS                              | `app_role`, `tenant_writer`, `audit_*` are explicitly `NOSUPERUSER`. The `postgres` superuser is never used by service code |
| `pg_dump` exports cross-tenant data                 | Operational: backups encrypted at rest; restore tooling is sprint-16             |
| RLS-policy drift between code and DB                | Property test (`test_rls_isolation.py`) generates 50 random tenant/user layouts × N probes per example; cross-tenant SELECTs must return 0 rows |

---

## Auditability threats

| Threat                                                | Mitigation                                                                       |
| ----------------------------------------------------- | -------------------------------------------------------------------------------- |
| Attacker UPDATEs a row                                | Immutability trigger raises; even superuser is blocked unless trigger is explicitly disabled (logged in pg_log) |
| Attacker DELETEs a row                                | Same — trigger blocks                                                            |
| Attacker disables the trigger, edits, re-enables      | Verifier detects: divergence at the edited seq (or gap on delete). Nightly + alert `AuditChainBroken` |
| Attacker TRUNCATEs the table                          | TRUNCATE bypasses triggers BUT requires DBA privilege. Postgres log + monitoring catches it. Sprint 16 streams events to immutable S3 bucket for the after-fact case |
| Attacker forges a payload_hash that matches their edit | Would also need to rewrite every subsequent row's prev_hash. Verifier walks them all |
| Service code bypasses AuditWriter                     | `audit_writer` is the only role with INSERT permission. CI gate `check-no-direct-audit-insert.py` scans the codebase for `INSERT INTO audit.events` outside libs/audit |
| Audit chain itself becomes a privacy leak             | `payload` carries IDs, never note content or personal data. Catalogue at `docs/audit/event-kinds.md` enforces convention |

---

## Cross-cutting risks (sprint-02 specific)

- **MFA built in sprint 16 (ADR-0039), still off by default in dev.**
  TOTP enrolment endpoints live on auth-service; `requires_mfa()` (with
  the 403 `mfa_enrolment_required` grace flow) guards role management,
  user lifecycle and tenant CRUD.
  Production enables `MDX_MFA_ENROLMENT_ENABLED` + `MDX_REQUIRE_MFA`.
  Residual: the dev-only `mdx-dev-cli` client could reach Keycloak's
  token endpoint directly inside the network, bypassing the proxy OTP
  check — the production realm must not ship it.
- **Dev credentials hard-coded** in `infra/keycloak/realm-export.json`
  (`dev-secret-change-in-prod-*`). Production deployments must
  regenerate every client secret via `kc.sh` import-realm.
- **Session-aware access-token revocation shipped in sprint 16**
  (ADR-0040): logout means logged out when
  `MDX_SESSION_REVOCATION_ENABLED` is on. Completeness rests on the
  invariant that every session-ending path runs through auth-service —
  a Keycloak-console logout does NOT hit the denylist.
- **DBA superuser has unrestricted DB access.** The chain catches
  tampering after-the-fact; we don't prevent it. Operational control:
  DBA action is logged at the Postgres-log level + reviewed weekly.
- **JWKS fetch is HTTP**, not mTLS. Acceptable because the JWKS is
  signed (we verify by the included signature, not the transport). A
  network attacker can't insert a forged JWKS without holding the
  realm's private key.

---

---

## Sprint 04 addendum — Streaming Dictation surface

The streaming surface (sprint 04) adds a long-lived authenticated
connection that holds decrypted audio in worker memory + tmpfs. STRIDE
deltas:

### Threats

- **Spoofing — forged `resume_session_id`**: an attacker who learns
  another tenant's session UUID attempts to resume. *Mitigation:* the
  resume gate checks `(tenant_id, user_id)` against the bearer's
  claims; any mismatch returns the uniform-failure `session_not_found`
  (never `forbidden`) so the attacker can't distinguish
  "wrong tenant" from "stale session". Verified in §2.6 of the sprint
  TODO.

- **Tampering — binary frame DoS**: a misbehaving client sends 16 KB
  frames at 50 fps. *Mitigation:* codec rejects frames > 8 KB with
  `bad_message` and closes the connection. The closure triggers an
  audit row (`dictation.upgrade.failed` if pre-session, `dictation.session.failed`
  if mid-session).

- **Repudiation — finalised transcript altered by an insider**:
  transcripts land in `dictation_sessions.transcript_jsonb` which is
  not append-only. *Mitigation:* every finalize emits an audit row
  whose `payload` carries the segment count and the audio_file_id;
  forensic correlation with the encrypted audio blob detects
  retroactive transcript edits.

- **Information disclosure — plaintext PCM in core dumps**:
  the per-session tmpfs ring is RAM-backed but a coredump that flushes
  process pages to disk would expose it. *Mitigation:* the ring is
  encrypted with a per-session AES-CTR DEK; the DEK is in process
  memory only (never persisted); on session-end the file is
  unlinked + zero-overwritten.

- **Information disclosure — pre-signed URL leak**: not applicable to
  the live stream (no pre-signed URLs are issued during a session);
  finalize uses `EncryptedObjectStore.put` which doesn't emit URLs.

- **Information disclosure — audit payload of a PII-bearing message**:
  audit payloads never include audio bytes or transcript text. The
  payload fields are limited to IDs and metadata; the spec is enforced
  by code review.

- **Denial of service — slow-loris on WS upgrade**: an attacker opens
  many WS connections, never sends a `start_session`. *Mitigation:* a
  10-second deadline on the first message; per-IP (10/min) and per-user
  (30/hr) upgrade rate limits backed by Redis counters.

- **Denial of service — 1000 idle resumes**: similar to slow-loris but
  post-`session_started`. *Mitigation:* the 35-s idle watchdog closes
  silent connections; the 30-min abandon timer reclaims resources for
  any unrecovered session. Tenant-level cap (10 active per tenant)
  prevents a single tenant from monopolising the worker.

- **Elevation of privilege — `extra` field in client message**: an
  attacker sends `{"type":"start_session", "is_admin":true, ...}`.
  *Mitigation:* every Pydantic model uses `extra="forbid"`; the codec
  rejects the frame with `bad_message`.

### Tmpfs hygiene

The `/run/dictation/<session_id>/` directory is created with mode 0700
at session start; the file inside is mode 0600; both are deleted on any
termination path. The buffer's `assert_mode()` helper is callable from a
runbook check.

### Cross-Site WebSocket Hijacking

CSWH would only apply if we used cookie auth on the WS upgrade. We
require `Authorization: Bearer …` (or `?token=` query param), which the
browser does NOT auto-attach to cross-origin requests. The `Origin`
header is additionally validated against the allow-list in prod.

---

## IDX addendum — the native identity platform

What changed when identity moved out of Keycloak (sprints A2, A3, A5,
B1b, B2, B3). Only the deltas; the sprint-02 tables above still hold.

### Trust boundary changes

| Before | After | Consequence |
| --- | --- | --- |
| Keycloak minted tokens; auth-service proxied | auth-service signs RS256 itself | The signing key is now **our** highest-value secret. Compromise mints any identity in any workspace. Rotation: `docs/runbooks/idx-secrets.md` |
| Keycloak stored credentials | `identities`, `identity_totp`, `service_credential_secrets` | Credential material is in our database. `app_role` — what every product service connects as — is granted nothing on any of it, enforced by `check-identity-grants.py` |
| Keycloak's brute-force detector | DB-backed lockout on `identities` | Survives a Redis restart, which the cache-based alternative would not |
| Room devices were Keycloak clients | `service_credentials`, `POST /auth/oauth/token` | The old form never worked: a Keycloak device token is rejected by `libs/auth.Claims`. See IDX-B1b |

### New assets

| Asset | Store | Protection |
| --- | --- | --- |
| Signing keys | secrets manager | Never on disk in prod; overlap rotation; JWKS publishes public halves only, asserted by test |
| TOTP secrets | `identity_totp.secret_enc` | `libs/crypto` envelope, AAD bound to the identity — a blob moved to another row fails to decrypt |
| Recovery codes | `identity_recovery_codes` | sha256 only, single-use, claimed by conditional UPDATE |
| Device secrets | `service_credential_secrets` | sha256 of a 256-bit random; **no KDF** — full-entropy input has no dictionary to stretch against |
| One-time codes | `auth_challenges.code_hash` | `sha256("<code>:<challenge_id>")`, so a leaked hash fits one challenge |
| Sessions | `auth_sessions` | Refresh token stored as sha256; revocation is DB row **plus** denylist |

### New threats, and what answers them

| Threat | Answer |
| --- | --- |
| **S** — forge a token | RS256 pinned before decode; `alg=none` and HS256-with-public-key both rejected (8.1/8.2 in the pen-test checklist) |
| **S** — enumerate accounts via the sign-in endpoint | Uniform 202: same work, same body, for known and unknown addresses. Two accepted residuals, both documented |
| **S** — brute-force a 6-digit code | 5 attempts per challenge, one live code per address, per-email and per-IP caps, then a DB-backed lockout |
| **S** — replay a TOTP code inside its drift window | Time step claimed with a strictly-greater-than guard; the same code cannot authenticate twice |
| **S** — guess a device secret | 256-bit random, 60/min per client, locked for 15 min after 10 failures — **fail-closed**, the one control where availability yields |
| **T** — alter the audit trail | Unchanged: hash-chained, verified nightly |
| **R** — deny an action | Every credential change, revocation and lockout writes a `sec` audit row. A *successful* device token grant deliberately does not (96/day/room would bury the trail) |
| **I** — read another workspace's people | `profile_of_subs` returns rows only for subs sharing an active membership with the caller's tenant; unscoped connections get nothing |
| **I** — a leaked service token reads customer data | Service credentials mint against the platform tenant, which owns none |
| **D** — lock everyone out via the lockout | Lockout is per identity; the sign-in caps are per address and per IP |
| **E** — admin escalates to owner | An admin cannot reset an **owner's** second factor; only another owner can |
| **E** — a room device acts as a user | `device` is capture-only, fixed per kind by a CHECK constraint; `tid` comes from the row, never the request |

### Accepted residual risks

1. **Timing on a locked, already-notified account.** It answers faster
   because it sends no mail. Reaching that state costs ten failures
   against an account you must already know exists.
2. **`email_in_use` on email change is explicit.** The caller is
   authenticated, so it is not an oracle; hiding it would fail later with
   nothing the user could act on.
3. **The denylist is fail-open** (ADR-0040). A Redis outage shortens
   revocation from "immediate" to "within the access-token lifetime".
   Alerted as critical (`DenylistPushFailed`).
4. **No single-instance lock on maintenance** (ADR-0041). Jobs are
   idempotent; concurrent runs are redundant, not harmful.

### Still open — do not treat as covered

Password login and its hashing parameters (IDX-A4), refresh rotation and
replay detection (IDX-A2's remaining half), invitations (IDX-B1), and the
removal of Keycloak itself (IDX-B2). Until those land, Keycloak is still
in the request path and its own threat surface still applies.

## Excluded by scope

- Network-layer attacks (DDoS, BGP hijack) — handled by the cloud
  perimeter, not application code.
- Side-channel attacks on the IdP host (e.g. memory dumps reading the
  signing key) — operational concern.
- Insider threat from a developer with prod database access —
  partially mitigated by the audit chain, but a determined insider
  with both DBA + service-account access can do significant damage.
  Operational control: least-privilege + 2-person review on prod data
  ops, not enforced by sprint 02 code.
