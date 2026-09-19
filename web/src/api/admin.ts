// Workspace-admin reads (Sprint 22). Counts only — nothing here names a recipient.
import { api } from "./http";
import type { SharingPolicy, SharingStats } from "./types";

export function sharingStats(days: 30 | 90 = 30): Promise<SharingStats> {
  return api<SharingStats>("note", "/v1/admin/sharing/stats", { query: { days } });
}

// ── Sprint 23: the workspace's sharing policy ─────────────────────

export function getSharingPolicy(): Promise<SharingPolicy> {
  return api<SharingPolicy>("note", "/v1/admin/sharing/policy");
}

export function putSharingPolicy(policy: SharingPolicy): Promise<SharingPolicy> {
  return api<SharingPolicy>("note", "/v1/admin/sharing/policy", { method: "PUT", json: policy });
}

/** Every live link in the workspace, revoked. Irreversible; the page confirms first. */
export function revokeAllExternal(): Promise<{ notes: number }> {
  return api<{ notes: number }>("note", "/v1/admin/sharing/revoke-all", { method: "POST" });
}
