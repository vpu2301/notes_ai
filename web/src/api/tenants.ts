// The workspace's own profile (auth-service `/tenants/{id}`), for the settings page (Sprint 23).
import { api } from "./http";
import type { TenantMember, TenantProfile } from "./types";

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

export function listMembers(id: string): Promise<TenantMember[]> {
  return api<{ items: TenantMember[] }>("auth", `/tenants/${id}/members`, { credentials: true }).then(
    (r) => r.items,
  );
}

/**
 * The address has to belong to an existing account: the server answers
 * 404 when nobody signed up with it yet, 409 when they are already in.
 */
export function addMember(id: string, email: string, role: string): Promise<TenantMember> {
  return api<TenantMember>("auth", `/tenants/${id}/members`, {
    method: "POST",
    json: { email, role },
    credentials: true,
  });
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
