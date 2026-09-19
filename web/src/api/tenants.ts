// The workspace's own profile (auth-service `/tenants/{id}`), for the settings page (Sprint 23).
import { api } from "./http";
import type { TenantProfile } from "./types";

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
