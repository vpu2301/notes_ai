import type { SearchHit } from "../api/types";
import { GlobeIcon, LockIcon, UsersIcon } from "./icons";

/** The widest audience a note reaches — what the list's badge says. */
export type NoteAccess =
  | { kind: "private" }
  | { kind: "shared"; count: number }
  | { kind: "workspace" }
  | { kind: "public" };

/** Null when the server predates the sharing fields. */
export function noteAccess(hit: SearchHit): NoteAccess | null {
  if (!hit.visibility) return null;
  if (hit.has_public_link) return { kind: "public" };
  if (hit.visibility === "workspace") return { kind: "workspace" };
  const count = hit.shared_with_count ?? 0;
  return count > 0 ? { kind: "shared", count } : { kind: "private" };
}

export function accessLabel(access: NoteAccess): string {
  switch (access.kind) {
    case "private":
      return "Private";
    case "shared":
      return `Shared with ${access.count}`;
    case "workspace":
      return "Workspace";
    case "public":
      return "Public";
  }
}

export function accessHelp(access: NoteAccess): string {
  switch (access.kind) {
    case "private":
      return "Private — only the note's authors can open it";
    case "shared":
      return `Private — shared with ${access.count} ${access.count === 1 ? "person" : "people"} in the workspace`;
    case "workspace":
      return "Visible to everyone in the workspace";
    case "public":
      return "Public — anyone with the link can open it";
  }
}

/**
 * Private or public, shown while the pointer is on the row (CSS). On a
 * touch screen, with no pointer to hover, the glyph stays on its own.
 */
export function AccessBadge({ access }: { access: NoteAccess }) {
  const Icon = access.kind === "public" ? GlobeIcon : access.kind === "workspace" ? UsersIcon : LockIcon;
  return (
    <span className={`access-badge${access.kind === "public" ? " public" : ""}`} title={accessHelp(access)}>
      <Icon size={11} />
      <span className="access-label">{accessLabel(access)}</span>
    </span>
  );
}
