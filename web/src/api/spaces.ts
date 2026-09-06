// Spaces — personal folders of notes, shared by every client (0021).

import { api } from "./http";
import type { Space, SpacesResponse } from "./types";

export async function listSpaces(): Promise<Space[]> {
  const res = await api<SpacesResponse>("note", "/v1/spaces");
  return res.spaces;
}

export function createSpace(name: string): Promise<Space> {
  return api<Space>("note", "/v1/spaces", { method: "POST", json: { name } });
}

export function renameSpace(id: string, name: string): Promise<Space> {
  return api<Space>("note", `/v1/spaces/${id}`, { method: "PUT", json: { name } });
}

/** Delete the space; the notes filed in it go back to "All notes". */
export function deleteSpace(id: string): Promise<void> {
  return api<void>("note", `/v1/spaces/${id}`, { method: "DELETE" });
}

/** File the note in a space; `null` takes it out of its space. */
export function fileNote(noteId: string, spaceId: string | null): Promise<void> {
  return api<void>("note", `/v1/notes/${noteId}/space`, {
    method: "PUT",
    json: { space_id: spaceId },
  });
}
