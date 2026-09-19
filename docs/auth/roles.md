# Roles

The realm defines six roles. The permission matrix lives at
`docs/auth/permissions.csv`; this file is its prose companion.

| Role           | Holds                                                   | Cannot                       |
| -------------- | ------------------------------------------------------- | ---------------------------- |
| `tenant_admin` | Onboarding, **user read/list, role management, deactivation/reactivation**, MFA reset, audit read/verify, tenant settings, templates, phrase/synonym curation, PII-free usage stats | Cross-tenant operations; **all note content** — notes, dictations, ASR jobs (S14 admin/content separation) |
| `member`       | Routine workspace user. Tenant-read. Notes (read/write), dictations, ASR, autocomplete | User admin (incl. user read); audit |
| `viewer`       | Limited workspace user. Same note/dictation reads and writes as member, minus `asr.cancel` | Most admin; user read     |
| `auditor`      | Read-only audit + tenant context + **read-only user roster (`user.read`)** + **one write: `user.remind_mfa`** (S21 — ask a user to enrol a second factor; changes nothing about the account) | Any write that alters an account: invite, roles, (de)activation, MFA reset; any note content |
| `service`      | Machine-to-machine token identity: S2S note/dictation/template/dictionary reads, ASR worker writes | Any human-facing admin operation |
| `device`       | Ambient-capture hardware (meeting-room devices, client-credentials auth): tenant-read, ASR job submit/read, dictation start/read/finalize, template read | **Everything else** — notes, users, audit, stats, notifications, dictionaries. Capture only |

The full machine-readable matrix (every role × action × target_kind, with an
explicit `true|false` for each) lives in `docs/auth/permissions.csv`; the
`libs/auth.perms.ALLOW` runtime gate mirrors it and a CI test fails on any
drift or any missing (role × action) combination.

There is **no global / cross-tenant super-admin role**. The DBA superuser
exists in the database but is never used by service code (ADR-0007).

## Administrators are separated from note content (S14)

`tenant_admin` holds **no content permission**. `asr.*`, `dictation.*` and
`note.read`/`note.write` are member/viewer only. An administrator manages
the workspace — its users, templates and dictionaries — but does not read
anyone's notes, dictations or transcripts.

This is a matrix over **roles, not people.** A founder who both runs the
workspace and takes notes holds *both* `tenant_admin` and `member`, and a
permission check passes on any granting role — their note access is
untouched. It is the admin-ONLY account that is restricted, which is why
the "give a working admin both roles" guidance below matters: assigning
`tenant_admin` alone takes their notes away.

One door is left open, on purpose:

- **`stats.read`** — PII-free aggregate reads. Admits an admin to the
  note-search, ASR-job and dictation-session lists in a stripped
  projection (no titles, no snippets, no transcripts, no result URLs),
  which is what keeps the usage dashboard's counts working.

## Membership roles → the `roles` claim (IDX)

The table above is the **permission** vocabulary. A self-serve workspace
has a second one: `tenant_memberships.role`, which says who may manage
the workspace. One membership carries one management role (the table is
`UNIQUE (tenant_id, user_sub)`), and `platform_roles_for`
(`auth_service.domain.identity_repository`) is the only place the two
vocabularies meet — a native session's `roles` claim is exactly what it
returns.

| Membership role | `roles` claim              | Who holds it |
| --------------- | -------------------------- | ------------ |
| `owner`         | `tenant_admin` + `member`  | The person who created the workspace — their own account, or the team/company they opened |
| `admin`         | `tenant_admin` + `member`  | Someone the owner appointed to run the workspace alongside them |
| `member`        | `member`                   | Works in the workspace |
| `assistant`     | `member`                   | Works in the workspace on someone else's behalf |
| `viewer`        | `viewer`                   | Reads, and dictates, but cannot cancel an ASR job |
| *(unknown)*     | `viewer`                   | A membership role we do not recognise must never become an admin |

**Managing a workspace never removes the ability to work in it.** S14
still holds where it was aimed — `tenant_admin` as a *permission* carries
no `note.*`, `asr.*` or `dictation.*`, so an admin-only account is still
expressible and still sees no content. What changed is the default a
person LANDS in: mapping `owner` to `tenant_admin` alone did not restrict
an administrator, it locked out the only account a new workspace has.
Every self-serve signup is the owner of the workspace it just created, so
the first thing that account did — write a note, start a recording — was
`403 deny: roles=['tenant_admin'] cannot 'asr.write'`.

An admin-only account is now made on purpose rather than by default:
assign the realm roles directly (`PUT /admin/users/{sub}/roles`) instead
of relying on a membership role to withhold `member`.

## Room devices are capture-only (`device`)

`device` is the identity of ambient-capture hardware — a meeting-room
microphone box that streams or uploads meetings on its own credentials
(Keycloak client credentials, one confidential client per room; see
`docs/runbooks/ambient-device.md`). Its grant set is deliberately the
smallest that lets a meeting be captured:

- `tenant.read`, `template.read` — session context and the template a
  conversation session loads on start;
- `dictation.start` / `dictation.read` / `dictation.finalize` — live
  conversation-mode capture over `dictation.v2`;
- `asr.write` / `asr.read` — the batch fallback: upload a recording,
  poll the job to confirm delivery.

Everything else is an explicit deny. The threat model is a compromised
or stolen box on an office shelf: it must not be able to read **any**
tenant content — no notes, no other transcripts beyond its own jobs, no
user roster, no audit trail, no usage stats. It can only *add*
audio/transcripts. `asr.cancel` is also denied: destructive acts on
capture go through a human member. Revocation is disabling the room's
Keycloak client — no user account is involved.

## Membership roles → the `roles` claim (native sessions)

