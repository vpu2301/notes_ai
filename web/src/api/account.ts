// Account, second factor, sessions and room devices. All native-mode only
// (404 otherwise; see `isUnavailableHere`). Step-up 403s are handled solely
// by `http.ts` — never catch `reauth_required` here.

import { api } from "./http";
import type {
  AccountDeletion,
  CreatedCredential,
  Credential,
  EmailChangeChallenge,
  Identity,
  InvitationAccepted,
  InvitationLookup,
  MyInvitation,
  RecoveryCodes,
  RevokedCount,
  RotatedCredential,
  SessionInfo,
  TenantSummary,
  TotpEnrolment,
  WorkspaceToken,
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

/** Step-up gated. The secret and `otpauth_uri` come back exactly once; nothing may persist them. */
export function startTotpEnrolment(): Promise<TotpEnrolment> {
  return api<TotpEnrolment>("auth", "/auth/mfa/totp/enroll", { method: "POST" });
}

/** Finishing enrolment ends every other session. */
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

/** Step-up gated. 202 with a 30-day grace period; `409 sole_owner_with_members` lists the workspaces in the extras. */
export function deleteAccount(): Promise<AccountDeletion> {
  return api<AccountDeletion>("auth", "/auth/account/delete", {
    method: "POST",
    json: { confirm: "DELETE" },
  });
}

// ── workspaces (read-only here) ───────────────────────────────────────

/** The last `GET /tenants` answer: names a workspace while requests are held back (workspace moved). */
let lastTenants: TenantSummary[] = [];

export function listTenants(): Promise<{ items: TenantSummary[] }> {
  return api<{ items: TenantSummary[] }>("auth", "/tenants").then((r) => {
    lastTenants = r.items;
    return r;
  });
}

export function cachedTenants(): TenantSummary[] {
  return lastTenants;
}

/** Re-scope this session to `tenantId`; nothing rotates. Native sessions only (`409 legacy_session`). */
export function activateWorkspace(tenantId: string): Promise<WorkspaceToken> {
  return api<WorkspaceToken>("auth", "/auth/token", {
    method: "POST",
    json: { tenant_id: tenantId, activate: true },
    credentials: true,
  });
}

// ── invitations, the invitee's side ───────────────────────────────────

/** Anonymous: the token only shows who invited whom to what. Every non-live state is one 404. */
export function lookupInvitation(token: string): Promise<InvitationLookup> {
  return api<InvitationLookup>("auth", `/auth/invitations/${encodeURIComponent(token)}`, { auth: false });
}

/** The signed-in address must be the invited one (`403 invitation_email_mismatch`). Moves the session there. */
export function acceptInvitation(token: string): Promise<InvitationAccepted> {
  forgetMyInvitations();
  return api<InvitationAccepted>("auth", `/auth/invitations/${encodeURIComponent(token)}/accept`, {
    method: "POST",
    credentials: true,
  });
}

export function myInvitations(): Promise<MyInvitation[]> {
  return api<{ items: MyInvitation[] }>("auth", "/auth/invitations").then((r) => {
    openInvitations = { at: Date.now(), items: r.items };
    return r.items;
  });
}

/** How long the shell's "Invitations (n)" trusts its last read. */
export const OPEN_INVITATIONS_TTL_MS = 5 * 60_000;
let openInvitations: { at: number; items: MyInvitation[] } | null = null;

/** The shell's count: read at most once per five minutes, however often the window is focused. */
export function myInvitationsCached(): Promise<MyInvitation[]> {
  if (openInvitations && Date.now() - openInvitations.at < OPEN_INVITATIONS_TTL_MS) {
    return Promise.resolve(openInvitations.items);
  }
  return myInvitations();
}

/** After an accept or decline, or a sign-out: the next read goes to the server. */
export function forgetMyInvitations(): void {
  openInvitations = null;
}

export function acceptMyInvitation(id: string): Promise<InvitationAccepted> {
  forgetMyInvitations();
  return api<InvitationAccepted>("auth", `/auth/invitations/${id}/accept`, {
    method: "POST",
    credentials: true,
  });
}

export function declineMyInvitation(id: string): Promise<void> {
  forgetMyInvitations();
  return api<void>("auth", `/auth/invitations/${id}/decline`, { method: "POST" });
}

// ── room devices ──────────────────────────────────────────────────────

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
