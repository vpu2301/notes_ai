"""Canonical audit event-kind strings.

Centralised so misspellings fail at import time and the catalogue in
docs/audit/event-kinds.md (Day 10) stays in sync.
"""

from __future__ import annotations

from typing import Final

# ── Authentication ────────────────────────────────────────────────────
AUTH_LOGIN: Final[str] = "auth.login"
AUTH_LOGIN_FAILED: Final[str] = "auth.login_failed"
AUTH_REFRESH: Final[str] = "auth.refresh"
AUTH_REFRESH_REPLAY_DETECTED: Final[str] = "auth.refresh_replay_detected"
AUTH_LOGOUT: Final[str] = "auth.logout"
AUTH_ACCOUNT_LOCKED: Final[str] = "auth.account_locked"

# A failed password re-entry by an already-authenticated user (e.g. the
# current-password check on a password change). `sec` severity: a wrong
# password typed by someone holding a live session is exactly the shape
# of a hijacked tab.
AUTH_REAUTH_FAILED: Final[str] = "auth.reauth_failed"

# ── MFA (sprint 16) ───────────────────────────────────────────────────
AUTH_MFA_ENROLLED: Final[str] = "auth.mfa.enrolled"
# Admin-assisted reset. The kind was pre-ledgered in sprint 02
# (docs/audit/event-kinds.md, permissions.csv) as `user.reset_mfa`; the
# sprint-16 spec's `auth.mfa.reset` name lost to the existing catalogue.
USER_RESET_MFA: Final[str] = "user.reset_mfa"
# S21 — an access review asked a user to enrol. `sec` severity, because
# the interesting question a year later is not "was anyone reminded" but
# "how long did this account sit unprotected after we noticed", and that
# answer needs the ask and the enrolment on the same trail.
USER_MFA_REMINDED: Final[str] = "user.mfa_reminded"

# ── Session revocation (sprint 16) ────────────────────────────────────
AUTH_SESSION_REVOKED: Final[str] = "auth.session.revoked"
# IDX-A2: `POST /auth/token` moved the session to another workspace.
# Payload: sid, from_tenant_id, to_tenant_id — the one place a `tid` changes.
AUTH_TENANT_SWITCHED: Final[str] = "auth.tenant_switched"

# ── Email one-time codes (IDX-A3) ─────────────────────────────────────
# `auth.otp_requested` has no tenant yet (the email may be nobody's) and
# is written to the platform tenant; `auth.signup` goes to the new
# personal tenant. Payloads carry challenge_id / identity_id, never the
# address or the code.
AUTH_OTP_REQUESTED: Final[str] = "auth.otp_requested"
AUTH_OTP_FAILED: Final[str] = "auth.otp_failed"
AUTH_SIGNUP: Final[str] = "auth.signup"
AUTH_ACCOUNT_DELETION_CANCELLED: Final[str] = "auth.account_deletion_cancelled"

# ── Second factors, sessions and the account surface (IDX-A5) ─────────
# The pack writes these as `auth.mfa_enrolled` / `auth.mfa_failed`. The
# catalogue already had `auth.mfa.enrolled` from sprint 16, and the house
# rule (see USER_RESET_MFA above) is that the existing name wins — a
# rename would split one account's MFA history across two kinds for
# nothing. So A5 REUSES `AUTH_MFA_ENROLLED` and adds its siblings in the
# same dotted style.
AUTH_MFA_DISABLED: Final[str] = "auth.mfa.disabled"
AUTH_MFA_FAILED: Final[str] = "auth.mfa.failed"
# A first factor passed and a second was demanded. Written to the
# platform tenant: at this point the sign-in has not chosen a
# workspace, and the event is about the identity, not a customer.
AUTH_MFA_CHALLENGED: Final[str] = "auth.mfa.challenged"
# A recovery code is the credential a user keeps on paper. Every use is
# worth a line, because a burst of them is what a stolen printout looks
# like from the inside.
AUTH_RECOVERY_CODE_USED: Final[str] = "auth.mfa.recovery_code_used"
AUTH_RECOVERY_CODES_REGENERATED: Final[str] = "auth.mfa.recovery_codes_regenerated"
# The login identifier moving is the single most dangerous change a
# session can make — it is how an account is quietly taken over.
AUTH_EMAIL_CHANGE_REQUESTED: Final[str] = "auth.email_change_requested"
AUTH_EMAIL_CHANGED: Final[str] = "auth.email_changed"
AUTH_EMAIL_REVERTED: Final[str] = "auth.email_reverted"
AUTH_ACCOUNT_DELETION_REQUESTED: Final[str] = "auth.account_deletion_requested"
# Written by the purge script, to the platform tenant: by then the
# identity's own workspaces are gone and only a pseudonymous id remains.
AUTH_ACCOUNT_PURGED: Final[str] = "auth.account_purged"

