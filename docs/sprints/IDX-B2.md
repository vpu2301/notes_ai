# IDX-B2 — Principal consolidation (`users` → `identities`) & Keycloak removal

**Status:** enabling half delivered (2026-09-05). **Keycloak is not
removed and `users` is not dropped** — the sprint's own gate is shut. See
§"Why the removal did not run".
**Branch:** S01 (uncommitted working tree).

## Why the removal did not run

The pack states the gate itself: *"Do not start F3 until that [B1b]
checklist is complete."* It is not, and four other preconditions are
unmet. Each was checked against the running stack, not assumed:

| Precondition | Actual state |
| --- | --- |
| A5 cut-over done | **No.** `MDX_IDP_MODE=keycloak` in `.env.example`, compose and the Helm values. The runbook was written in A5; the user chose not to execute it. |
| B1b: every room re-provisioned | **No.** The checklist in `docs/sprints/IDX-B1b.md` is empty. |
| B1 run | **No.** `profile_of_subs` did not exist; `/tenants/{id}/switch` and `/admin/users/*` are still the live routes, not compatibility shims. |
| W2/M2/I2 merged | **No.** The clients still send no `X-Client-Type` (A2/A5 debt). |
| A4 run | **No** — and this is the one that decides it. |

**A4 is the blocker that matters.** There is no native password login.
`/auth/login` → Keycloak's password grant is the only working sign-in for
every existing user; the only native path is the A3 email code, which no
client implements. Deleting Keycloak today locks every user out of every
environment. Dropping `users` compounds it: the pack's compat view is
granted to `tenant_writer` only, and notification-service reads
`users.email` as `app_role`, so notifications would break at the same
moment.

So this sprint did everything that makes the removal a short, safe
follow-up, and touched neither Keycloak nor `users`.

## Inspect first

| Item | Finding |
| --- | --- |
| FK inventory | **Thirteen**, not the six the pack lists. The seven it misses were added by later migrations: `auth_mail_outbox`, `auth_password_events`, `auth_password_reset_tokens`, `notifications`, `notification_preferences`, `notification_user_settings`, `notification_digest_progress`. The pack said "verify against the live catalogue" — this is why. |
| `identities ⊇ users` | **No**: 8 of 20 `users` rows had no identity, so F1's own guard would have aborted. A1's backfill never ran. |
| Email collisions blocking a backfill | **None** — 0 orphans collide with an existing identity, 0 duplicate each other. A clean 1:1. |
| `profile_of_subs` | Did not exist anywhere. F2 depends on it entirely. |
| Readers of `users` | note-service (`find_member_by_email`, `fetch_members`), notification-service (`filter_to_tenant_members`, `tenant_admin_ids`, `user_email`), auth-service (13 sites, runs as `tenant_writer`). |
| `mfa_reminders` | The pack says A5 retired it and it should be dropped. A5 did **not** retire it — `/auth/me` still reads it. Its two FKs were re-pointed instead. |
| Keycloak surface | 564 references across 81 files (`scripts/ci/check-no-keycloak.py --count`). |

## Delivered

1. **Migration `0027_identity_backfill_and_profiles`** — the two IDX-A1
   artefacts B2 needs. Backfills an identity per `users` row keeping the
   same UUID (which is what makes the FK swap a constraint change, not a
   data migration), carries the home tenant across, and creates
   `profile_of_subs`.
2. **Migration `0028_users_to_identities_fks`** — all thirteen FKs
   re-pointed at `identities`, `ON DELETE` preserved per constraint,
   `NOT VALID` + `VALIDATE` so no long exclusive lock. The statements were
   **generated from `pg_constraint`**, with the regeneration query in the
   file header — hand-typing an inventory is how the other seven were
   missed in the first place. A guard aborts if any `users` row still
   lacks an identity.
3. **F2 query rewrites** — note-service and notification-service read
   `profile_of_subs` (or `tenant_memberships` for the admin roster).
   `grep "FROM users\|JOIN users"` across every product service returns
   nothing.
4. **F4 `libs/auth/testing`** — `mint_test_token`, `auth_headers`,
   `shared_issuer` (one RSA key per session, not per test),
   `jwks_cache_for(issuer)`, `install_test_issuer`, and a pytest plugin
   (`auth.pytest_plugin`) with `auth_client_factory`.
5. **`scripts/ci/check-no-keycloak.py`** — written, deliberately **not
   wired into CI**, and currently reports 564 references. It is the
   removal's finish line and its progress bar.

### The bug this actually fixes

IDX-B2 §C describes it, and it is not cosmetic. `users` is keyed on
`sub`, so a principal has one row in one home tenant. A colleague
invited into a second workspace had **no row there**, and every roster
and author-name lookup was a `LEFT JOIN` that rendered them blank. Worse
than blank in one case: note-service's `find_member_by_email` could not
find them at all, so *sharing a note with a cross-tenant colleague failed
with "no such member"*. `profile_of_subs` reads `identities`, which is
not per-tenant, and both are fixed —
`test_note_service_finds_a_cross_tenant_member_by_email` is the proof.

