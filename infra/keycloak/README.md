# Keycloak realm import

`realm-export.json` is imported at container start (`--import-realm`). Keycloak deserializes it
into `RealmRepresentation` with **unknown properties rejected**, so the file must contain only
real Keycloak fields — no `_comment_*` keys, no JSON5/JSONC comments. Adding one fails the
import with `UnrecognizedPropertyException` and the container exits 1, taking every
`depends_on: keycloak` service down with `dependency failed to start`.

Notes that would otherwise be inline comments live here.

## `sslRequired: "NONE"` — DEV ONLY

`external` is the Keycloak default and the correct production value: it demands HTTPS for any
request Keycloak deems non-private. On Docker Desktop a browser on the host reaches Keycloak
through the bridge gateway, which Keycloak treats as external, so every realm endpoint answered
`403 HTTPS required` — the admin console loaded but could never sign in. The SPA was unaffected
because auth-service talks to Keycloak inside the Docker network.

Production MUST set this back to `external` and terminate TLS in front of Keycloak.

The `master` realm is created by Keycloak bootstrap and is not covered by this file (which
defines the `notes` realm). Relax it separately for local admin-console access:

```bash
docker compose exec keycloak /opt/keycloak/bin/kcadm.sh \
  update realms/master -s sslRequired=NONE
```

## `room-device-demo` — ambient-capture device client (DEV ONLY)

One meeting-room capture device = one confidential, service-accounts-only client. The
export ships a single dev example, `room-device-demo` (secret `dev-room-device-secret`):

- **client_credentials only** — `standardFlowEnabled`, `directAccessGrantsEnabled` and
  `implicitFlowEnabled` are all false; a room device never runs a browser flow.
- Its service-account user (`service-account-room-device-demo`) holds the **`device`**
  realm role — the capture-only grant set (see `docs/auth/roles.md` and
  `docs/auth/permissions.csv`) — and a `tenant_id` attribute (tenant A) that the tid
  protocol mapper turns into the `tid` claim `libs/auth` requires on every token.
- Mappers mirror the other S2S clients (`aud=mdx-api`, flat `roles` array) plus the
  `tid` mapper, because unlike the worker clients a device is tenant-bound.

Provisioning real rooms (one client per room, naming, rotation, revocation) is the
runbook `docs/runbooks/ambient-device.md`. The dev secret here is, like every other
secret in this file, **not** a production credential.
