# Runbook — Auth & Audit (Sprint 02; user-CRUD entries added in CRUD-by-role)

Scope: incident-response procedures for the auth-service, libs/audit,
the Keycloak realm, and the audit chain. Each section opens with a
*signal* (what alert or symptom triggers this entry) and ends with the
recovery state you're aiming for.

The tenant-admin user-management surface these procedures call is:
`GET /admin/users`, `GET /admin/users/{sub}`, `POST /admin/users/invite`,
`POST /admin/users/{sub}/deactivate`, `POST /admin/users/{sub}/reactivate`,
and `PUT /admin/users/{sub}/roles`. All are RLS-scoped to the caller's
tenant (a cross-tenant `sub` returns 404, never an existence leak) and
emit `sec`-severity audit events. The full role × action matrix lives in
`docs/auth/permissions.csv`; the prose companion is `docs/auth/roles.md`.

---

## Keycloak outage

**Signal:** `/healthz` of auth-service returns 200 but `/auth/login`
returns 503; `JwksCacheHitRatioLow` may eventually fire as the JWKS
cache expires.

**Behaviour during outage (steady state):**
- Existing access tokens (≤15 min lifespan) continue to verify against
  the JwksCache. Users mid-session are unaffected.
- New logins fail with HTTP 503 from `/auth/login` (Keycloak's token
  endpoint unreachable). The frontend retries.
- Refresh-token rotation fails the same way. After ~15 min of outage,
  the JWKS cache may expire; from that point every verify also fails.

**Recovery:**
1. Restart the Keycloak container (`docker compose restart keycloak`).
   Confirm `/realms/notes/.well-known/openid-configuration`
   responds 200.
2. Watch `mdx_jwks_refresh_attempts_total` climb — services will
   re-prime their caches naturally on the first verify.
3. No data action required; the audit chain is unaffected (it doesn't
   touch Keycloak).

---

## MFA reset for a locked-out user

**Signal:** A user calls support saying they've lost their phone /
authenticator. (Applies when MFA is on: `MDX_MFA_ENROLMENT_ENABLED` +
`MDX_REQUIRE_MFA=true` — ADR-0039.)

**Steps:**
1. Verify the user's identity by an out-of-band channel. **Do not** do
   this over chat.
2. As a `tenant_admin` for the user's tenant, call:
   ```
   DELETE /auth/mfa/{sub}
   ```
   This wipes the envelope-encrypted TOTP attributes, clears
   `users.mfa_enrolled_at`, and revokes the user's live Keycloak
   sessions (a reset without revocation would leave a live `mfa=true`
   session usable by whoever holds it).
3. Audit row appears under `kind=user.reset_mfa`, severity `sec`.
4. Tell the user to log in (password only works again) and re-enrol:
   `POST /auth/mfa/enrol` → scan the QR → `POST /auth/mfa/verify`.

**Enrolment support notes:** an enrolled user's login needs the `otp`
field — the SPA shows the code prompt on the 401 `otp_required` machine
code; `otp_invalid` is a wrong code; `otp_unavailable` means the secret
store (master key / Vault) is down — check `docs/runbooks/kms.md`, the
login fails CLOSED on purpose.

---

## Session revocation (sprint 16, ADR-0040)

With `MDX_SESSION_REVOCATION_ENABLED=true` (fleet-wide env), logout /
deactivation / refresh-replay push the token's `sid` (or the user's
`sub`) onto the Redis denylist, and every service's `current_user`
rejects denylisted tokens — logout means logged out immediately, not
after 15 minutes.

- **Kill one user's access now:** `POST /admin/users/{sub}/deactivate`
  (pushes the sub-level deny). Reactivation clears it.
- **Redis down?** Checks fail OPEN with a
  `session_denylist.check_failed_fail_open` WARNING — the fleet
  degrades to the pre-sprint-16 15-minute window, never worse. Restore
  Redis; nothing to replay.
- **Caveat:** a logout performed in the Keycloak admin console does NOT
  hit the denylist — use the platform API.

---

## Restoring a deactivated user (reactivation)

**Signal:** A user reports they can no longer log in, and the audit log
shows a `kind=user.deactivated` event for their `sub` — either an
accidental deactivation or one done during a token-theft investigation
that is now closed.

**Steps:**
1. Confirm the user *should* regain access (investigation closed / the
   deactivation was a mistake). Verify identity out-of-band for the
   latter.
