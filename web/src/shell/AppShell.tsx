import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { cachedTenants, listTenants, myInvitationsCached } from "../api/account";
import { createWorkspace, unarchiveWorkspace } from "../api/tenants";
import { ApiError } from "../api/http";
import { roleLabel, workspaceLabel, type TenantSummary } from "../api/types";
import type { SearchScope } from "../api/notes";
import * as notifApi from "../api/notifications";
import type { NotificationItem } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toaster";
import { createBlankNote } from "../lib/createBlankNote";
import { messageFor } from "../lib/errorCopy";
import { useDismiss } from "../lib/useDismiss";
import {
  BellIcon,
  ChevronDownIcon,
  CheckIcon,
  CloseIcon,
  MailIcon,
  FileTextIcon,
  LayersIcon,
  LogoutIcon,
  MicIcon,
  NotesIcon,
  MonitorIcon,
  SettingsIcon,
  MoonIcon,
  PlusIcon,
  SidebarIcon,
  SunIcon,
  UploadIcon,
  UserIcon,
  UsersIcon,
  ShareIcon,
} from "../components/icons";
import { relativeTime } from "../lib/time";
import { SpacePeople, useActiveSpace, WorkspaceMark } from "./SpaceHeader";
import { SpacesNav } from "./SpacesNav";
import { useTheme, type ThemePref } from "./theme";

const COLLAPSE_KEY = "notesai.sidebar.collapsed";

function initialsOf(name: string): string {
  const parts = name.trim().split(/[\s@.]+/).filter(Boolean);
  const first = parts[0]?.[0] ?? "?";
  const second = parts.length > 1 ? parts[1]?.[0] ?? "" : "";
  return (first + second).toUpperCase();
}

// ── Sidebar pieces ──────────────────────────────────────────────────────

const SCOPES: { scope: SearchScope; label: string; icon: ReactNode }[] = [
  { scope: "all", label: "All notes", icon: <NotesIcon size={16} /> },
  { scope: "mine", label: "My notes", icon: <UserIcon size={16} /> },
  { scope: "shared_with_me", label: "Shared with me", icon: <UsersIcon size={16} /> },
];

/** All notes / My notes / Shared with me, as the Mac sidebar; the home page reads the scope from `?scope=`.
 *  A guest's notes are the ones shared with them: one row, nothing to filter. */
function ScopeLinks({ collapsed, guest }: { collapsed: boolean; guest: boolean }) {
  const { pathname, search } = useLocation();
  const current = new URLSearchParams(search).get("scope") ?? "all";
  if (guest) return <SideLink to="/" end icon={<UsersIcon size={16} />} label="Shared with me" collapsed={collapsed} />;
  return (
    <>
      {SCOPES.map((s) => {
        const on = pathname === "/" && current === s.scope;
        return (
          <Link
            key={s.scope}
            to={s.scope === "all" ? "/" : `/?scope=${s.scope}`}
            className={`sb-link ${on ? "on" : ""}`}
            aria-current={on ? "page" : undefined}
            title={collapsed ? s.label : undefined}
          >
            {s.icon}
            <span className="sb-link-label">{s.label}</span>
          </Link>
        );
      })}
    </>
  );
}

function SideLink({
  to,
  end,
  icon,
  label,
  collapsed,
}: {
  to: string;
  end?: boolean;
  icon: ReactNode;
  label: string;
  collapsed: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) => `sb-link ${isActive ? "on" : ""}`}
      title={collapsed ? label : undefined}
    >
      {icon}
      <span className="sb-link-label">{label}</span>
    </NavLink>
  );
}

interface MenuAction {
  icon: ReactNode;
  label: string;
  kbd?: string;
  onClick: () => void;
}

