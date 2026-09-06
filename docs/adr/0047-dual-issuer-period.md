# ADR-0047 (ADR-IDX-09): A bounded dual-issuer period — `MDX_IDP_MODE=dual`

Date: 2026-09-06
Status: Accepted
Sprint: FND-0 (batch `first-account`)
Also filed as: **ADR-IDX-09** in the IDX pack's `01-ARCHITECTURE-DECISIONS.md`.
The pack lives outside this repository; this file is the in-repo copy of
record and the one the code references.

## Context

The identity work (IDX-A1…A3, A5, B1b) has landed a complete native issuer:
auth-service can mint RS256 tokens, serve `/.well-known/jwks.json`, own
sessions in Postgres, and sign a user up with an emailed one-time code.
All of it is gated behind a **binary** switch —
`MDX_IDP_MODE ∈ {keycloak, native}` (`config.py`, `main.py::create_app`).

Binary is the problem. Every service verifies against exactly one issuer
(`AUTH_ISSUER` / `AUTH_JWKS_URL` / `AUTH_AUDIENCE`, one string each), so
flipping auth-service to `native` invalidates every token in flight and
every existing Keycloak session at the same instant. `native` also
unmounts `/auth/login` and `/auth/password/*` — IDX-A4 was never run, so
there is no native password surface to replace them. The consequence is
that the only path to self-serve signup currently available is a big-bang
cut-over that logs out every existing user and takes their password login
away with them.

The business goal of this batch is narrower than the cut-over: **let a new
person create an account with an email code and start using the product.**
That needs the native issuer to mint for *new* users. It does not need
existing users moved.

## Decision

Add a third value to the mode switch.

`MDX_IDP_MODE ∈ {keycloak, dual, native}`, default `keycloak`, logged at
startup by every deployment.

- **`keycloak`** — today's behaviour, unchanged. Keycloak mints; the
  native routers are not mounted.
- **`dual`** — auth-service mints native tokens for email-code logins;
  Keycloak keeps minting for password logins. Both issuers are live at
  once. Every service trusts **a list** of issuers rather than one
  (FND-1), selecting the verification config by the token's `iss`.
- **`native`** — Keycloak is gone from the token path. Reached later, by
  IDX-A4/A5, not by this batch.

`dual` is **bounded to ≤ 8 weeks** and is ended by the A4/A5 cut-over. It
is a migration state, not an architecture.

### Consequence recorded up front

During `dual`, `POST /auth/token` (workspace switch) works for **native
sessions only**. A caller presenting a Keycloak token gets
`409 legacy_session`. Workspace switching is a native-session capability
because it re-mints an access token for a different `tid`, and
auth-service cannot re-mint a Keycloak token without Keycloak's key.
Existing users switch workspaces the way they do today — by signing in
again — until A4/A5 moves them.

## Options considered

**A — Big-bang cut-over (`keycloak` → `native` in one window).**
One switch, one issuer at a time, no multi-issuer code in `libs/auth`.
Rejected: it invalidates every live session and every access token at the
flip; it requires IDX-A4 (native password login) to exist first, which is
two sprints of work standing between us and the first self-serve account;
and its rollback is another mass logout. The blast radius is the entire
user base for a feature that only new users need.

**B — Dual issuer for a bounded period (chosen).**
`libs/auth` verifies against a list of issuers; auth-service routes by
token shape. New users get native sessions from day one; existing users
are untouched and keep their Keycloak password login. Cost: multi-issuer
verification code in the shared library and in every service's config
(FND-1), a routing rule in `/auth/refresh` and `/auth/logout`, and a
period where two issuers are simultaneously trusted. Bounded and revert-
able.

**C — Native issuer only for signup, Keycloak-provisioned afterwards.**
Sign the user up natively, then create them in Keycloak and hand back a
Keycloak token, so there is only ever one issuer. Rejected: it makes
Keycloak the write path for the thing we are retiring, adds a
distributed-transaction failure mode on the signup path (identity created,
Keycloak user not), and requires the Keycloak admin API on the hot path of
the batch's headline flow. It also defers, rather than removes, the
password-login problem.

## Evidence

- `services/auth-service/src/auth_service/main.py:231` — the binary switch;
  the `native` branch unmounts `login.router` and `password.router`.
- `docs/sprints/IDX-W2.md:54` — `PUT|DELETE /auth/password` do not exist;
  IDX-A4 was never run.
- `docs/sprints/IDX-B2.md:16` — the A5 cut-over was written and
  deliberately not executed; `MDX_IDP_MODE=keycloak` in `.env.example`,
  compose and the Helm values.
- `libs/auth/src/auth/jwks.py:61` — `JwksCache` is already keyed by
  issuer, with per-issuer state, locks and rate limits. Multi-issuer
  verification is a config and selection change, not a cache rewrite.
- `libs/auth/src/auth/verifier.py:39` — `expected_issuer: str` is the one
  place the single-issuer assumption is hard-coded.

## Consequences

Positive:
- A new person can create an account and use the product without any
  existing user being logged out or losing a login method.
- The cut-over stops being a single window with a mass-logout blast
  radius and becomes a sequence with a revert at every step.
- `libs/auth` gains a capability we need regardless of Keycloak's fate
  (issuer rotation without downtime is the same mechanism).

Negative:
- Two issuers are trusted at once. A compromise of *either* signing key is
  a compromise of the fleet for the duration. This is the reason for the
  8-week bound, and the reason FND-1's contract tests assert that a
  **third** issuer is rejected.
- Two code paths on `/auth/refresh` and `/auth/logout` for the duration
  (routed by the `nrt_` prefix, BE-2).
- `POST /auth/token` is capability-split by token origin — a wart that
  exists only during `dual`.

## Cut-over plan (replaces IDX-A0 §C3)

No big-bang window in this batch. The sequence:

1. **FND-1** — every service trusts a list of issuers. Fleet-wide deploy.
   Behaviour unchanged (the list has one live issuer; auth-service's JWKS
   is empty-but-valid).
2. **BE-2** — auth-service to `MDX_IDP_MODE=dual`. It starts minting.
3. **BE-3** — email-code signup opens. New users get native sessions.
4. *(later)* **A4/A5** — existing users migrate; native password login
   ships; mode moves to `native`.
5. *(later)* **B2** — Keycloak removed.

**Rollback, at any point: `MDX_IDP_MODE=keycloak`.** Written down because
it is not free: native identities created during `dual` cannot sign in
while the mode is reverted (there is no Keycloak user for them, and A4's
native password login does not exist yet). Their data is intact and their
sessions resume when the mode is restored. Accepted for a period measured
in weeks with a signup cohort measured in tens.

## Trigger conditions for revisiting

- **Revert trigger for the batch:** FND-1 fails to deploy cleanly
  fleet-wide — any service rejecting tokens it accepted before the issuer
  list landed. FND-1 is the batch's revert trigger precisely because it is
  the only step that touches every service at once.
- The 8-week bound is reached without A4/A5 landing → re-open, and decide
  explicitly whether to extend or to stop and finish the cut-over.
- A signing-key incident on either issuer → the dual period ends
  immediately in whichever direction is safe.
