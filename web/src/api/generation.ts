// The document engine's status for one note (Sprint 33/37).
//
// The note is readable the whole time this is running — generation writes
// into sections the author has not touched, and never over their words.
// The client polls only while the run is live.
import { api, apiBlob, BASES } from "./http";
import type { GeneratedItem, GenerationView } from "./types";

export function getGeneration(noteId: string): Promise<GenerationView> {
  return api<GenerationView>("note", `/v1/notes/${noteId}/generation`);
}

export function regenerate(noteId: string): Promise<{ id: string; status: string }> {
  return api<{ id: string; status: string }>("note", `/v1/notes/${noteId}/generation`, {
    method: "POST",
  });
}

/** Every line the engine wrote, with the words that prove it (Q5: one row
 *  per line). `current` = only the run the reader is looking at. */
export function getGeneratedItems(
  noteId: string,
  opts: { generation?: "current" | "all" } = {},
): Promise<GeneratedItem[]> {
  return api<GeneratedItem[]>("note", `/v1/notes/${noteId}/generated-items`, {
    query: opts.generation ? { generation: opts.generation } : undefined,
  });
}

export interface AudioClip {
  clip_id: string;
  clip_url: string;
  expires_at_unix: number;
}

/** A playable clip of the recording between two moments. The URL carries
 *  its own short-lived token, so an `<audio>` element can play it. */
export async function createClip(noteId: string, startMs: number, endMs: number): Promise<string> {
  const clip = await api<AudioClip>("note", "/v1/audio-clips", {
    method: "POST",
    json: { note_id: noteId, start_ms: Math.max(0, Math.round(startMs)), end_ms: Math.round(endMs) },
  });
  return clip.clip_url.startsWith("http") ? clip.clip_url : `${BASES.note}${clip.clip_url}`;
}

/** A key date as a calendar file (Q5). */
export function dateCalendarFile(noteId: string, itemKey: string): Promise<Blob> {
  return apiBlob("note", `/v1/notes/${noteId}/dates/${itemKey}.ics`);
}

/** Accept or reject a name the engine respelled (Q5). */
export function correctName(
  noteId: string,
  itemKey: string,
  params: {
    expected_version: number;
    action: "correction_accepted" | "correction_rejected";
    surface: string;
    canonical: string;
    source?: string;
  },
): Promise<{ item_key: string; version_number: number; line: string | null }> {
  return api("note", `/v1/notes/${noteId}/items/by-key/${itemKey}`, {
    method: "PATCH",
    json: { ...params, ...(params.action === "correction_rejected" ? { reason: "wrong_name" } : {}) },
  });
}
