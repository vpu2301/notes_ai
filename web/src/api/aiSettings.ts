// Who processes this workspace's meetings, and what it may cost. Members read; admins change.
import { api } from "./http";
import type { AiSettings, AiSettingsUpdate } from "./types";

export function getAiSettings(): Promise<AiSettings> {
  return api<AiSettings>("note", "/v1/ai/settings");
}

export function putAiSettings(body: AiSettingsUpdate): Promise<AiSettings> {
  return api<AiSettings>("note", "/v1/ai/settings", { method: "PUT", json: body });
}
