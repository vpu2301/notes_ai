// How this workspace wants its notes written — the workspace text, one per meeting type that
// extends it (N4), and one note's own. Members read; admins check, save and clear; any editor
// of a note may write that note differently.
import { api } from "./http";
import type { AiInstructions, InstructionsScope } from "./types";

const path = (scope: InstructionsScope = "workspace") =>
  scope === "workspace" ? "/v1/ai/instructions" : `/v1/ai/instructions/${scope}`;

export function getAiInstructions(scope?: InstructionsScope): Promise<AiInstructions> {
  return api<AiInstructions>("note", path(scope));
}

export function putAiInstructions(
  body: { text: string },
  scope?: InstructionsScope,
): Promise<AiInstructions> {
  return api<AiInstructions>("note", path(scope), { method: "PUT", json: body });
}

/** What saving this text would do; nothing is written. */
export function previewAiInstructions(
  body: { text: string },
  scope?: InstructionsScope,
): Promise<AiInstructions> {
  return api<AiInstructions>("note", `${path(scope)}/preview`, { method: "POST", json: body });
}

export function deleteAiInstructions(scope?: InstructionsScope): Promise<void> {
  return api<void>("note", path(scope), { method: "DELETE" });
}

// ── One note's instructions ("Write this note differently") ─────────

const notePath = (noteId: string) => `/v1/notes/${noteId}/instructions`;

export function getNoteInstructions(noteId: string): Promise<AiInstructions> {
  return api<AiInstructions>("note", notePath(noteId));
}

/** Saved with the workspace's and the meeting type's texts; the caller rewrites the note. */
export function putNoteInstructions(
  noteId: string,
  body: { text: string },
): Promise<AiInstructions> {
  return api<AiInstructions>("note", notePath(noteId), { method: "PUT", json: body });
}

export function previewNoteInstructions(
  noteId: string,
  body: { text: string },
): Promise<AiInstructions> {
  return api<AiInstructions>("note", `${notePath(noteId)}/preview`, { method: "POST", json: body });
}

export function deleteNoteInstructions(noteId: string): Promise<void> {
  return api<void>("note", notePath(noteId), { method: "DELETE" });
}