2. As a `tenant_admin` for the user's tenant, call:
   ```
   POST /admin/users/{sub}/reactivate
   ```
   This flips `users.status` back to `active` and re-enables the account
   in Keycloak. It is the exact mirror of `/deactivate`.
3. An audit row appears under `kind=user.reactivated`, severity `sec`.
4. The user can log in immediately. (Reactivation does **not** restore
   the old sessions revoked at deactivation — they log in fresh.)

**Recovery state:** user `active` in both Postgres and Keycloak; a
`user.deactivated` → `user.reactivated` pair is visible in the audit
trail for the tenant.

---

## Forcing immediate role revocation / change

**Signal:** A user's privileges must change *now* — over-provisioned
account, role granted in error, or a need-to-know change.

**Steps:**
1. As a `tenant_admin`, set the user's full realm-role set:
   ```
   PUT /admin/users/{sub}/roles      body: {"roles": ["member"]}
   ```
   Unknown roles are rejected (422). The endpoint **refuses (409)** to
   strip `tenant_admin` from the *last* active tenant_admin of a tenant,
   so you can never lock a tenant out of its own administration — add a
   second admin first, then demote.
2. The change sets the role set in Keycloak (diffing add/remove within
   the managed app-role universe; built-in Keycloak roles are left
   untouched) and mirrors the highest-privilege role into the local
   `users.role` column.
3. An audit row appears under `kind=user.role_changed`, severity `sec`,
   with the `old_roles → new_roles` set in the payload.
4. **Propagation caveat:** existing access tokens keep their old roles
   until they expire (≤15 min). The new role set is carried on the next
   refresh. For *immediate* hard revocation (suspected compromise, not
   just a routine demotion), `POST /admin/users/{sub}/deactivate`
   instead — it calls `/logout` and kills active + refresh sessions at
   once.

**Recovery state:** Keycloak role set and `users.role` agree; the
`user.role_changed` event records the transition.

---

## Suspected token theft (refresh-replay alert fired)

**Signal:** `RefreshReplayDetected` alert. The audit log contains a
`kind=auth.refresh_replay_detected` event under the affected tenant.

**Steps:**
1. The auth-service has already attempted to force-revoke the user's
   sessions on detection. Verify in the audit log:
   - Look for `kind=auth.refresh_replay_detected` (tenant_id of the user).
   - The payload's `actor_sub` field carries the user's UUID (extracted
     from the replayed token's unverified claims — adequate for forensics
     since the row + the Postgres log + Keycloak sessions all
     corroborate).
2. As `tenant_admin`, deactivate the user pending investigation:
   ```
   POST /admin/users/{sub}/deactivate
   ```
3. Pull the Keycloak event log for the affected user:
   ```
   GET /admin/realms/notes/events?user={sub}
   ```
   Look for unusual IPs, user agents, or geolocations.
4. If the user can be reached, ask them to confirm whether they've
   recently used the application from a new device / network. A
   client-side bug that re-sends an old refresh after rotation
   sometimes triggers this alert legitimately.
5. Post-incident: write the timeline into a sec-ops doc; preserve the
   Postgres log for 30 days.

---

## Audit chain divergence (`AuditChainBroken` alert)

**Signal:** `min(mdx_audit_chain_ok) == 0`, or the nightly verifier
exits non-zero. **This is a critical security event.**

**Steps:**
1. **Do not** attempt to "fix" the chain. The divergence row is
   forensic evidence.
2. Identify the affected tenant from the Prometheus gauge:
   ```promql
   mdx_audit_chain_ok == 0
   ```
3. Run `make nightly-verify` manually to confirm and get the exact
   divergence seq:
   ```
   /admin/audit/verify?from_seq=1     (via the auth-service API)
   ```
4. The verifier returns `first_divergence_seq` + `divergence_reason`
   (one of `gap`, `prev_hash_mismatch`, `payload_hash_mismatch`).
5. Check the Postgres logs around the time of the divergence:
   - `SELECT … FROM pg_stat_activity` — who held what connection
   - `pg_audit` extension logs if enabled
   - container-level docker logs for the postgres image
6. If the attacker disabled the immutability trigger to perform the
   edit, the Postgres logs show the `ALTER TABLE … DISABLE TRIGGER`
   statement.
