# ADR-0070 — Invitations: one entity, an authenticated accept, auto-accept at sign-up

**Status:** Accepted (dev/staging). · **Date:** 2026-10-13 · **Implements:** Sprint W2
(workspaces & collaboration track) · **Related:** ADR-0069 (a workspace is a tenant), ADR-0031/0049
(mail boundaries), concept §5 (`docs/sprints/workspaces-collab/01-concept.md`)

## Context

After W1 a person can hold several workspaces, but nobody can bring anyone in: add-by-e-mail
only finds people already in the workspace, `POST /admin/users/invite` answers 410, and an
address without an account has no path at all.

## Decision

1. **One entity for every case.** `tenant_invitations` (migration 0072) covers an address with or
   without an account, a workspace or (W3, `note_id`) a single note. One live row per
   (workspace, address, note); re-inviting re-arms it with a new token (the old link stops
   working) instead of answering 409.
2. **The token only shows the invitation.** 32 random bytes, sha256 at rest, 14-day window.
   `GET /auth/invitations/{token}` (anonymous, 60/min per IP) returns the workspace name, the
   inviter's display name, the role and a masked address; every non-live state is the same 404.
3. **Accepting is authenticated and address-bound.** `POST /auth/invitations/{token|id}/accept`
   grants only when `lower(identity.email) = invitation.email`; the membership upsert and the
   accepted mark are one transaction decided by a conditional UPDATE (a racing revoke wins or
   loses cleanly); the session is switched to the workspace and its token returned. Joining
   twice is not an error.
4. **Auto-accept at sign-up only.** A new identity created by an e-mail code accepts its open
   invitations (each in its own transaction, failures stay pending) and lands in the first;
   `AuthResult.joined_tenant_ids` lets clients say "You joined …". Existing accounts accept
   explicitly — their switcher is theirs.
5. **Step-up for managing people, not for creating a workspace.** `POST /tenants {name}` needs a
   plain session; invite, resend, revoke, role change, remove and dissolve need a recent sign-in
   (300 s) in dual/native — MFA only under Keycloak.
6. **Leaving and dissolving are soft.** Leaving suspends your own row with `left_at` (swept after
   30 days). Dissolve: owner, team workspace, no other active members, typed name; memberships
   suspended, invitations revoked, restorable for 30 days. A session whose workspace is gone
   moves to Personal on its next refresh instead of being signed out.
7. **Mail** goes inline through `mailing.send_rendered` like the sign-in code (a relay failure is
   visible: the row stays, `delivery: "queued_failed"`, Resend). Not the outbox — that is the
   Keycloak-era password path.
8. **Notifications never read across tenants.** `workspace.invited` is written in the invitee's
   Personal workspace, `workspace.invitation_accepted` in the inviting one,
   `workspace.member_removed` in the removed person's Personal one — so the ordinary
   member filter holds and no copy carries a workspace or person name.

## Options considered

- **Add existing accounts directly, no acceptance.** Puts workspaces on someone's switcher
  without asking — the "spread like a virus" pattern. Rejected.
- **Link-holder joins** ("anyone with the link"). Turns a forwarded mail into access. Rejected
  (concept §9: not now).
- **Reading the inviting workspace's name in notification-service.** Needs a cross-tenant read
  under `app_role`. Rejected; the in-app Invitations list (auth-service, by the caller's own
  address) shows the names.

## Consequences

- `POST /tenants/{id}/members` with an `email` answers `409 use_invitations` in dual/native.
- Rate limits (`mdx:auth:rl`): `invite:tenant` 50/day and `invite:identity` 100/day fail closed
  (503 `invite_unavailable`); `resend:invitation` 3/day, `invite-lookup:ip` 60/min,
  `tenant-create:identity` 10/day fail open.
- The address is PII: the sweeper deletes revoked/expired rows after 90 days; `funnel_reader`
  gets column grants without `email` or `message`; the DSAR erase runbook covers the table.

## Revisit trigger

Acceptance of no-account invitations below 20 % over 7 days (`InvitationAcceptanceLow`).