### Deviation: the helper returns emails

The pack's F2 says `profile_of_subs` returns no emails, with roster
emails coming from auth-service instead. That does not survive contact
with the callers: note-service resolves a share recipient **by** address,
and notification-service needs an address to actually send to. Both read
`users.email` as `app_role` today. Omitting the column would not remove
that access — it would leave four call sites unable to move off `users`,
which is the thing the function exists to enable.

The privacy control is the membership predicate, and it is **tighter**
than what those callers have now: a row comes back only for a sub with an
active membership in the connection's tenant, an unscoped connection gets
nothing at all, and a `deleted` identity never resolves. All three are
tested.

## Verification

* Migrations applied to the dev database and round-tripped
  (`0028` down restores all 13 FKs to `users`, up moves them back).
* **0 FKs reference `users`; 13 now reference `identities`**, all
  validated, `ON DELETE` unchanged.
* `users_without_identity = 0` (was 8).
* New integration suite: **15 passed** — FK inventory by name, `ON
  DELETE` preservation, `convalidated`, the cross-tenant rendering fix,
  tenant scoping, suspended membership, unscoped connection, deleted
  identity, `app_role` still denied on `identities` directly, and the
  three rewritten service call paths.
* `libs/auth` **75 passed** (8 new, all going through the *real*
  `verify_token` — a wrong audience and an expired token still fail, so
  the harness cannot be mistaken for a bypass).
* Regression: auth-service 292, note-service 349, notification-service
  60, all green.
* `check-rls`, `check-identity-grants`, `lint-imports`,
  `check-metric-names`, `check-audit-insert`, `check-no-os-environ`,
  `check-no-crypto`, ruff: green.

### A regression I introduced in B1b and fixed here

`libs/auth`'s perms tests were failing: the `device.manage` rows I added
to `permissions.csv` in IDX-B1b used `owner`/`admin`, which are
**membership** roles, not the JWT roles that matrix is keyed on, and the
`credential` target kind was not registered. I had run auth-service's
suite but not `libs/auth`'s. Fixed: `credential` added to
`KNOWN_TARGET_KINDS`, `("tenant_admin", "device.manage", "credential")`
added to `ALLOW`, and the two invalid CSV rows removed — the owner/admin
mapping is prose in the matrix comment, where it belongs.

## Acceptance criteria

| Criterion | Status |
| --- | --- |
| `count(*) FROM pg_constraint WHERE confrelid='users'` = 0 | ✅ |
| `users` is a view granted only to `tenant_writer` | ❌ Deliberately not — `users` is untouched. Gated on A4. |
| No file outside ADR history references Keycloak | ❌ 564 references. Guard written, not wired. |
| Every service suite passes with no Keycloak running | ⚠️ The harness exists and libs/auth proves it; adopting it in every service `conftest.py` belongs with the removal, since those fixtures are what talks to Keycloak. |
| `profile_of_subs` is the only way product services get display names | ✅ `grep "JOIN users"` across product services returns nothing |
| Dev seed logs in on all three clients | ⚠️ Unchanged — still via Keycloak, which is correct until cut-over. |
| `/tenants/{id}/switch` and `/admin/users/*` return 404 | ❌ Not removed — B1 never ran, so they are the live routes, not shims. |

## What the removal sprint still has to do

Everything in F3, plus these, in this order:

1. **IDX-A4** — native password login. Without it the cut-over locks
   every existing user out.
2. Execute `docs/runbooks/idx-issuer-cutover.md` (staging, soak,
   production).
3. Complete B1b's room checklist.
4. Then: drop `users`, create the compat view — **and first decide what
   notification-service does**, because it reads `users.email` as
   `app_role` and the pack's view is `tenant_writer`-only. It is already
   migrated to `profile_of_subs` here, so the answer may simply be "the
   view needs no `app_role` grant after all" — worth confirming with a
   grep before the drop.
5. Delete Keycloak per F3; wire `make check-no-keycloak` on the same
   commit as the last deletion.
6. Adopt `auth.pytest_plugin` in every service `conftest.py`, replacing
   the Keycloak login fixtures.
7. `MDX_SESSION_REVOCATION_ENABLED=true` by default (H). Its precondition
   — the push side being fully internal — is now met by A5 and B1b, but
   it is a live deployment behaviour change and belongs with the cut-over,
   not with a schema sprint.
8. Delete the B1 compatibility routes after confirming W2/M2/I2 shipped.

## Debt / NOT-NOW

- `users` still exists with 13 auth-service read sites. They run as
  `tenant_writer` and are unaffected by the FK swap.
- `mfa_reminders` was not dropped — A5 did not retire it as the pack
  assumed, and `/auth/me` still reads it.
- `fakeredis` is a declared note-service dev dep that is not installed in
  the root venv, so `test_audio_clips_domain.py` cannot be collected
  there. Pre-existing, unrelated, and CI installs dev deps.