/** The "create" split button. Menu is `fixed` so it escapes the collapsed rail's overflow clipping. */
function NewMenu({
  primary,
  actions,
  collapsed,
}: {
  primary: MenuAction;
  actions: MenuAction[];
  collapsed: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number; minWidth: number } | null>(null);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss<HTMLDivElement>(open, close);

  const toggle = () => {
    if (!open && ref.current) {
      const r = ref.current.getBoundingClientRect();
      setPos(
        collapsed
          ? { left: Math.round(r.right + 6), top: Math.round(r.top), minWidth: 240 }
          : { left: Math.round(r.left), top: Math.round(r.bottom + 6), minWidth: Math.max(240, Math.round(r.width)) },
      );
    }
    setOpen((v) => !v);
  };

  const items = collapsed ? [primary, ...actions] : actions;

  return (
    <div className={`sb-new ${collapsed ? "collapsed" : ""} ${open ? "open" : ""}`} ref={ref}>
      {collapsed ? (
        <button className="sb-new-main" onClick={toggle} title="Create" aria-label="Create" aria-haspopup="menu" aria-expanded={open}>
          <PlusIcon size={16} />
        </button>
      ) : (
        <>
          <button
            className="sb-new-main"
            onClick={primary.onClick}
            title={primary.kbd ? `${primary.label} (${primary.kbd})` : primary.label}
          >
            <PlusIcon size={16} />
            <span className="sb-link-label">{primary.label}</span>
          </button>
          <button
            className="sb-new-caret"
            onClick={toggle}
            title="More ways to start"
            aria-label="More ways to start"
            aria-haspopup="menu"
            aria-expanded={open}
          >
            <ChevronDownIcon size={14} />
          </button>
        </>
      )}
      {open && pos && (
        <div className="anchored-menu" role="menu" style={pos}>
          {items.map((it) => (
            <button
              key={it.label}
              className="anchored-menu-item"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                it.onClick();
              }}
            >
              {it.icon}
              <span className="anchored-menu-label">{it.label}</span>
              {it.kbd && <kbd>{it.kbd}</kbd>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ThemeSeg({ pref, onChange }: { pref: ThemePref; onChange: (p: ThemePref) => void }) {
  const opts: { v: ThemePref; icon: ReactNode; title: string }[] = [
    { v: "light", icon: <SunIcon />, title: "Light" },
    { v: "system", icon: <MonitorIcon />, title: "Follow system" },
    { v: "dark", icon: <MoonIcon />, title: "Dark" },
  ];
  return (
    <div className="seg-pill" role="group" aria-label="Appearance">
      {opts.map((o) => (
        <button
          key={o.v}
          className={pref === o.v ? "on" : ""}
          title={o.title}
          aria-pressed={pref === o.v}
          onClick={() => onChange(o.v)}
        >
          {o.icon}
        </button>
      ))}
    </div>
  );
}

/** One switcher row, from `GET /tenants` or, until it answers, `/auth/me` memberships. */
interface WorkspaceRow {
  id: string;
  name: string;
  kind?: string;
  role: string;
  /** Archived ones are listed (to their owners) apart, with Restore instead of a switch. */
  archived?: boolean;
}

/** `GET /tenants` (not `/auth/me` memberships): it carries display name and `is_active`. Shown even with one workspace.
 *  Mounted each time the menu opens, so a create, leave or dissolve is reflected on the next open. */
function WorkspaceSwitch({ onDone, onNew }: { onDone: () => void; onNew: () => void }) {
  const { me, memberships, activeTenantId, canSwitchWorkspaces, switchWorkspace } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [tenants, setTenants] = useState<TenantSummary[] | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);
  // A `409 legacy_session` answers the question once: the switcher goes.
  const [legacy, setLegacy] = useState(false);

  useEffect(() => {
    if (!canSwitchWorkspaces) return;
    let live = true;
    listTenants()
      .then((r) => live && setTenants(r.items))
      .catch(() => live && setTenants([]));
    return () => {
      live = false;
    };
  }, [canSwitchWorkspaces]);

  // Server order (Personal first); older servers omit `kind`, so `personal_tenant_id` fills it.
  const rows: WorkspaceRow[] = tenants
    ? tenants.map((t) => ({
        id: t.id,
        name: t.display_name || t.name,
        kind: t.kind ?? (t.id === me?.personal_tenant_id ? "personal" : undefined),
        role: t.my_role,
        archived: t.status === "archived",
      }))
    : memberships.map((m) => ({ id: m.tenant_id, name: m.name, kind: m.kind, role: m.role }));
  // A session that cannot switch still names where it is.
  const fixed = !canSwitchWorkspaces || legacy;
  const open = rows.filter((r) => !r.archived);
  const archived = fixed ? [] : rows.filter((r) => r.archived);
  const shown = fixed ? open.filter((r) => r.id === activeTenantId) : open;
  const [restoring, setRestoring] = useState<string | null>(null);

  /** Back as it was; it then sits with the others, one click away. */
  const restore = async (t: WorkspaceRow) => {
    setRestoring(t.id);
    try {
      const back = await unarchiveWorkspace(t.id);
      setTenants((list) => list?.map((x) => (x.id === back.id ? { ...x, status: back.status, is_active: back.is_active } : x)) ?? list);
      toast.success(`${t.name} restored`);
    } catch (err) {
      toast.error(messageFor(err));
    } finally {
      setRestoring(null);
    }
  };

  const pick = async (t: WorkspaceRow) => {
    if (t.id === activeTenantId || switching) return;
    setSwitching(t.id);
    try {
      await switchWorkspace(t.id);
      onDone();
      navigate("/");
    } catch (err) {
      if (err instanceof ApiError && err.code === "legacy_session") setLegacy(true);
      toast.error(messageFor(err));
    } finally {
      setSwitching(null);
    }
  };

  return (
    <>
      {shown.map((t) => {
        const current = t.id === activeTenantId;
        return (
          <button
            key={t.id}
            className={`sb-user-menu-item ${current ? "current" : ""}`}
            role="menuitemradio"
            aria-checked={current}
            disabled={switching !== null || (fixed && !current)}
            onClick={() => void pick(t)}
          >
            <WorkspaceMark kind={t.kind} name={t.name} />
            <span className="grow ellipsis">{workspaceLabel(t)}</span>
            {t.role === "guest" && switching !== t.id ? (
              <span className="chip guest-badge">Guest</span>
            ) : (
              <span className="sb-user-menu-hint">{switching === t.id ? "Switching…" : roleLabel(t.role)}</span>
            )}
            {current && <CheckIcon size={13} />}
          </button>
        );
      })}
      {archived.length > 0 && (
        <>
          <div className="sb-user-menu-sep" />
          <div className="sb-user-menu-label">Archived</div>
          {archived.map((t) => (
            <div key={t.id} className="sb-user-menu-row archived">
              <WorkspaceMark kind={t.kind} name={t.name} />
              <span className="grow ellipsis">{t.name}</span>
              <button className="btn ghost sm" disabled={restoring !== null} onClick={() => void restore(t)}>
                {restoring === t.id ? "Restoring…" : "Restore"}
              </button>
            </div>
          ))}
        </>
      )}
      {!fixed && (
        <>
          <div className="sb-user-menu-sep" />
          <button className="sb-user-menu-item" role="menuitem" onClick={onNew}>
            <PlusIcon size={14} />
            <span>New workspace…</span>
          </button>
        </>
      )}
    </>
  );
}

/** Name it, Enter, and you are in it — on the Members page, ready to invite. */
function NewWorkspaceDialog({ onClose }: { onClose: () => void }) {
  const { switchWorkspace } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, busy]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createWorkspace(trimmed);
      // Remounts the signed-in tree, this dialog included.
      await switchWorkspace(created.id);
      navigate("/settings/members?first=1");
    } catch (err) {
      setError(messageFor(err));
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <form className="modal" role="dialog" aria-modal="true" aria-label="New workspace" onSubmit={(e) => void submit(e)}>
        <div className="modal-h">
          <h2>New workspace</h2>
          <p>A shared home for a team's notes. You can invite people next.</p>
        </div>
        <div className="modal-b">
          <label className="field">
            <span className="label">Name</span>
            <input
              autoFocus
              maxLength={80}
              placeholder="Sunrise Studio"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
            />
          </label>
          {error && (
            <div className="banner banner-danger" role="alert">
              <span className="grow">{error}</span>
            </div>
          )}
        </div>
        <div className="modal-f">
          <button type="button" className="btn ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={busy || !name.trim()}>
            {busy ? "Creating…" : "Create"}
          </button>
        </div>
      </form>
    </div>
  );
}

/** The sidebar head: where am I, and the one click to go elsewhere. */
export function WorkspaceMenu({ collapsed }: { collapsed: boolean }) {
  const { me, identity, memberships, activeTenantId } = useAuth();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss<HTMLDivElement>(open, close);
  const active = memberships.find((m) => m.tenant_id === activeTenantId) ?? me?.active_membership ?? null;
  const name = active ? workspaceLabel(active) : "Notes AI";
  // A guest's "Guest in …" already says the role.
  const role = active && active.role !== "guest" ? roleLabel(active.role) : null;

  // `fixed`, like NewMenu: the sidebar clips overflow.
  const toggle = () => {
    if (!open && ref.current) {
      const r = ref.current.getBoundingClientRect();
      setPos(
        collapsed
          ? { left: Math.round(r.right + 6), top: Math.round(r.top) }
          : { left: Math.round(r.left), top: Math.round(r.bottom + 6) },
      );
    }
    setOpen((v) => !v);
  };

  return (
    <div className="sb-ws-wrap" ref={ref}>
      <button
        className={`sb-ws ${open ? "open" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        title={collapsed ? name : "Switch workspace"}
        onClick={toggle}
      >
        <WorkspaceMark kind={active?.kind} name={name} />
        {!collapsed && (
          <>
            <span className="sb-ws-text">
              <span className="sb-ws-name">{name}</span>
              {role && <span className="sb-ws-role">{role}</span>}
            </span>
            <ChevronDownIcon size={13} />
          </>
        )}
      </button>
      {open && pos && (
        <div className="sb-user-menu down" role="menu" aria-label="Workspaces" style={pos}>
          {identity?.email && (
            <div className="sb-user-menu-head">
              <span>{identity.email}</span>
            </div>
          )}
          <WorkspaceSwitch
            onDone={close}
            onNew={() => {
              setOpen(false);
              setCreating(true);
            }}
          />
        </div>
      )}
      {creating && <NewWorkspaceDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

/** "You joined <name>" — after an accepted invitation, wherever it was accepted. */
function JoinedBanner() {
  const { joinedWorkspace, dismissJoined } = useAuth();
  if (!joinedWorkspace) return null;
  return (
    <div className="banner banner-ok ws-moved" role="status">
      <CheckIcon size={15} />
      <span className="grow">
        You joined <strong>{joinedWorkspace}</strong>.
      </span>
      <button className="icon-btn" aria-label="Dismiss" onClick={dismissJoined}>
        <CloseIcon size={14} />
      </button>
    </div>
  );
}

/** The session moved in another tab: this one refuses requests (`http.ts`) until it follows. */
export function WorkspaceMovedStrip() {
  const { workspaceMoved, memberships, followWorkspace } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  if (!workspaceMoved) return null;
  // A workspace made in the other tab may not be in this tab's memberships: the last `GET /tenants` names it
  // (no new request: everything but `/auth/*` is held back now).
  const known = memberships.find((m) => m.tenant_id === workspaceMoved.to);
  const listed = cachedTenants().find((t) => t.id === workspaceMoved.to);
  const name = known
    ? workspaceLabel(known)
    : listed
      ? workspaceLabel({ kind: listed.kind, name: listed.display_name || listed.name, role: listed.my_role })
      : null;
  const follow = async () => {
    setBusy(true);
    try {
      await followWorkspace();
      navigate("/");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="banner banner-warn ws-moved" role="status">
      <span className="grow">
        This session switched to {name ? <strong>{name}</strong> : "another workspace"} in another tab.
      </span>
      <button className="btn moss sm" onClick={() => void follow()} disabled={busy}>
        Continue there
      </button>
    </div>
  );
}

/** Open invitations to this person: on mount and on window focus, from a five-minute cache. Zero while unknown. */
function useOpenInvitations(): number {
  const onList = useLocation().pathname === "/invitations";
  const [count, setCount] = useState(0);
  useEffect(() => {
    let live = true;
    const load = () =>
      myInvitationsCached()
        .then((items) => live && setCount(items.length))
        .catch(() => {
          /* keep the last count; a missing dot is harmless */
        });
    void load();
    window.addEventListener("focus", load);
    return () => {
      live = false;
      window.removeEventListener("focus", load);
    };
  }, [onList]);
  return count;
}

function AccountMenu({ collapsed, onSignOut }: { collapsed: boolean; onSignOut: () => void }) {
  const { pref, setPref } = useTheme();
  // `identity`, not `db_user`: AuthContext already reconciles the `/auth/me` shape.
  const { identity, displayName } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss<HTMLDivElement>(open, close);
  const email = identity?.email ?? "";
  const invitations = useOpenInvitations();

  return (
    <div className="sb-user-wrap" ref={ref}>
      <button
        className={`sb-user ${open ? "open" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        title={collapsed ? displayName : "Account menu"}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="avatar" aria-hidden="true">
          {initialsOf(displayName)}
          {invitations > 0 && <span className="avatar-dot" />}
        </span>
        {!collapsed && (
          <>
            <span className="sb-user-name">{displayName}</span>
            <ChevronDownIcon size={14} />
          </>
        )}
      </button>
      {open && (
        <div className={`sb-user-menu ${collapsed ? "collapsed" : ""}`} role="menu" aria-label="Account">
          <div className="sb-user-menu-head">
            <strong>{displayName}</strong>
            {email && <span>{email}</span>}
          </div>
          <div className="sb-user-menu-sep" />
          {invitations > 0 && (
            <button
              className="sb-user-menu-item"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                navigate("/invitations");
              }}
            >
              <MailIcon size={14} />
              <span className="grow">Invitations ({invitations})</span>
            </button>
          )}
          <button
            className="sb-user-menu-item"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              navigate("/settings/account");
            }}
          >
            <SettingsIcon size={14} />
            <span>Settings</span>
          </button>
          <div className="sb-user-menu-row">
            {pref === "dark" ? <MoonIcon size={14} /> : pref === "light" ? <SunIcon size={14} /> : <MonitorIcon size={14} />}
            <span className="grow">Appearance</span>
            <ThemeSeg pref={pref} onChange={setPref} />
          </div>
          <div className="sb-user-menu-sep" />
          <button
            className="sb-user-menu-item danger"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onSignOut();
            }}
          >
            <LogoutIcon size={14} />
            <span>Sign out</span>
          </button>
        </div>
      )}
    </div>
  );
}

// ── Topbar pieces ───────────────────────────────────────────────────────

function NotificationBell() {
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[] | null>(null);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss<HTMLDivElement>(open, close);

  const poll = useCallback(async () => {
    try {
      const r = await notifApi.unreadCount();
      setCount(r.unread_count);
    } catch {
      /* keep the last known count; the service may be down */
    }
  }, []);

  useEffect(() => {
    void poll();
    const t = window.setInterval(() => void poll(), 30_000);
    return () => window.clearInterval(t);
  }, [poll]);

  const openFeed = async () => {
    setOpen((v) => !v);
    if (!open) {
      try {
        const page = await notifApi.feed(15);
        setItems(page.items);
        setCount(page.unread_count);
      } catch {
        setItems([]);
      }
    }
  };

  const onItemClick = async (item: NotificationItem) => {
    if (!item.read_at) {
      try {
        const r = await notifApi.markRead(item.id);
        setCount(r.unread_count);
        setItems(
          (prev) => prev?.map((n) => (n.id === item.id ? { ...n, read_at: new Date().toISOString() } : n)) ?? null,
        );
      } catch {
        /* non-fatal */
      }
    }
  };

  const onReadAll = async () => {
    try {
      const r = await notifApi.markAllRead();
      setCount(r.unread_count);
      setItems((prev) => prev?.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })) ?? null);
    } catch {
      /* non-fatal */
    }
  };

  return (
    <div className="dropdown-host" ref={ref}>
      <button
        className="icon-btn"
        aria-label={count > 0 ? `Notifications, ${count} unread` : "Notifications"}
        aria-expanded={open}
        onClick={() => void openFeed()}
      >
        <BellIcon />
        {count > 0 && <span className="count">{count > 99 ? "99+" : count}</span>}
      </button>
      {open && (
        <div className="dropdown dropdown-wide" role="menu" aria-label="Notifications">
          <div className="menu-head">
            <span>Notifications</span>
            {count > 0 && (
              <button className="btn ghost sm" onClick={() => void onReadAll()}>
                Mark all read
              </button>
            )}
          </div>
          {items === null && <div className="menu-empty">Loading…</div>}
          {items !== null && items.length === 0 && <div className="menu-empty">You're all caught up.</div>}
          {items?.map((item) => (
            <button key={item.id} className={`notif ${item.read_at ? "read" : ""}`} onClick={() => void onItemClick(item)}>
              <span className="dot" aria-hidden="true" />
              <span style={{ minWidth: 0 }}>
                <div className="notif-title">{item.title}</div>
                <div className="notif-body">{item.body_text}</div>
                <div className="notif-time">{relativeTime(item.created_at)}</div>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** "3 Days Labs ▾ · Workspace" at the head of every page, as the Mac's title-bar row: the name opens the switcher. */
function TopbarSpace() {
  const { identity } = useAuth();
  const { name, kind, personal } = useActiveSpace();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss<HTMLDivElement>(open, close);
  if (!name) return null;
  return (
    <div className="tb-space" role="group" aria-label={`${personal ? "Private" : "Workspace"}: ${name}`}>
      <div className="dropdown-host" ref={ref}>
        <button
          className={`tb-space-btn ${open ? "open" : ""}`}
          aria-haspopup="menu"
          aria-expanded={open}
          title="Switch workspace"
          onClick={() => setOpen((v) => !v)}
        >
          <WorkspaceMark kind={kind} name={name} />
          <span className="tb-space-name">{name}</span>
          <ChevronDownIcon size={13} />
        </button>
        {open && (
          <div className="dropdown tb-space-menu" role="menu" aria-label="Workspaces">
            {identity?.email && (
              <div className="sb-user-menu-head">
                <span>{identity.email}</span>
              </div>
            )}
            <WorkspaceSwitch
              onDone={close}
              onNew={() => {
                setOpen(false);
                setCreating(true);
              }}
            />
          </div>
        )}
      </div>
      <span className="tb-space-kind">{personal ? "Private · only you" : "Workspace"}</span>
      {creating && <NewWorkspaceDialog onClose={() => setCreating(false)} />}
    </div>
  );
}

/** Route → topbar title, after the workspace label. Pages that need a richer crumb own their heading. */
function titleFor(pathname: string): string {
  if (pathname.startsWith("/meeting/new")) return "New meeting";
  if (pathname.startsWith("/new")) return "New from template";
  return "";
}

function TopBar({ scroller }: { scroller: React.RefObject<HTMLDivElement> }) {
  const { pathname } = useLocation();
  const title = titleFor(pathname);
  const [stuck, setStuck] = useState(false);

  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const onScroll = () => setStuck(el.scrollTop > 2);
    onScroll();
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [scroller]);

  return (
    <header className={`tb ${stuck ? "is-stuck" : ""}`}>
      <TopbarSpace />
      {title && (
        <div className="tb-title">
          <span className="tb-space-sep" aria-hidden="true">·</span>
          {title}
        </div>
      )}
      <div className="tb-spacer" />
      <div className="tb-actions">
        <SpacePeople />
      </div>
    </header>
  );
}

// ── Sign-out confirmation ───────────────────────────────────────────────

function SignOutDialog({ onCancel, onConfirm, busy }: { onCancel: () => void; onConfirm: () => void; busy: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel, busy]);

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && !busy && onCancel()}>
      <div className="modal" role="alertdialog" aria-modal="true" aria-label="Sign out?">
        <div className="modal-h">
          <h2>Sign out?</h2>
          <p>Your current session will end. Unsaved changes may be lost.</p>
        </div>
        <div className="modal-f">
          <button className="btn ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button className="btn danger" onClick={onConfirm} disabled={busy} autoFocus>
            {busy ? "Signing out…" : "Sign out"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── The shell ───────────────────────────────────────────────────────────

export function AppShell() {
  const navigate = useNavigate();
  const { activeRole, logout, me } = useAuth();
  // A guest reaches only notes shared with them: nothing to record, file or set up here.
  const guest = activeRole === "guest";
  const toast = useToast();
  const scroller = useRef<HTMLDivElement>(null);

  // "Blank note" makes the note straight away and opens it — no picker.
  const blankInFlight = useRef(false);
  const newBlankNote = useCallback(async () => {
    if (blankInFlight.current) return;
    blankInFlight.current = true;
    try {
      navigate(`/notes/${await createBlankNote()}`);
    } catch (err) {
      toast.error(messageFor(err));
    } finally {
      blankInFlight.current = false;
    }
  }, [navigate, toast]);

  const [collapsed, setCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  const [confirmOut, setConfirmOut] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const onSignOut = async () => {
    setSigningOut(true);
    try {
      await logout();
    } finally {
      setSigningOut(false);
      setConfirmOut(false);
      navigate("/login");
    }
  };

  // Keyboard: N → new meeting, B → blank note (outside text fields).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t?.matches("input, textarea, select, [contenteditable]")) return;
      if (e.metaKey || e.ctrlKey || e.altKey || guest) return;
      if (e.key === "n") {
        e.preventDefault();
        navigate("/meeting/new");
      } else if (e.key === "b") {
        e.preventDefault();
        void newBlankNote();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate, newBlankNote, guest]);

  return (
    <div className="app">
      <aside className={`sb ${collapsed ? "collapsed" : ""}`}>
        <div className="sb-head">
          <button
            className="sb-toggle"
            onClick={() => setCollapsed((v) => !v)}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            <SidebarIcon size={17} />
          </button>
          <WorkspaceMenu collapsed={collapsed} />
          <NotificationBell />
        </div>

        {!guest && (
          <NewMenu
            collapsed={collapsed}
            primary={{ icon: <MicIcon size={14} />, label: "New meeting", kbd: "N", onClick: () => navigate("/meeting/new") }}
            actions={[
              { icon: <FileTextIcon size={14} />, label: "Blank note", kbd: "B", onClick: () => void newBlankNote() },
              { icon: <UploadIcon size={14} />, label: "Upload a recording", onClick: () => navigate("/meeting/new?mode=upload") },
              { icon: <LayersIcon size={14} />, label: "New from template…", onClick: () => navigate("/new") },
            ]}
          />
        )}

        <nav className="sb-nav" aria-label="Main">
          <ScopeLinks collapsed={collapsed} guest={guest} />
          {(activeRole === "owner" || activeRole === "admin") && (
            /* counts only; the API refuses everyone else */
            <SideLink to="/admin/sharing" icon={<ShareIcon size={16} />} label="Sharing" collapsed={collapsed} />
          )}
          {me?.claims.roles.includes("platform_admin") && (
            <SideLink to="/admin/dashboard" icon={<LayersIcon size={16} />} label="Telemetry" collapsed={collapsed} />
          )}
          {!guest && <SpacesNav collapsed={collapsed} />}
        </nav>

        <div className="sb-spacer" />

        <div className="sb-foot">
          <AccountMenu collapsed={collapsed} onSignOut={() => setConfirmOut(true)} />
        </div>
      </aside>

      <div className="app-main" ref={scroller}>
        <TopBar scroller={scroller} />
        <WorkspaceMovedStrip />
        <JoinedBanner />
        <main className="page">
          <Outlet />
        </main>
      </div>

      {confirmOut && <SignOutDialog busy={signingOut} onCancel={() => setConfirmOut(false)} onConfirm={() => void onSignOut()} />}
    </div>
  );
}
