# Runbook — ambient room-capture devices

Provisioning and operating meeting-room capture hardware ("ambient
scribe" boxes). A room device is a **machine identity, not a user**: one
confidential Keycloak client per room, authenticating with client
credentials, whose service account holds the capture-only `device` realm
role. It can add audio/transcripts; it can read no tenant content.

## Key paths

| Concern            | Path / value                                                       |
| ------------------ | ------------------------------------------------------------------ |
| Role definition    | `libs/auth/src/auth/perms.py` (`device`), `docs/auth/permissions.csv` |
| Role rationale     | `docs/auth/roles.md` §"Room devices are capture-only"              |
| Dev example client | `infra/keycloak/realm-export.json` → `room-device-demo`            |
| Live capture       | `wss://<api-host>/ws/dictate`, subprotocol `dictation.v2`          |
| Protocol specs     | `docs/api/dictation-ws-v1.md`, `docs/api/dictation-ws-v2.md`       |
| Batch fallback     | `POST /asr/jobs` (asr-service), then `GET /asr/jobs/{id}/result`   |
| Token endpoint     | `<keycloak>/realms/notes/protocol/openid-connect/token` (dev host: `http://localhost:8088`, in-network: `http://keycloak:8080`) |

## What the `device` role can and cannot do

Grants (everything else is an explicit deny in the matrix):
`tenant.read`, `asr.write`, `asr.read`, `dictation.start`,
`dictation.read`, `dictation.finalize`, `template.read`.

Threat model: a compromised or stolen box on an office shelf. Its token
cannot read notes, other users' transcripts, the user roster, audit, or
stats — only submit new capture and read back **its own** jobs/sessions.
Even `asr.cancel` is denied: destructive acts go through a human member.

## Provisioning a new room

One client per room — the clientId **is** the device identity in audit
trails, so name it after the room, e.g. `room-device-berlin-4f`.

Using `kcadm.sh` inside the Keycloak container (dev; in prod, run the
same against your admin host):

```bash
KCADM="docker compose exec keycloak /opt/keycloak/bin/kcadm.sh"
$KCADM config credentials --server http://localhost:8080 \
  --realm master --user "$KC_ADMIN" --password "$KC_ADMIN_PW"

# 1. Confidential, service-accounts-only client. No browser flows.
$KCADM create clients -r notes -f - <<'EOF'
{
  "clientId": "room-device-berlin-4f",
  "enabled": true,
  "publicClient": false,
  "clientAuthenticatorType": "client-secret",
  "standardFlowEnabled": false,
  "directAccessGrantsEnabled": false,
  "implicitFlowEnabled": false,
  "serviceAccountsEnabled": true
}
EOF

# 2. Protocol mappers — copy the three from `room-device-demo` in
#    realm-export.json: audience `mdx-api`, flat `roles` array, and the
#    `tid` mapper on the `tenant_id` user attribute. All three are
#    REQUIRED: libs/auth rejects a token without aud/roles/tid.

# 3. Bind the service account to the room's tenant and grant `device`.
CID=$($KCADM get clients -r notes -q clientId=room-device-berlin-4f --fields id --format csv --noquotes)
SA=$($KCADM get "clients/$CID/service-account-user" -r notes --fields id --format csv --noquotes)
$KCADM update "users/$SA" -r notes \
  -s 'attributes.tenant_id=["<TENANT-UUID>"]'
$KCADM add-roles -r notes --uid "$SA" --rolename device

# 4. Read the generated secret and load it into the device's secure store.
$KCADM get "clients/$CID/client-secret" -r notes
```

The dev realm export ships a ready-made example, `room-device-demo`
(secret `dev-room-device-secret`, tenant A) — use it for local testing,
never as a template for real secrets.

## Getting a token (client_credentials)

```bash
curl -s http://localhost:8088/realms/notes/protocol/openid-connect/token \
  -d grant_type=client_credentials \
  -d client_id=room-device-demo \
  -d client_secret=dev-room-device-secret | jq -r .access_token
```

Expect in the decoded token: `aud` containing `mdx-api`, `roles:
["device"]`, `tid` = the room's tenant UUID. Lifespan is the realm's
`accessTokenLifespan` (**900 s**). Client-credentials tokens carry **no
refresh token** (`client_credentials.use_refresh_token=false`) — refresh
means running the same grant again (see "Long meetings" below).

## Live capture (preferred): `dictation.v2` conversation mode

Connect to `wss://<api-host>/ws/dictate` offering
`Sec-WebSocket-Protocol: dictation.v2` and the bearer either as an
`Authorization: Bearer <jwt>` header or `?token=<jwt>` (devices can set
headers; the query form exists for browser clients). Then:

```jsonc
{
  "type": "start_session",
  "protocol_version": 2,
  "language": "en",
  "mode": "conversation",           // diarized; SPEAKER_N proposals
  "template_id": "…",               // needed for a draft at finalize
  "capture_source": "room_device",  // ambient-capture v1 field
  "device_name": "Berlin 4F"        // free-text room/device label
}
```

`capture_source` (`"browser"` default | `"mobile"` | `"room_device"`)
and `device_name` (1–128 chars, allowed with any source) are the
ambient-capture v1 additions to `start_session` (v1 and v2): both are
validated (unknown source → `bad_message`), persisted on
`dictation_sessions` (migration `0014_ambient_capture`), included in
the `dictation.session.started` audit payload, and returned on
`GET /dictate/sessions` list and detail rows. They describe the
original capture — a resume from another surface never overwrites
them. A room device MUST send `capture_source: "room_device"` plus a
stable `device_name` — that is what lets a reviewer distinguish "the
room heard this" from "a person dictated this".

Everything else is the standard v2 flow (`docs/api/dictation-ws-v2.md`):
speaker labels arrive as neutral proposals, finalize
(`end_session`) renders speaker-turn dialogue and pushes a draft note.
A device does **not** send `set_speaker_mapping` — naming speakers is a
human, post-hoc edit. Heartbeat/cadence rules from v1 apply (client
traffic at least every 35 s; hard session cap 60 min).

## Batch fallback: upload the recording

When live streaming isn't possible (no GPU capacity — `gpu_full` /
close 1013 — or flaky room network), record locally and upload:

