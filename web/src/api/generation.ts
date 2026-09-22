// The document engine's status for one note (Sprint 33/37).
//
// The note is readable the whole time this is running — generation writes
// into sections the author has not touched, and never over their words.
// The client polls only while the run is live.
import { api } from "./http";
import type { GeneratedItem, GenerationView } from "./types";

export function getGeneration(noteId: string): Promise<GenerationView> {
  return api<GenerationView>("note", `/v1/notes/${noteId}/generation`);
}

export function regenerate(noteId: string): Promise<{ id: string; status: string }> {
  return api<{ id: string; status: string }>("note", `/v1/notes/${noteId}/generation`, {
    method: "POST",
  });
}

/** Every verified fact behind the note, with the words that prove it. */
export function getGeneratedItems(noteId: string): Promise<GeneratedItem[]> {
  return api<GeneratedItem[]>("note", `/v1/notes/${noteId}/generated-items`);
}