A native session's `roles` claim is derived from the person's **membership**
in the workspace it is scoped to (`tenant_memberships.role`), by
`platform_roles_for` in `services/auth-service/.../identity_repository.py`:

| Membership role     | `roles` claim              |
| ------------------- | -------------------------- |
| `owner`, `admin`    | `tenant_admin` **+** `member` |
| `member`, `assistant` | `member`                 |
| `viewer`            | `viewer`                   |
| anything unknown    | `viewer` (never an admin)  |

**Running a workspace never removes the ability to work in it.** Mapping
`owner` to `tenant_admin` alone is not the S14 separation, it is a lockout:
the person who creates a workspace is its owner, so the first token every
self-serve account is ever issued would be one that cannot open a note,
create a space or start a recording — `403 deny: roles=['tenant_admin']
cannot 'asr.write'` on the first thing they try. The rule above is the
"a founder holds both" guidance applied by default rather than left as a
manual step nobody performs.

An **admin-only** account — administration with no content access — is
still expressible, and is still what `tenant_admin` alone means. It is now
a deliberate realm-role assignment (`PUT /admin/users/{sub}/roles`), not
something a person falls into by owning the workspace they created.

The claim is re-read from the membership every time a token is minted,
including on every refresh, so a role change takes effect on the next
rotation rather than at next sign-in. Clients lean on that: web, macOS and
iOS all refresh once and retry when a request comes back with a role
denial, so a token that predates a grant does not strand the app.

## Picking a role at invite time

- A person who runs the workspace *and* takes notes → assign **both**
  `tenant_admin` *and* `member`. A user can hold multiple realm roles.
  Since S14 this is **required**, not merely tidy: `tenant_admin` alone
  carries no note access.
- Compliance officer / external auditor → `auditor`. Doesn't need
  `tenant_admin`; the audit endpoints are independently role-gated.
- A colleague who mostly consumes shared notes but may still dictate →
  `viewer`.
- A machine that calls our API on a partner's behalf → `service`. The
  scope mechanism (Day 7) is wired for service tokens but per-scope
  checks are not yet enforced.
- A meeting-room capture device → **no user account at all**: a per-room
  credential in `service_credentials` holding `device`, which exchanges a
  client secret for a token at `POST /auth/oauth/token`
  (`docs/runbooks/ambient-device.md`). Before IDX-B1b this was a Keycloak
  client; that form of token is rejected by `libs/auth.Claims`, so any room
  still provisioned that way cannot call the API.

## Changing a user's role

`PUT /admin/users/{sub}/roles` (tenant_admin only, `user.manage_roles`)
sets a user's realm roles. The body is `{ "roles": ["member", …] }`,
validated against the known realm-role catalogue (unknown role → 422). The
endpoint sets the full role set in Keycloak and mirrors the
highest-privilege role into the local `users.role` column (which holds a
single value). It emits a `user.role_changed` audit event (severity `sec`)
recording the old → new role set.

**Guardrail:** the endpoint refuses (409) to remove `tenant_admin` from the
*last* active tenant_admin of a tenant, so a tenant can never be left
without an administrator.

Other user-management endpoints: `GET /admin/users` (list, paginated),
`GET /admin/users/{sub}` (read one), `POST /admin/users/invite`,
`POST /admin/users/{sub}/deactivate`, and
`POST /admin/users/{sub}/reactivate`. All are RLS-scoped to the caller's
tenant; a cross-tenant `sub` returns 404 (no existence leak).

### MFA reminders (S21)

`POST /admin/users/{sub}/mfa-reminder` — `user.remind_mfa`, held by
`tenant_admin` **and `auditor`**. Records a standing request that the target
enrols a second factor:

- One row per (tenant, user) in `mfa_reminders`. A repeat ask bumps
  `reminder_count` and reopens a resolved row rather than inserting a second.
- It closes in exactly one place: `POST /auth/mfa/verify` stamps
  `resolved_at` in the same transaction that sets `users.mfa_enrolled_at`.
  There is no dismiss endpoint, by design — a reminder the subject can wave
  away measures nothing.
- Refusals: 409 already enrolled or deactivated, 422 reminding yourself, 404
  outside the tenant.
- Audited `user.mfa_reminded` at `sec`, and published as the
  `security.mfa_reminder` notification (bell + email) to the subject alone.
- **Not** behind `requires_mfa()`, unlike every other mutation here: it is how
  a company with no enrolments bootstraps, and it grants nothing.

`GET /admin/users` and `GET /auth/me` were widened to carry the state these
surfaces read — `mfa_enrolled_at` + `mfa_reminded_at`/`mfa_reminder_count` on
the roster, and `db_user.mfa_reminder` (requester's **role**, never their name)
for the subject's own banner.

## How role changes propagate

- Existing access tokens keep their old roles until they expire (up to
  15 minutes). For immediate revocation, follow the runbook's
  "Suspected token theft" path: `POST /admin/users/{sub}/deactivate`
  also calls `/logout` which revokes refresh + active sessions in
  Keycloak.
- Next refresh after a Keycloak-side role change carries the new role
  set in the new access token (Keycloak rebuilds the claim set on
  refresh, not on access-token verify).

## The founding user of a self-serve workspace (Sprint 21, ADR-0048)

A person who creates a workspace through `/join` or `/signup` is its
only member and holds **both** `tenant_admin` and `member` realm roles
from the first sign-in (`onboarding_service.SIGNUP_REALM_ROLES`), with
`users.role = tenant_admin` and an `owner` membership. This is a
deliberate exception to the admin/content separation above: an admin
who cannot read notes is a locked-out workspace when there is nobody
else. Do not "fix" it by removing `member`; an admin-only account is
still expressible through `PUT /admin/users/{sub}/roles` when a second
person exists to do the work.
