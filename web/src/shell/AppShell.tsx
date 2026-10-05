import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { listTenants } from "../api/account";
import { ApiError } from "../api/http";
import type { TenantSummary } from "../api/types";
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
  ShareIcon,
} from "../components/icons";
import { relativeTime } from "../lib/time";
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

/**
 * The single "create" control: a primary action plus a caret that drops the
 * other ways to start. Menu is `fixed` off the trigger so it escapes the
 * sidebar's overflow clipping when the rail is collapsed.
 */
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

/**
 * The workspaces this account belongs to, read when the menu first opens.
 * `GET /tenants` rather than the memberships on `/auth/me`: the tenant
 * list carries the display name and `is_active`, which is what the
 * switcher shows, and it is the same call the Mac and iPhone apps make.
 */
function WorkspaceSwitch({ onDone }: { onDone: () => void }) {
  const { activeTenantId, canSwitchWorkspaces, switchWorkspace } = useAuth();
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

  if (!canSwitchWorkspaces || legacy || !tenants || tenants.length < 2) return null;

  const pick = async (t: TenantSummary) => {
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
      <div className="sb-user-menu-label">Workspace</div>
      {tenants.map((t) => {
        const current = t.id === activeTenantId;
        return (
          <button
            key={t.id}
            className={`sb-user-menu-item ${current ? "current" : ""}`}
            role="menuitemradio"
            aria-checked={current}
            disabled={switching !== null}
            onClick={() => void pick(t)}
          >
            <span className="sb-ws-mark" aria-hidden="true">
              {initialsOf(t.display_name || t.name)}
            </span>
            <span className="grow ellipsis">{t.display_name || t.name}</span>
            {current ? (
              <CheckIcon size={13} />
            ) : (
              switching === t.id && <span className="sb-user-menu-hint">Switching…</span>
            )}
          </button>
        );
      })}
      <div className="sb-user-menu-sep" />
    </>
  );
}

function AccountMenu({ collapsed, onSignOut }: { collapsed: boolean; onSignOut: () => void }) {
  const { pref, setPref } = useTheme();
  // `identity`, not `db_user`: IDX-B2 deletes the per-tenant `users` row,
  // and `AuthContext` already reconciles whichever shape `/auth/me` sends.
  const { identity, displayName } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss<HTMLDivElement>(open, close);
  const email = identity?.email ?? "";

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
          <WorkspaceSwitch onDone={close} />
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

/** Route → topbar title. Pages that need a richer crumb own their heading. */
function titleFor(pathname: string): string {
  // The home page, a space and a note carry their own heading.
  if (pathname === "/" || pathname.startsWith("/spaces/") || pathname.startsWith("/notes/")) return "";
  if (pathname.startsWith("/meeting/new")) return "New meeting";
  if (pathname.startsWith("/new")) return "New from template";
  return "Notes AI";
}

function TopBar({ scroller }: { scroller: React.RefObject<HTMLDivElement> }) {
  const { pathname } = useLocation();
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
      <div className="tb-title">
        {titleFor(pathname)}
      </div>
      <div className="tb-spacer" />
      <div className="tb-actions">
        <NotificationBell />
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
  const { activeRole, logout } = useAuth();
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
      if (e.metaKey || e.ctrlKey || e.altKey) return;
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
  }, [navigate, newBlankNote]);

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
          {!collapsed && (
            <NavLink to="/" className="sb-wordmark" title="Notes AI">
              Notes AI
            </NavLink>
          )}
        </div>

        <NewMenu
          collapsed={collapsed}
          primary={{ icon: <MicIcon size={14} />, label: "New meeting", kbd: "N", onClick: () => navigate("/meeting/new") }}
          actions={[
            { icon: <FileTextIcon size={14} />, label: "Blank note", kbd: "B", onClick: () => void newBlankNote() },
            { icon: <UploadIcon size={14} />, label: "Upload a recording", onClick: () => navigate("/meeting/new?mode=upload") },
            { icon: <LayersIcon size={14} />, label: "New from template…", onClick: () => navigate("/new") },
          ]}
        />

        <nav className="sb-nav" aria-label="Main">
          <SideLink to="/" end icon={<NotesIcon size={16} />} label="All notes" collapsed={collapsed} />
          {(activeRole === "owner" || activeRole === "admin") && (
            /* Sprint 22: the workspace's recipient loop, counts only; the API refuses everyone else. */
            <SideLink to="/admin/sharing" icon={<ShareIcon size={16} />} label="Sharing" collapsed={collapsed} />
          )}
          <SpacesNav collapsed={collapsed} />
        </nav>

        <div className="sb-spacer" />

        <div className="sb-foot">
          <AccountMenu collapsed={collapsed} onSignOut={() => setConfirmOut(true)} />
        </div>
      </aside>

      <div className="app-main" ref={scroller}>
        <TopBar scroller={scroller} />
        <main className="page">
          <Outlet />
        </main>
      </div>

      {confirmOut && <SignOutDialog busy={signingOut} onCancel={() => setConfirmOut(false)} onConfirm={() => void onSignOut()} />}
    </div>
  );
}
