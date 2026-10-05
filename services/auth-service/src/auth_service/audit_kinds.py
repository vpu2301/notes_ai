"""Canonical audit event-kind strings; kept in sync with docs/audit/event-kinds.md."""

from __future__ import annotations

from typing import Final

# ── Authentication ────────────────────────────────────────────────────
AUTH_LOGIN: Final[str] = "auth.login"
AUTH_LOGIN_FAILED: Final[str] = "auth.login_failed"
AUTH_REFRESH: Final[str] = "auth.refresh"
AUTH_REFRESH_REPLAY_DETECTED: Final[str] = "auth.refresh_replay_detected"
AUTH_LOGOUT: Final[str] = "auth.logout"
AUTH_ACCOUNT_LOCKED: Final[str] = "auth.account_locked"

# Failed password re-entry by an authenticated user; `sec` (the shape of a hijacked tab).
AUTH_REAUTH_FAILED: Final[str] = "auth.reauth_failed"

# ── MFA ───────────────────────────────────────────────────────────────
AUTH_MFA_ENROLLED: Final[str] = "auth.mfa.enrolled"
# Admin-assisted reset; the catalogue's existing name wins over `auth.mfa.reset`.
USER_RESET_MFA: Final[str] = "user.reset_mfa"
# An access review asked a user to enrol; `sec` so the ask and the enrolment share a trail.
USER_MFA_REMINDED: Final[str] = "user.mfa_reminded"

# ── Session revocation ────────────────────────────────────────────────
AUTH_SESSION_REVOKED: Final[str] = "auth.session.revoked"
# `POST /auth/token` moved the session to another workspace (the one place a `tid` changes).
AUTH_TENANT_SWITCHED: Final[str] = "auth.tenant_switched"

# ── Email one-time codes ──────────────────────────────────────────────
# `auth.otp_requested` goes to the platform tenant, `auth.signup` to the new
# personal tenant. Payloads carry ids, never the address or the code.
AUTH_OTP_REQUESTED: Final[str] = "auth.otp_requested"
AUTH_OTP_FAILED: Final[str] = "auth.otp_failed"
AUTH_SIGNUP: Final[str] = "auth.signup"
AUTH_ACCOUNT_DELETION_CANCELLED: Final[str] = "auth.account_deletion_cancelled"

# ── Second factors, sessions and the account surface ──────────────────
# Reuses `AUTH_MFA_ENROLLED`; siblings follow the same dotted style.
AUTH_MFA_DISABLED: Final[str] = "auth.mfa.disabled"
AUTH_MFA_FAILED: Final[str] = "auth.mfa.failed"
# A first factor passed and a second was demanded; platform tenant (no workspace chosen yet).
AUTH_MFA_CHALLENGED: Final[str] = "auth.mfa.challenged"
# Every recovery-code use is worth a line (a burst = a stolen printout).
AUTH_RECOVERY_CODE_USED: Final[str] = "auth.mfa.recovery_code_used"
AUTH_RECOVERY_CODES_REGENERATED: Final[str] = "auth.mfa.recovery_codes_regenerated"
# The login identifier moving is how an account is quietly taken over.
AUTH_EMAIL_CHANGE_REQUESTED: Final[str] = "auth.email_change_requested"
AUTH_EMAIL_CHANGED: Final[str] = "auth.email_changed"
AUTH_EMAIL_REVERTED: Final[str] = "auth.email_reverted"
AUTH_ACCOUNT_DELETION_REQUESTED: Final[str] = "auth.account_deletion_requested"
# Written by the purge, to the platform tenant.
AUTH_ACCOUNT_PURGED: Final[str] = "auth.account_purged"

# ── Non-human principals ──────────────────────────────────────────────
# A device's lifecycle goes to its workspace's chain; a service credential's to the platform tenant.
CREDENTIAL_CREATED: Final[str] = "credential.created"
CREDENTIAL_ROTATED: Final[str] = "credential.rotated"
CREDENTIAL_REVOKED: Final[str] = "credential.revoked"
# A SUCCESSFUL grant is deliberately NOT audited (~96/day per room); failure is.
AUTH_CLIENT_CREDENTIALS_FAILED: Final[str] = "auth.client_credentials_failed"
AUTH_CLIENT_LOCKED: Final[str] = "auth.client_locked"

# ── Password recovery ─────────────────────────────────────────────────
# All `sec`. The request is recorded as well as the outcome; a request for an
# unknown address is deliberately NOT (the audit log must not be an enumeration oracle).
AUTH_PASSWORD_RESET_REQUESTED: Final[str] = "auth.password.reset_requested"
AUTH_PASSWORD_RESET_COMPLETED: Final[str] = "auth.password.reset_completed"
AUTH_PASSWORD_CHANGED: Final[str] = "auth.password.changed"
# The "this wasn't me" button: the highest-signal event this service emits.
AUTH_ACCOUNT_LOCKDOWN: Final[str] = "auth.account.lockdown"

# ── User lifecycle ────────────────────────────────────────────────────
USER_INVITED: Final[str] = "user.invited"
USER_DEACTIVATED: Final[str] = "user.deactivated"
USER_REACTIVATED: Final[str] = "user.reactivated"
USER_ROLE_CHANGED: Final[str] = "user.role_changed"

# ── Tenant lifecycle + membership ─────────────────────────────────────
TENANT_CREATED: Final[str] = "tenant.created"
TENANT_UPDATED: Final[str] = "tenant.updated"
TENANT_LOGO_UPDATED: Final[str] = "tenant.logo_updated"
TENANT_MEMBER_ADDED: Final[str] = "tenant.member_added"
TENANT_MEMBER_ROLE_CHANGED: Final[str] = "tenant.member_role_changed"
TENANT_MEMBER_REMOVED: Final[str] = "tenant.member_removed"
TENANT_SWITCHED: Final[str] = "tenant.switched"

# ── Referral leads ────────────────────────────────────────────────────
# Platform tenant; payload is ref_present only, never the address.
LEAD_CAPTURED: Final[str] = "lead.captured"