7. Page the security lead. Preserve all logs before any recovery
   action. The chain itself is irreparable — the divergence is
   permanent and that's by design.

---

## JWKS rotation (planned)

**Signal:** Keycloak realm admin rotated the realm signing key.

**Behaviour:**
- libs/auth's JwksCache caches by `kid`. A new token with a new `kid`
  triggers a miss → refresh → cache update. The rate-limit prevents a
  storm of refreshes from forged-`kid` attacks.
- Old tokens (signed by the previous key, still in the JWKS as long as
  Keycloak retains it) continue to verify.

**Action:** none required for routine rotation. If the rotation is
forced because the old key is suspected compromised, also revoke all
active sessions for the realm: `kc.sh import --override` resets keys
and sessions on next start.

---

## Brute-force from a single IP

**Signal:** `LoginFailureBurst` alert. Per-IP source visible in
auth-service logs (`username_hash` is hashed; IP comes from the
reverse-proxy header).

**Steps:**
1. Confirm Keycloak's per-account lockout has kicked in (5 fails / 60s).
   The attacker is now rate-limited per username they're trying.
2. If the attempt is concentrated on one IP, escalate to the network
   team for an upstream block (load balancer / WAF rule).
3. If multiple IPs (distributed attack), increase Keycloak's
   `quickLoginCheckMilliSeconds` (already 1000 ms in dev) and consider
   enabling Keycloak's CAPTCHA flow.
4. Don't rotate signing keys — this is a guessing attack, not a key
   compromise.

---

## auth-service crash / restart

**Signal:** auth-service `/healthz` returns 5xx, `/readyz` fails, or
the container is in CrashLoopBackOff.

**Recovery:**
1. `docker compose logs auth-service --tail 200` for the last
   exception. Common: DB pool exhausted (visible as asyncpg connect
   timeouts), Keycloak unreachable (HTTPx connect errors).
2. Restart the service. The lifespan re-builds all pools + the JWKS
   cache. Cold start is ~3 s.
3. No data action — service is stateless.

---

## Cookie audit (compliance check)

Set-Cookie attributes for `mdx_rt` must be:

```
HttpOnly; Secure; SameSite=Strict; Path=/auth
```

In dev (`AUTH_COOKIE_SECURE=false`) the Secure flag is intentionally
off so cookies work over http://localhost. Staging and production MUST
set `AUTH_COOKIE_SECURE=true` in their env file. Verify with:

```
curl -i -X POST http://staging.example/auth/login -d '…' | grep -i set-cookie
```

The cookie must have `Secure` in staging/prod or treat as a P0 incident.

---

# Alert response

One section per alert in `infra/prometheus/rules/auth-audit.yml`. The
`runbook:` annotation on each rule links here by anchor, and
`services/auth-service/tests/unit/test_alert_rules.py` fails if a rule
points at a heading that does not exist — a link into nothing sends
whoever is paged at 3am to the top of a long document to search.

## Login failure burst

**Fires:** aggregate login failures over 5/s for a minute.

Aggregate, not per-account: one account being hammered is handled by the
per-identity lockout (IDX-A3 F5, ten failures then fifteen minutes,
doubling). This fires when many accounts are being tried, which lockout
does not stop.

1. `mdx_auth_login_total{result}` — which failure kind dominates.
2. Audit, platform tenant: `auth.otp_failed`, `auth.login_failed`. Group
   by `ip_hash`. One address is a script; thousands is a botnet.
3. One source → block at the edge. Spread → confirm the per-email and
   per-IP caps are actually engaged (`OtpStartRateLimitedBurst` should be
   firing too; if it is not, check Redis).
4. Do **not** relax the caps to reduce the noise.

## Refresh replay

**Fires:** any refresh-token replay. Critical.

A rotated refresh token presented after its grace window means the token
was captured. The session is already revoked and the account's tokens
denylisted; this is notification, not a decision.

1. Identify the identity from the audit row.
2. Check `GET /auth/sessions` for that identity — anything unfamiliar.
3. Ask them to change their email password and re-enrol MFA.
4. If several accounts fire together, treat as a token-store compromise.

## Chain divergence

**Fires:** `mdx_audit_chain_ok == 0` for a tenant.

The hash chain no longer verifies: an audit row was altered or deleted.
Treat as an integrity incident, not a bug.

