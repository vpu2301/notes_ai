# ADR-0048 — Self-serve signup stays on the BE-0 path; referral attribution is a stamp on `referrals`

**Status:** Accepted · **Date:** 2026-09-17 · **Sprint:** 21 (recipient viral loop)

## Context

Sprint 21's brief describes a signup built around a `pending_signups`
table, a verification *link*, and a tenant created only at verification.
By the time the sprint started, BE-0 (`first-account` batch, 2026-09-06)
had already shipped password signup on the current stack:
`POST /auth/signup` creates the Keycloak user (disabled), the personal
tenant, the owner membership, the `identities` and `users` rows in one
transaction, and mails a six-digit *code*; `/auth/signup/verify` enables
the account. Web `/signup`, macOS and iOS "Create one" all use it.

Two designs for one door would be the worst outcome: two enumeration
surfaces, two rate-limit sets, two mail templates, two places for the
founding-role rule to drift.

## Decision

1. **One signup path.** Sprint 21 extends BE-0 instead of replacing it.
   The tenant is still created at signup (BE-0's compensation logic
   already handles the failure modes the brief worried about); it is
   `plan = 'free'` from the first row and `status = invited` until the
   code is spent. No `pending_signups` table, no verification link.
2. **The free plan is recorded, not enforced** — `tenants.plan`,
   `tenants.signup_source`, `tenants.plan_limits` (migration 0038).
   Existing personal workspaces are backfilled to `free / self_serve`;
   everything else is `legacy / admin`.
3. **Attribution is a stamp, never a join key to the sender.** Signup
   with a `ref` inserts `referrals (ref_code, referred_sub)`; verify sets
   `referred_tenant_id`. The referring tenant is never written next to
   the new one; the funnel joins `ref_code` to `note_share_links` offline
   (`scripts/ops/loop_funnel.sql`). Audit payloads carry `ref_present`,
   never the code.
4. **Uniform 202, uniform clock.** A throwaway-mail domain (bundled list
   in `domain/disposable_domains.py`, extendable by file) creates
   nothing and answers the same 202; `/auth/signup` holds every branch to
   a minimum response time (`AUTH_SIGNUP_MIN_RESPONSE_MS`, 300 ms).
5. **`/join` is the funnel page.** It asks `GET /auth/signup/config` and
   renders the signup form when signup is on, the Sprint 19 lead form
   otherwise. The native apps open `/join`; they carry no `ref`.
6. **Founding role set.** Unchanged from BE-0: the owner of a personal
   workspace holds both `tenant_admin` and `member` realm roles
   (`docs/auth/roles.md`), because `tenant_admin` alone cannot read a
   note and a one-person workspace must be usable.

## Consequences

- A referred person lands on `/meeting/new?first_run=1`; everyone else
  lands where BE-0 already sent them.
- Sprint 21's `pending_signups` migration, verification-link mails and
  Keycloak client additions are not built; the acceptance criteria that
  named them are met by BE-0's code-based equivalents.
- Plan enforcement, when it comes, reads `plan_limits` and needs no
  data migration.
