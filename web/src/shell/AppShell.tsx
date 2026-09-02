import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { errorMessage } from "../api/http";
import * as notifApi from "../api/notifications";
import type { NotificationItem } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useToast } from "../components/Toaster";
import { createBlankNote } from "../lib/createBlankNote";
import { useDismiss } from "../lib/useDismiss";
import {
  BellIcon,
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  FileTextIcon,
  LayersIcon,
  LogoutIcon,
  MicIcon,
  NotesIcon,
  MonitorIcon,
  MoonIcon,
  SunIcon,
  UploadIcon,
} from "../components/icons";
import { relativeTime } from "../lib/time";
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
    <div className={`sb-cta-split ${collapsed ? "collapsed" : ""}`} ref={ref}>
      {collapsed ? (
        <button className="sb-cta" onClick={toggle} title="Create" aria-haspopup="menu" aria-expanded={open}>
          <span className="sb-cta-icon">
            <MicIcon size={14} />
          </span>
        </button>
      ) : (
        <>
          <button
            className="sb-cta"
            onClick={primary.onClick}
            title={primary.kbd ? `${primary.label} (${primary.kbd})` : primary.label}
          >
            <span className="sb-cta-icon">{primary.icon}</span>
            <span className="sb-cta-label">{primary.label}</span>
          </button>
          <button
            className={`sb-cta sb-cta-caret ${open ? "open" : ""}`}
            onClick={toggle}
            title="More ways to start"
            aria-haspopup="menu"
            aria-expanded={open}
          >
            <ChevronDownIcon size={13} />
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
    <div className="seg-pill" role="group" aria-label="Theme">
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

function AccountMenu({ collapsed, onSignOut }: { collapsed: boolean; onSignOut: () => void }) {
  const { me, displayName } = useAuth();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss<HTMLDivElement>(open, close);
  const email = me?.db_user?.email ?? "";

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
            <span className="sb-user-info">
              <span className="sb-user-name">{displayName}</span>
              <span className="sb-user-role">{email || "Member"}</span>
            </span>
            {open ? <ChevronDownIcon /> : <ChevronRightIcon />}
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
  if (pathname === "/") return "Notes";
  if (pathname.startsWith("/meeting/new")) return "New meeting";
  if (pathname.startsWith("/new")) return "New from template";
  if (pathname.startsWith("/notes/")) return "Note";
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
      <div className="tb-title">{titleFor(pathname)}</div>
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
  const { logout } = useAuth();
  const { pref, setPref } = useTheme();
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
      toast.error(errorMessage(err));
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
        <div className="sb-brand">
          <NavLink to="/" className="sb-brand-inner" title="Notes AI">
            <span className="sb-brand-mark" aria-hidden="true">
              N
            </span>
            {!collapsed && (
              <span className="sb-wordmark">
                Notes <span className="ai">AI</span>
              </span>
            )}
          </NavLink>
          <button
            className="sb-toggle"
            onClick={() => setCollapsed((v) => !v)}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <ChevronRightIcon size={13} /> : <ChevronLeftIcon size={13} />}
          </button>
        </div>

        <NewMenu
          collapsed={collapsed}
          primary={{ icon: <MicIcon size={13} />, label: "New meeting", kbd: "N", onClick: () => navigate("/meeting/new") }}
          actions={[
            { icon: <FileTextIcon size={14} />, label: "Blank note", kbd: "B", onClick: () => void newBlankNote() },
            { icon: <UploadIcon size={14} />, label: "Upload a recording", onClick: () => navigate("/meeting/new?mode=upload") },
            { icon: <LayersIcon size={14} />, label: "New from template…", onClick: () => navigate("/new") },
          ]}
        />

        <nav className="sb-nav" aria-label="Main">
          <SideLink to="/" end icon={<NotesIcon size={14} />} label="Notes" collapsed={collapsed} />
        </nav>

        <div className="sb-spacer" />

        <div className="sb-foot">
          <div className="sb-controls">
            {collapsed ? (
              <button
                className="icon-btn"
                title="Toggle theme"
                aria-label="Toggle theme"
                onClick={() => setPref(pref === "dark" ? "light" : "dark")}
              >
                {pref === "dark" ? <MoonIcon /> : <SunIcon />}
              </button>
            ) : (
              <>
                <ThemeSeg pref={pref} onChange={setPref} />
                <span className="grow" />
              </>
            )}
          </div>
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
