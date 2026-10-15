// The workspace's own profile (auth-service `/tenants/{id}`), for the settings page.
import { api } from "./http";
import type {
  CollaboratorRole,
  DissolveResult,
  InvitationOut,
  InvitationRole,
  MemberList,
  TenantMember,
  TenantProfile,
  WorkspaceToken,
} from "./types";

/** Self-serve short form: a name (1–80 chars) is all; the caller becomes its owner. */
export function createWorkspace(name: string): Promise<TenantProfile> {
  return api<TenantProfile>("auth", "/tenants", { method: "POST", json: { name }, credentials: true });
}

export function getTenant(id: string): Promise<TenantProfile> {
  return api<TenantProfile>("auth", `/tenants/${id}`, { credentials: true });
}

export function patchTenant(
  id: string,
  patch: Partial<Pick<TenantProfile, "display_name" | "legal_name" | "contact_email">>,
): Promise<TenantProfile> {
  return api<TenantProfile>("auth", `/tenants/${id}`, { method: "PATCH", json: patch, credentials: true });
}

/** PNG/SVG/JPEG, at most 2 MB; the server validates the type. */
export function uploadLogo(id: string, file: File): Promise<TenantProfile> {
  const form = new FormData();
  form.append("file", file);
  return api<TenantProfile>("auth", `/tenants/${id}/logo`, { method: "PUT", form, credentials: true });
}

// ── members (owner/admin; the server re-checks the role on every call) ──

export function listMembers(id: string): Promise<MemberList> {
  return api<MemberList>("auth", `/tenants/${id}/members`, { credentials: true });
}

export function setMemberRole(id: string, sub: string, role: string): Promise<TenantMember> {
  return api<TenantMember>("auth", `/tenants/${id}/members/${sub}`, {
    method: "PATCH",
    json: { role },
    credentials: true,
  });
}

export function removeMember(id: string, sub: string): Promise<void> {
  return api<void>("auth", `/tenants/${id}/members/${sub}`, { method: "DELETE", credentials: true });
}

/** Your own row goes `suspended`; the token is for your Personal workspace, where the session already is. */
export function leaveWorkspace(id: string): Promise<{ token: WorkspaceToken }> {
  return api<{ token: WorkspaceToken }>("auth", `/tenants/${id}/members/me`, {
    method: "DELETE",
    credentials: true,
  });
}

/** Owner only, nobody else left in it, and the name typed exactly. */
export function dissolveWorkspace(id: string, confirmName: string): Promise<DissolveResult> {
  return api<DissolveResult>("auth", `/tenants/${id}/dissolve`, {
    method: "POST",
    json: { confirm_name: confirmName },
    credentials: true,
  });
}

// ── invitations (owner/admin; step-up gated, `http.ts` handles reauth) ──

export function listInvitations(
  id: string,
  status: InvitationOut["status"] = "pending",
): Promise<InvitationOut[]> {
  return api<{ items: InvitationOut[] }>("auth", `/tenants/${id}/invitations`, {
    query: { status },
    credentials: true,
  }).then((r) => r.items);
}

/** 201 new, 200 when a live one existed (it is resent). With `note_id` (role `guest`) it invites to one note. */
export function invite(
  id: string,
  body: {
    email: string;
    role: InvitationRole;
    message?: string;
    note_id?: string;
    note_role?: CollaboratorRole;
  },
): Promise<InvitationOut> {
  return api<InvitationOut>("auth", `/tenants/${id}/invitations`, {
    method: "POST",
    json: body,
    credentials: true,
  });
}

export function resendInvitation(id: string, invitationId: string): Promise<InvitationOut> {
  return api<InvitationOut>("auth", `/tenants/${id}/invitations/${invitationId}/resend`, {
    method: "POST",
    credentials: true,
  });
}

export function revokeInvitation(id: string, invitationId: string): Promise<void> {
  return api<void>("auth", `/tenants/${id}/invitations/${invitationId}`, {
    method: "DELETE",
    credentials: true,
  });
}
