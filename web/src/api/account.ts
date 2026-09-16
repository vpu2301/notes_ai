// Account, second factor, sessions and room devices (IDX-A5 + IDX-B1b).
//
// Everything here is native-mode only: `routers/account.py`,
// `routers/mfa_native.py` and `routers/credentials.py` are mounted under
// `MDX_IDP_MODE=native` and answer 404 otherwise — deliberately, so a
// prober cannot tell a switched-off deployment from an absent feature.
// `isUnavailableHere` (in `./auth`) is how a screen tells the difference.
//
// Several of these carry `Depends(recent_auth)` on the server. Nothing
// here handles that 403: `http.ts` owns it, opens the one reauth dialog,
// and retries. A call site that caught it itself would be a second,
// weaker step-up.

import { api } from "./http";
import type {
  AccountDeletion,
  CreatedCredential,
  Credential,
  EmailChangeChallenge,
  Identity,
  RecoveryCodes,
  RevokedCount,
  RotatedCredential,
  SessionInfo,
  TenantSummary,
  TotpEnrolment,
} from "./types";

// ── sessions ──────────────────────────────────────────────────────────

export function listSessions(): Promise<SessionInfo[]> {
  return api<SessionInfo[]>("auth", "/auth/sessions");
}

export function revokeSession(sessionId: string): Promise<void> {
  return api<void>("auth", `/auth/sessions/${sessionId}`, { method: "DELETE" });
}

/** Step-up gated. Returns how many were ended. */
export function revokeOtherSessions(): Promise<RevokedCount> {
  return api<RevokedCount>("auth", "/auth/sessions/revoke-others", { method: "POST" });
}

// ── second factor ─────────────────────────────────────────────────────

/**
 * Step-up gated. The secret and `otpauth_uri` come back exactly once and
 * only until a code confirms them; after that the secret exists solely as
 * ciphertext on the server. Nothing may persist either.
 */
export function startTotpEnrolment(): Promise<TotpEnrolment> {
  return api<TotpEnrolment>("auth", "/auth/mfa/totp/enroll", { method: "POST" });
}

/**
 * Finishing enrolment ends every other session — turning MFA on is a
 * remedy for "somebody may be in my account", not just a new lock.
 */
export function confirmTotpEnrolment(enrollmentId: string, code: string): Promise<RecoveryCodes> {
  return api<RecoveryCodes>("auth", "/auth/mfa/totp/confirm", {
    method: "POST",
    json: { enrollment_id: enrollmentId, code },
  });
}

/** Step-up gated, and needs a live factor on top. Also ends other sessions. */
export function disableMfa(method: "totp" | "recovery_code", code: string): Promise<void> {
  return api<void>("auth", "/auth/mfa/disable", { method: "POST", json: { method, code } });
}

/** Step-up gated. Invalidates the previous set — there is no "show me again". */
export function regenerateRecoveryCodes(): Promise<RecoveryCodes> {
  return api<RecoveryCodes>("auth", "/auth/mfa/recovery-codes", { method: "POST" });
}

// ── email address ─────────────────────────────────────────────────────

/** Step-up gated. Mails a code to the NEW address. */
export function startEmailChange(newEmail: string): Promise<EmailChangeChallenge> {
  return api<EmailChangeChallenge>("auth", "/auth/email/change/start", {
    method: "POST",
    json: { new_email: newEmail },
  });
}

/** On success the old address is mailed a revert link. */
export function confirmEmailChange(challengeId: string, code: string): Promise<Identity> {
  return api<Identity>("auth", "/auth/email/change/confirm", {
    method: "POST",
    json: { challenge_id: challengeId, code },
  });
}

// ── deletion ──────────────────────────────────────────────────────────

/**
 * Step-up gated. 202 with a 30-day grace period; signing in again cancels
 * it. `409 sole_owner_with_members` lists the workspaces in the extras.
 */
export function deleteAccount(): Promise<AccountDeletion> {
  return api<AccountDeletion>("auth", "/auth/account/delete", {
    method: "POST",
    json: { confirm: "DELETE" },
  });
}

// ── workspaces (read-only here; B1 owns the rest) ─────────────────────

export function listTenants(): Promise<{ items: TenantSummary[] }> {
  return api<{ items: TenantSummary[] }>("auth", "/tenants");
}

// ── room devices (IDX-B1b) ────────────────────────────────────────────

export function listDevices(tenantId: string): Promise<Credential[]> {
  return api<Credential[]>("auth", `/tenants/${tenantId}/devices`);
}

/** Step-up gated. The response is the only time the secret exists here. */
export function createDevice(tenantId: string, name: string): Promise<CreatedCredential> {
  return api<CreatedCredential>("auth", `/tenants/${tenantId}/devices`, {
    method: "POST",
    json: { name },
  });
}

/** Step-up gated. The previous secret keeps working until `old_expires_at`. */
export function rotateDevice(
  tenantId: string,
  credentialId: string,
): Promise<RotatedCredential> {
  return api<RotatedCredential>("auth", `/tenants/${tenantId}/devices/${credentialId}/rotate`, {
    method: "POST",
    json: {},
  });
}

export function revokeDevice(tenantId: string, credentialId: string): Promise<void> {
  return api<void>("auth", `/tenants/${tenantId}/devices/${credentialId}`, { method: "DELETE" });
}
