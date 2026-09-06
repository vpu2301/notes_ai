# Runbook — secrets inventory & rotation (identity platform)

Every secret the native identity platform depends on, where it lives, and
how to change it without an outage. If a secret is not in this table, it
either does not exist or nobody owns it — both are bugs.

## Inventory

| Secret | Where | Blast radius if leaked | Rotation |
| --- | --- | --- | --- |
| `AUTH_SIGNING_KEYS_JSON` | secrets manager → env | **Total.** Anyone holding it can mint a token for any identity in any workspace. | Overlap (below) |
| Master key (`MDX_MASTER_KEY_PATH` / Vault transit) | mounted file or Vault | Every TOTP secret in the estate becomes decryptable | Overlap + re-key (below) |
| `service_credential_secrets` (per device/service) | database, sha256 only | One room's recordings | `POST .../rotate`, 24 h overlap |
| DB DSNs per role | secrets manager | Role-scoped; `tenant_writer` reaches every identity table | Standard credential rotation |
| SMTP credentials | secrets manager | Outbound mail as us — phishing with our domain | Provider-side |
| `MDX_PASSWORD_RESET_IP_HASH_SALT` | secrets manager | Stored IP hashes become reversible (the address space is small) | Standard; old hashes stay unreadable |
| `infra/dev/auth-signing-dev.json`, `infra/dev/master.key` | **in the repository, deliberately** | None — dev only | Never used outside dev; `check-dev-keys.py` fails CI if they appear in an image |

**Removed by IDX-B2:** the Keycloak client secrets (`mdx-backend`,
`mdx-admin`, `mdx-asr-worker`, `mdx-dictation`, `room-device-demo`) and
`KEYCLOAK_ADMIN_PASSWORD`. They are still live today because B2's removal
half is gated — delete them from every store on the commit that removes
Keycloak, and record the deletions in the sprint log.

> The pack lists `AUTH_SECRETS_KEKS_JSON`. It does not exist: IDX-A5
> reused the existing `libs/crypto` envelope rather than introducing a
> second key hierarchy, so identity secrets are wrapped under the
> platform tenant's KEK, which is wrapped by the environment master key.
> "Rotate the KEK" therefore means "re-key through the envelope" — see
> below.

## Rotating the signing key

The JWKS publishes a retired key until its tokens can no longer be
valid, so this is a zero-downtime overlap, not a cutover.

1. `uv run python scripts/ops/gen-signing-key.py --list` — new entry with
   a `not_after` further out than the current one.
2. Append it to `AUTH_SIGNING_KEYS_JSON` (keep the old entry) and deploy.
   The furthest-out key that is still ahead becomes active immediately;
   the old one keeps being published so tokens already issued still
   verify.
3. Wait for `old not_after + AUTH_ACCESS_TTL_SECONDS`. Every token signed
   by the old key has expired.
4. Remove the old entry and deploy.

Check the state at any time with
`python -m auth_service.maintenance signing-key-status`, which also runs
daily and warns when the active key is within 30 days of expiry.

**Never remove the old key in the same deploy as adding the new one.**
Every token in flight was signed by it, and the JWKS is what services
check against.

## Rotating the master key / re-keying TOTP secrets

1. Add the new master key alongside the old (the provider supports a
   composite for exactly this).
2. Deploy.
3. `uv run python scripts/ops/idx-rekey-totp-secrets.py --dry-run` — it
   reports how many rows decrypt cleanly and how many do not.
4. **If any row cannot be decrypted, stop.** That user needs an admin MFA
   reset (`DELETE /auth/mfa/{sub}`), not a re-key. Re-keying skips them
   and they stay unreadable.
5. `--apply`. Every row is re-wrapped under the current keys.
6. Remove the old master key only after step 5 reports zero failures.

## Rotating a device or service secret

See `docs/runbooks/ambient-device.md#rotate`. The short version: rotation
issues a **second** live secret and puts a 24-hour clock on the old one,
so a room is re-keyed by deploying the new secret whenever somebody is
next in the room. Rotation deliberately does not revoke — a rotation that
takes the room offline the moment the button is pressed is a rotation
nobody performs.

## Where TLS-dependent settings live

Not in the application, and this is deliberate — an app-set header on a
response that arrived over plain HTTP is ignored by browsers and
misleading to whoever reads the code.

| Setting | Where | Verify |
| --- | --- | --- |
| HSTS | TLS terminator (ingress) | `curl -sI https://auth.example.com/healthz \| grep -i strict-transport` |
| TLS version / ciphers | terminator | ditto |
| `Secure` on `mdx_rt` | `AUTH_COOKIE_SECURE=true` in prod config | `curl -sI … \| grep -i set-cookie` |
| `SameSite` | `AUTH_COOKIE_SAMESITE` (`lax`; `none`+Secure only if cross-site) | ditto |

What auth-service *does* set, on every response:
`X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
`Cache-Control: no-store` on `/auth/*` and `/admin/*` (the JWKS keeps its
own `public, max-age=300` — it is a public key), and a
`default-src 'none'` CSP plus `X-Frame-Options: DENY` on the HTML pages.
Asserted in `tests/unit/test_security_headers.py`.

## If a secret leaks

1. **Signing key** — rotate immediately (add new, deploy, remove old in
   the same window rather than waiting out the overlap; accept that
   in-flight tokens break). Then revoke every session:
   `UPDATE auth_sessions SET revoked_at = now()` and let the denylist
   catch the access tokens.
2. **Master key** — re-key as above, then treat every TOTP secret as
   compromised: force re-enrolment.
3. **A device secret** — `DELETE /tenants/{ws}/devices/{id}`. Immediate:
   the row stops the next grant and the denylist stops the live token.
4. **A DB DSN** — rotate the role's password; `tenant_writer` reaches
   every identity table, so treat it as a full identity-platform
   incident, not a database one.