```bash
curl -s -X POST https://<api-host>/asr/jobs \
  -H "Authorization: Bearer $TOKEN" \
  -F audio=@meeting.opus \
  -F language=en \
  -F diarize=true
# → 202 { "id": "<job-id>", "status": "queued", … }
```

`diarize` (bool multipart field, default `false`) is the ambient-capture
v1 addition to `POST /asr/jobs`; it rides the Redis-stream enqueue
payload to the asr-worker (no DB column). A diarized COMPLETE result's
segments carry `speaker` (`"SPEAKER_1"…"SPEAKER_N"`, `null` when
unattributed) and the result lists `speakers` in first-appearance order.

Poll `GET /asr/jobs/{id}` / fetch `GET /asr/jobs/{id}/result` (the
device holds `asr.read`) to confirm delivery, then delete the local
recording. A human member later turns the job into a note via
`POST /v1/notes/from-transcript`, which renders a diarized result as
speaker-turn dialogue lines automatically.

## Long meetings: token refresh

- Access tokens live 15 minutes and the client-credentials grant issues
  **no OAuth refresh token** — "refreshing" is simply running the grant
  again. Re-run it with a margin (e.g. every 12 min) and use the newest
  token for every new HTTP request.
- The WebSocket enforces expiry **mid-session**: a watchdog emits
  `token_expiring{expires_in_s}` from 60 s before expiry (re-emitted
  every 15 s) and terminates the session if the token lapses. On the
  warning, mint a fresh client-credentials token and send
  `refresh_token{token}` on the socket. The new token must carry the
  same subject + tenant — true for a device, since every grant for the
  same client returns the same service-account `sub` and `tid`.
- If the socket drops instead, reconnect with a fresh token and
  `start_session{resume_session_id}` (resume semantics per
  `dictation-ws-v1.md`; the session survives in `reconnecting` for up to
  30 min).
- The 60-minute hard session cap still applies: for longer meetings,
  finalize and start a new session, or use the batch path.

## Revocation / decommissioning a room

Disable the room's client — the device can no longer mint tokens:

```bash
$KCADM update "clients/$CID" -r notes -s enabled=false
```

Already-issued access tokens remain valid until expiry (≤15 min); that
window buys capture-only actions, no reads of existing content. Rotate
instead of disable (suspected secret leak, device still trusted):
`POST clients/$CID/client-secret` regenerates the secret. Deleting the
client entirely also works but loses the audit-friendly identity; prefer
`enabled=false`.