# ── Non-human principals (IDX-B1b) ────────────────────────────────────
# A device's lifecycle is written to ITS WORKSPACE's chain — that is where
# somebody investigating a room recording will look. A service credential
# has no workspace, so it goes to the platform tenant.
CREDENTIAL_CREATED: Final[str] = "credential.created"
CREDENTIAL_ROTATED: Final[str] = "credential.rotated"
CREDENTIAL_REVOKED: Final[str] = "credential.revoked"
# A SUCCESSFUL client_credentials grant is deliberately NOT audited: one
# room fetches ~96 tokens a day, and burying a workspace's trail under
# "a device asked for a token and got one" makes the trail useless for the
# thing it exists for. Failure is audited, because failure is the shape of
# somebody guessing.
AUTH_CLIENT_CREDENTIALS_FAILED: Final[str] = "auth.client_credentials_failed"
AUTH_CLIENT_LOCKED: Final[str] = "auth.client_locked"

# ── Password recovery ─────────────────────────────────────────────────
# All `sec` severity. The *request* is recorded as well as the outcome
# because a burst of requests against one account, none of them
# completed, is the visible half of an attempt to take it over — and
# without the request event the trail starts only once the attacker
# succeeds.
#
# Note what is deliberately NOT recorded: a request for an address with
# no account. Writing one would turn the audit log into the account
# enumeration oracle the endpoint's uniform 202 exists to prevent.
AUTH_PASSWORD_RESET_REQUESTED: Final[str] = "auth.password.reset_requested"
AUTH_PASSWORD_RESET_COMPLETED: Final[str] = "auth.password.reset_completed"
AUTH_PASSWORD_CHANGED: Final[str] = "auth.password.changed"
# The "this wasn't me" button. Its own kind rather than a flavour of
# session-revoked, because it is a user telling us an account was taken
# over — the single highest-signal event this service can emit.
AUTH_ACCOUNT_LOCKDOWN: Final[str] = "auth.account.lockdown"

# ── User lifecycle ────────────────────────────────────────────────────
USER_INVITED: Final[str] = "user.invited"
USER_DEACTIVATED: Final[str] = "user.deactivated"
USER_REACTIVATED: Final[str] = "user.reactivated"
USER_ROLE_CHANGED: Final[str] = "user.role_changed"

# ── Tenant (company) lifecycle + membership (Sprint 12) ────────────────
TENANT_CREATED: Final[str] = "tenant.created"
TENANT_UPDATED: Final[str] = "tenant.updated"
TENANT_LOGO_UPDATED: Final[str] = "tenant.logo_updated"
TENANT_MEMBER_ADDED: Final[str] = "tenant.member_added"
TENANT_MEMBER_ROLE_CHANGED: Final[str] = "tenant.member_role_changed"
TENANT_MEMBER_REMOVED: Final[str] = "tenant.member_removed"
TENANT_SWITCHED: Final[str] = "tenant.switched"