1. Do not write to the audit tables.
2. `GET /auth/audit/verify` for the tenant — note the first bad `seq`.
3. Preserve a backup from before the divergence.
4. Escalate to the security lead. Chain divergence is a reportable event.

## OTP verify failures

**Fires:** over 30% of `/auth/email/verify` attempts failing for 10 min.

A code is six digits, five attempts and ten minutes, so a sustained rate
this high is not people mistyping.

1. `mdx_auth_otp_verify_total{result}` — `invalid` means guessing;
   `expired` usually means a slow mail relay (check
   `mdx_auth_email_send_seconds`); `consumed` means a client
   double-submitting, which is a client bug, not an attack.
2. If `invalid` dominates, check `AccountLockoutBurst` and the
   `auth.otp_failed` audit rows for a concentration of `challenge_id`s.

## OTP start rate limited

**Fires:** over 1/s of `/auth/email/start` refused for 5 min.

The caps are working. This is the signal that they are being exercised.

1. Group `auth.otp_requested` by `ip_hash` — one sweeper or many.
2. Confirm the per-email cap is engaged as well; a sweep across many
   addresses only trips the per-IP one.
3. If a legitimate customer is tripping it (a shared NAT), raise
   `AUTH_OTP_START_IP_LIMIT` for that deployment rather than globally.

## Account lockout burst

**Fires:** more than 20 challenges exhausted in 10 minutes.

Each exhaustion is five wrong codes against one challenge, and counts
toward that identity's lockout.

1. `auth.account_locked` (sec) audit rows — how many distinct identities.
2. One identity, many locks → targeted; tell the account holder.
3. Many identities → credential stuffing against a leaked address list.
   The lockout holds; consider tightening `AUTH_OTP_START_EMAIL_LIMIT`.

## Denylist push failed

**Fires:** a revocation did not reach Redis. **Critical.**

Revocation has two halves. The database row stops the next refresh
immediately; the denylist stops the access token already in someone's
hands. When the push fails, a revoked session keeps working for up to
`AUTH_ACCESS_TTL_SECONDS` (15 min by default).

1. Check Redis reachability from auth-service.
2. Until healthy, treat every logout, MFA disable, device revoke and
   account deletion as taking up to 15 minutes to bite. Say so to anyone
   who asks for an urgent revocation.
3. If the revocation was urgent (suspected compromise), shorten the
   window by restarting the affected services after Redis recovers.
4. This is fail-open by design (ADR-0040) — availability over the
   residual window. It is not a bug to fix under pressure.

## Maintenance stale

**Fires:** a job has not succeeded in 3 hours.

The longest scheduled interval is hourly, so this is three missed runs.

1. `mdx_scheduler_job_runs_total{job_name,outcome}` — running and failing, or
   not running at all?
2. Not running: is `MDX_BACKGROUND_JOBS` true, and is a replica up? The
   jobs are hosted in-process, so a scaled-to-zero deployment has no
   scheduler.
3. Failing: the `scheduler.job.failed` audit row (platform tenant)
   carries the exception.
4. Either way, run it by hand — same code path, same effect:
   `python -m auth_service.maintenance <job>`.
5. Nothing here is urgent on its own. The consequence of a long outage is
   growth in `auth_challenges` and a delayed account purge, which is a
   GDPR commitment worth watching but not a page.

## Email send failures

**Fires:** more than 5 account emails failed in 5 minutes.

Sign-in codes are sent **inline**, so a failing relay is a failing
sign-in: `/auth/email/start` answers 503 and deletes the challenge.

1. `mdx_auth_email_send_failed_total{template}` — every template, or one?
2. Check the SMTP relay and its credentials.
3. Users see "the code could not be sent". There is no queue to drain and
   nothing to replay; they retry once the relay is back.

## MFA verify failures

**Fires:** more than 20 second-factor failures in 10 minutes.

Includes **replayed** TOTP codes — a code whose time step was already
spent — which is the signature of a code being reused from a phished
page rather than a user mistyping.

1. Grep for `auth.mfa.code_replayed` in the logs; it carries
   `identity_id` and nothing else.
2. Replays concentrated on one identity → contact them; a phishing page
   that captured a code is trying to use it a second time.
3. Spread evenly → more likely clock drift on a client fleet. The window
   is ±1 step (±30s).

## Recovery code spike

**Fires:** more than 5 recovery codes used in an hour.

A recovery code is the credential people keep on paper.

