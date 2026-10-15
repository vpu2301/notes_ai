// What a person may do with one note (W3). Hiding is a convenience: every write re-checks server-side.
import type { NoteLevel } from "../api/types";

/** An older server sends no level: everything stays offered, as before W3. */
export function canEditNote(level: NoteLevel | null | undefined): boolean {
  return !level || level === "manage" || level === "edit";
}

/** Share, visibility, links, delete: the author team and workspace managers. */
export function canManageNote(level: NoteLevel | null | undefined): boolean {
  return !level || level === "manage";
}

/** Commenting needs a server that knows about levels. */
export function canCommentNote(level: NoteLevel | null | undefined): boolean {
  return level === "manage" || level === "edit" || level === "comment";
}

const LABEL: Record<NoteLevel, string> = {
  manage: "Can manage",
  edit: "Can edit",
  comment: "Can comment",
  view: "Can view",
};

export function levelLabel(level: NoteLevel): string {
  return LABEL[level] ?? level;
}

/** The strip over a body the caller cannot change; null when they can. */
export function readOnlyStrip(level: NoteLevel | null | undefined): string | null {
  if (level === "comment") return "You can comment on this note";
  if (level === "view") return "You can view this note";
  return null;
}
