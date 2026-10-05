// Who processes this workspace's meetings, and what it may cost
// (Sprint 37). Every member may read it; only an admin may change it,
// and the API refuses the rest — the page only hides what it knows will
// be refused.
import { api } from "./http";
import type { AiSettings, AiSettingsUpdate } from "./types";

export function getAiSettings(): Promise<AiSettings> {
  return api<AiSettings>("note", "/v1/ai/settings");
}

export function putAiSettings(body: AiSettingsUpdate): Promise<AiSettings> {
  return api<AiSettings>("note", "/v1/ai/settings", { method: "PUT", json: body });
}