1. `auth.mfa.recovery_code_used` (sec) rows — distinct identities.
2. One identity burning several → they lost their device; help them
   re-enrol and regenerate.
3. Many identities → a stolen printout or a leaked export. Force
   regeneration and treat as a credential compromise.

## JWKS cache hit ratio

**Fires:** below 90% for 10 minutes.

Every miss is an HTTP fetch on the request path. In native mode the JWKS
is served in-process, so a low ratio here means a service is still
pointed at an external issuer.

1. Check `AUTH_JWKS_URL` on the complaining service.
2. A burst of misses right after a key rotation is expected and settles
   within the cache TTL (300s).

## Chain verify stale

**Fires:** the nightly audit-chain verifier has not reported in over a day.

The verifier is a textfile exporter (`scripts/jobs/nightly_verify.py`),
not a service, so this alert is about the *job*, not the chain. A stale
result is not a divergence — it is the absence of evidence either way.

1. Check the job's last run and its exit code.
2. Run it by hand for the affected tenant; a fresh
   `mdx_audit_chain_ok` clears the alert.
3. If it cannot complete, treat the chain as unverified until it can —
   do not assume health from a green `ChainDivergence`, which also
   depends on this series.

## Audit write slow

**Fires:** audit writes are taking longer than the threshold.

Every security-relevant action writes a hash-chained row, and the chain
serialises per tenant — a slow write shows up as latency on login, MFA
changes and revocations, not just on the audit table.

1. Check database CPU and lock waits on `audit.events`.
2. A single tenant with a very deep chain is the usual cause.
3. Audit writes are best-effort at every call site, so the user-facing
   effect is latency, not failure — but a sustained slowdown means rows
   are being dropped, which is a gap in the trail.

## Signup (BE-0)

Self-serve signup is on when `MDX_SIGNUP_ENABLED=true` and the deployment
has a mail relay and Redis. `MDX_IDP_MODE` must be `keycloak` or `dual`;
in `native` the routes are not mounted at all.

### "I signed up and never got the code"

In order, because each step rules out the next:

1. **Was the mail attempted?** `mdx_auth_email_send_total{kind=signup_verify}`
   on the First Account dashboard. No increment means signup did not reach
   the mailer — check `mdx_auth_signup_total{result}`: `rate_limited`,
   `policy` and `unavailable` all end the request before any mail.
2. **Did the relay accept it?** `result=failed` on the same counter, and
   `auth.mail.send_failed` in the logs with `template=signup_verify`.
3. **Did the provider suppress it?** Check the provider's suppression
   list for the address — a previous bounce or complaint silently drops
   everything afterwards, and this is the single most common cause of
   "the mail never arrived" once the code is working.
