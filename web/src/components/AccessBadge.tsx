import { errorMessage } from "../api/http";
import { createPublicLink, revokePublicLink, setVisibility } from "../api/notes";
import type { SearchHit, SharingView } from "../api/types";
import { ChevronDownIcon, CloseIcon, GlobeIcon, LockIcon, UsersIcon } from "./icons";
import { Menu, type MenuItem } from "./Menu";
import { publicLinkUrl } from "./ShareDialog";
import { useToast } from "./Toaster";

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

/** The list row's sharing fields after a change made from its menu. */
export function withSharing(hit: SearchHit, view: SharingView): SearchHit {
  return {
    ...hit,
    visibility: view.visibility,
    shared_with_count: view.shared_with.length,
    has_public_link: view.public_link !== null,
  };
}

/**
 * Private or public, shown while the pointer is on the row (CSS): the lock
 * (or globe), the word, and a chevron that opens who-can-open-it. On a
 * touch screen, with no pointer to hover, the glyph stays on its own.
 * The server decides whether this person may change it; a refusal is a
 * toast.
 */
export function AccessMenu({
  hit,
  access,
  onChange,
}: {
  hit: SearchHit;
  access: NoteAccess;
  onChange: (view: SharingView) => void;
}) {
  const toast = useToast();
  const Icon = access.kind === "public" ? GlobeIcon : access.kind === "workspace" ? UsersIcon : LockIcon;
  const workspace = hit.visibility === "workspace";

  const run = async (work: () => Promise<SharingView>, done?: (view: SharingView) => Promise<void> | void) => {
    try {
      const view = await work();
      onChange(view);
      await done?.(view);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const items: MenuItem[] = [
    {
      label: "Private",
      icon: <LockIcon size={14} />,
      checked: !workspace,
      onClick: () => void (workspace && run(() => setVisibility(hit.note_id, "private"))),
    },
    {
      label: "Everyone in the workspace",
      icon: <UsersIcon size={14} />,
      checked: workspace,
      onClick: () => void (!workspace && run(() => setVisibility(hit.note_id, "workspace"))),
    },
    {
      label: hit.has_public_link ? "Copy public link" : "Create public link",
      icon: <GlobeIcon size={14} />,
      sep: true,
      onClick: () =>
        void run(
          () => createPublicLink(hit.note_id),
          async (view) => {
            if (!view.public_link) return;
            await navigator.clipboard.writeText(publicLinkUrl(view.public_link.path));
            toast.success("Public link copied");
          },
        ),
    },
  ];
  if (hit.has_public_link) {
    items.push({
      label: "Turn off public link",
      icon: <CloseIcon size={14} />,
      onClick: () => void run(() => revokePublicLink(hit.note_id)),
    });
  }

  return (
    <span className="access-menu" onClick={(e) => e.stopPropagation()}>
      <Menu
        anchored
        items={items}
        label={accessHelp(access)}
        triggerClassName={`access-badge${access.kind === "public" ? " public" : ""}`}
        trigger={
          <>
            <Icon size={11} />
            <span className="access-label">{accessLabel(access)}</span>
            <ChevronDownIcon size={10} />
          </>
        }
      />
    </span>
  );
}
