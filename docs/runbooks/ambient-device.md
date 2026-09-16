# Runbook — meeting-room capture devices

One room = one credential. A device holds a client id and a client
secret, exchanges them for a 15-minute access token, and uses that token
to upload recordings (`POST /asr/jobs`) or open a live capture session.
It has no user account, no password, and no refresh token.

Since IDX-B1b the credential lives in auth-service, not Keycloak. If you
are looking for the old `kcadm` procedure, it is in git history — do not
use it: a Keycloak room-device token is rejected by `libs/auth.Claims`
(no `sid`, plus `client_id`/`clientHost`/`clientAddress`, which the model
forbids), so devices provisioned that way cannot call the API at all.

**Requires:** auth-service in `MDX_IDP_MODE=native`. See
`docs/runbooks/idx-issuer-cutover.md`.

---

## What a device may do

`device` is capture-only, and deliberately so — a box on a wall in a room
anyone can walk into is the least trustworthy principal in the system.
The grant set (`docs/auth/permissions.csv`) is:

| Allowed | Not allowed |
| --- | --- |
| `asr.write`, `asr.read` — upload a recording, read back its own job | notes, users, audit, stats, dictionaries |
| `dictation.start`, `dictation.read`, `dictation.finalize` | `asr.cancel` — cancellations go through a human |
| `tenant.read` — its own workspace context | anything in another workspace |

The token's `tid` comes from the credential row, never from the request.
A device cannot ask to be in another workspace, and RLS stops it even if
the grant were wrong.

## Create a room

```bash
export MDX_OPERATOR_TOKEN=...   # platform operator, recent auth
uv run python scripts/ops/idx-provision-device.py \
    --auth-url https://auth.example.com \
    --tenant <workspace id> \
    --name "Room 4.02"
```

Or, if the workspace's own owner is doing it:

```bash
curl -sX POST https://auth.example.com/tenants/<workspace id>/devices \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "Room 4.02"}' | jq
```

Both need **recent auth** — sign in, or complete `POST /auth/reauth`,
within the last five minutes. Both print the secret exactly once.

> Name it after the room, not the hardware. The name is what appears in
> the workspace's audit trail next to a recording, and "Room 4.02" tells
> somebody reading it six months later what they need to know; "Rev B
> unit 7" does not.

## Configure the device

| Setting | Value |
| --- | --- |
| Token URL | `https://auth.example.com/auth/oauth/token` |
| Grant | `client_credentials` |
| Client id | the `id` from the create response |
| Client secret | the `secret` from the create response |

## Verify

```bash
curl -s -X POST https://auth.example.com/auth/oauth/token \
  -d grant_type=client_credentials \
  -d client_id=<id> \
  -d client_secret=<secret> | jq -r .access_token
```

A 200 with a JWT means the room is live. Check the payload carries
`"roles": ["device"]` and the right `tid`. Locally, `./scripts/dev/auth-test.sh s2s`
does all of this against the seeded dev device.

Then confirm the real path end to end: upload a short recording with
`diarize=true` and check the job appears in the workspace.

## Rotate

A room can be re-keyed without a visit, because **both secrets work
during the overlap**:

```bash
curl -sX POST https://auth.example.com/tenants/<ws>/devices/<id>/rotate \
  -H "Authorization: Bearer $TOKEN" | jq
```

Returns a new secret and `old_expires_at` (24 h by default, 7 d maximum).
Deploy the new secret whenever somebody is next in the room; the old one
stops working at `old_expires_at`.

Rotation deliberately does **not** revoke. A rotation that took the room
offline the moment the button was pressed is a rotation nobody performs.

Rotate when: an installer leaves, a secret is pasted somewhere it should
not be, or on whatever schedule your policy sets. There is no automatic
expiry otherwise.

**Two live secrets is the maximum.** A third would make "which one is
deployed" unanswerable, which is the state rotation exists to avoid — the
API answers `409 rotation_in_progress`.

## Revoke

```bash
curl -sX DELETE https://auth.example.com/tenants/<ws>/devices/<id> \
  -H "Authorization: Bearer $TOKEN"
```

Immediate: the credential and every secret are revoked, and the id is
pushed onto the session denylist, so the token the device is currently
holding stops working at its next request rather than in 15 minutes.

Revoke when hardware is decommissioned, lost, or leaves the building.

## When something is wrong

| Symptom | Cause | Do this |
| --- | --- | --- |
| `401 invalid_client` | wrong/revoked/expired secret, or an unknown id | Re-provision. The response is deliberately identical for all of these, so there is nothing to diagnose from it — check `auth.client_credentials_failed` in the platform tenant's audit trail for the reason. |
| `423 client_locked` | ten wrong secrets in ten minutes | Wait 15 minutes, or clear the lock (below). Then fix the configured secret — a locked room is usually a device left running with a rotated-away secret. |
| `429 client_rate_limited` | more than 60 grants a minute | The device is not caching its token. It should hold one for ~15 minutes. |
| `503 try_again`, `Retry-After: 5` | Redis is unreachable, so the lock cannot be checked | Nothing to do on the device — it retries. This endpoint fails **closed** on purpose: the alternative is unlimited secret guessing. |
| Token works, uploads 404 | the device is in a different workspace than the notes | Check `tid` in the token against the workspace. |

Clearing a lock (operator, after fixing the configured secret):

```bash
redis-cli DEL "mdx:auth:lock:client:<client id>" "mdx:auth:fail:client:<client id>"
```

## Dev

`make seed` creates one device in tenant A:

* client id `0000000d-0000-0000-0000-00000000d0e1`
* secret `dev-room-device-secret` — the same string the Keycloak realm
  used, so a dev device config needs no change across the cut-over.

Dev only. It is seeded by `scripts/seed/seed.py`, which computes the hash
rather than hard-coding one.

## Migrating rooms off Keycloak

Every production room must be re-provisioned **before IDX-B2 removes
Keycloak**, and each one verified with the check above. Track it in the
IDX-B1b sprint log as a checklist of room names and client ids — never
secrets.

There is no bulk migration and there cannot be: Keycloak stores the
client secret hashed, so the existing secrets cannot be read out and
carried over. Each room gets a new credential and a visit (or a remote
config push, if the fleet supports one).

Order per room: create the new credential → configure the device →
verify → only then delete the Keycloak client. The two coexist happily
while `MDX_IDP_MODE` is still `keycloak`, so this can be done room by
room over as long as it takes.