4. **Was it the other mail?** If the address already had an account they
   received `signup_exists` (subject "You already have a Notes AI
   account"), not a code. That is by design — `/auth/signup` cannot say
   so in its response without becoming a membership oracle. Tell them to
   sign in or use "Forgot password?".
5. **Resend.** `POST /auth/signup/resend` — 3/hour per address. It
   supersedes the previous code, so the old one stops working.

Never read a code out of the database to give somebody: `auth_challenges`
stores `sha256("<code>:<row id>")`, so there is nothing to read, and that
is deliberate.

### "I confirmed but I still cannot sign in"

`403 email_not_verified` after a successful confirmation means the
database says `active` and Keycloak still says disabled — the `verify`
call updated one and not the other.

```
# What Keycloak thinks
python - <<'PY'
import asyncio
from auth_service.main_deps import build_state
async def m():
    s = await build_state()
    async with s.tenant_writer_pool.acquire() as c:
        sub = await c.fetchval("SELECT id FROM identities WHERE email=$1", "PERSON@EXAMPLE")
    print(await s.keycloak.get_user(sub))
asyncio.run(m())
PY
```

Look at `enabled` and `emailVerified`. If either is false, the fix is for
the person to submit their code again — `verify` is idempotent, and it
calls Keycloak **before** consuming the challenge precisely so a retry is
possible. If their challenge is spent, `POST /auth/signup/resend` first.

Do not enable the user in the Keycloak console. It works, and it leaves
the two stores agreeing by coincidence rather than by the code path;
the next person hits the same bug and nobody knows it recurred.

### "Login says my account is not fully set up"

`423` with "Account is not fully set up" from Keycloak means a pending
required action **or an incomplete user profile**. The second one is the
one that bites: the realm's declarative user profile marks `firstName`
and `lastName` required, and a user with an empty `lastName` gets
`VERIFY_PROFILE` demanded at authentication time while their record still
shows `requiredActions: []`. `split_display_name` in `keycloak_client.py`
is what prevents it — a single-word name is written to both fields.

The related failure is a token with **no `tid` claim**, which every
service rejects as malformed. `tenant_id` is an unmanaged attribute unless
the realm's user profile declares it, and Keycloak silently drops
undeclared attributes on admin-API writes. The declaration lives in the
`components → org.keycloak.userprofile.UserProfileProvider` block of
`infra/keycloak/realm-export.json`. Check the running realm with:

```
GET /admin/realms/notes/users/profile      # attributes[] must list tenant_id
```

Realm *import* bypasses the profile, so the seeded dev users work whether
or not it is declared — which is why this stays invisible until somebody
creates a user at runtime.

### Stuck `invited` accounts

An account that was never confirmed keeps its address reserved forever.

```
python -m auth_service.ops.cleanup_invited --dry-run          # what would go
python -m auth_service.ops.cleanup_invited --yes              # 30 days+
python -m auth_service.ops.cleanup_invited --older-than-days 7 --yes
```

Removes the Keycloak user, the `users` row, the membership and the empty
personal workspace. Only `email_verified_at IS NULL` identities; an active
account is never touched whatever its age, and a team workspace with other
members in it is never deleted. `--yes` is required — without it the
command is a dry run, because deleting accounts should not happen because
a flag was forgotten.

### Half-created accounts

There should be none: a database failure after the Keycloak user exists
deletes it (`mdx_auth_signup_total{result=compensated}`). A non-zero
reconciliation count is a bug, not a state:

```sql
-- identities with no Keycloak user, and vice versa, are found by
-- comparing this list against GET /admin/realms/notes/users
SELECT id, email, created_at FROM identities
 WHERE legacy_idp = true AND email_verified_at IS NULL
 ORDER BY created_at DESC LIMIT 50;
```

If `auth.signup.compensation_failed` appears in the logs, the Keycloak
delete itself failed and there **is** an orphan: delete that user in the
console, and open an issue — the compensation path is meant to be the one
thing that always works.

## Self-serve signup: the conversion step (Sprint 21, ADR-0048)

`POST /auth/signup` (BE-0) now records the plan and where the account
came from: every self-serve tenant is `plan = 'free'`,
`signup_source = 'self_serve'` or `'referral'` (a `ref` from a shared
note's CTA), with `plan_limits` recorded from `MDX_SIGNUP_FREE_LIMITS`
and **not enforced**. `GET /auth/signup/config` tells the SPA whether
signup is on; `/join` shows the signup form or the Sprint 19 lead form
accordingly.

**"A referral never got attributed."** Attribution is two writes: signup
inserts `referrals (ref_code, referred_sub)`; verify stamps
`referred_tenant_id`. If the second is missing the person never spent
the code — `SELECT * FROM referrals WHERE referred_tenant_id IS NULL AND
referred_sub IS NOT NULL` lists them; `auth_challenges` (kind
`signup_verify`) shows whether a code is still open. The audit line
`auth.email_verified` carries `ref_present`.

**"Signups from a domain never arrive."** The domain is on the
disposable list (bundled in `domain/disposable_domains.py`, extended by
`MDX_DISPOSABLE_DOMAINS_FILE`). Those answer 202 and create nothing, by
design; the counter `mdx_auth_signup_total{result="disposable"}` shows
how often.

**"Signup feels slow."** `AUTH_SIGNUP_MIN_RESPONSE_MS` (300) is a floor
on every branch of `/auth/signup`, so timing cannot tell a taken address
from a new one. Lower it only with a reason.

**Erasing a stuck signup.** BE-0's rules apply: an account that never
verified is a Keycloak user (disabled) plus rows in `tenants`,
`tenant_memberships`, `identities`, `users` and — if referred — one
`referrals` row keyed by `referred_sub`. `scripts/ops/erase_lead.py`
covers lead rows only; delete the referral row by `referred_sub` when
purging the identity.

**Funnel.** `scripts/ops/loop_funnel.sql` produces the cohort table
(links viewed → CTA → signup → verified → first finalized note) from the
audit and referral tables; run it against a read replica, not the app
role.
