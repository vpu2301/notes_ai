import { useCallback, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import * as notifApi from "../api/notifications";
import type { NotificationItem } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { BellIcon, LogoutIcon, MicIcon, NotesIcon, PlusIcon } from "../components/icons";
import { relativeTime } from "../lib/time";

function initialsOf(name: string): string {
  const parts = name.trim().split(/[\s@.]+/).filter(Boolean);
  const first = parts[0]?.[0] ?? "?";
  const second = parts.length > 1 ? parts[1]?.[0] ?? "" : "";
  return (first + second).toUpperCase();
}

/** Closes the dropdown on any outside click. */
function useDismiss(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);
  return ref;
}

function NotificationBell() {
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[] | null>(null);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss(open, close);

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
          (prev) =>
            prev?.map((n) =>
              n.id === item.id ? { ...n, read_at: new Date().toISOString() } : n,
            ) ?? null,
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
              <button className="btn btn-ghost btn-sm" onClick={() => void onReadAll()}>
                Mark all read
              </button>
            )}
          </div>
          {items === null && <div className="notif-body" style={{ padding: 12 }}>Loading…</div>}
          {items !== null && items.length === 0 && (
            <div style={{ padding: "20px 12px", textAlign: "center", color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
              Nothing here yet — you're all caught up.
            </div>
          )}
          {items?.map((item) => (
            <button
              key={item.id}
              className={`notif ${item.read_at ? "read" : ""}`}
              onClick={() => void onItemClick(item)}
            >
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

function UserMenu() {
  const { me, displayName, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss(open, close);

  const onLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <div className="dropdown-host" ref={ref}>
      <button className="user-btn" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen((v) => !v)}>
        <span className="avatar" aria-hidden="true">
          {initialsOf(displayName)}
        </span>
        <span>{displayName}</span>
      </button>
      {open && (
        <div className="dropdown" role="menu" aria-label="Account">
          <div className="menu-head" style={{ display: "block" }}>
            <div style={{ color: "var(--ink)" }}>{displayName}</div>
            <div style={{ fontWeight: 400, marginTop: 2 }}>{me?.db_user?.email}</div>
          </div>
          <div className="menu-sep" />
          <button className="menu-item" role="menuitem" onClick={() => void onLogout()}>
            <LogoutIcon />
            Log out
          </button>
        </div>
      )}
    </div>
  );
}

export function AppShell() {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="wordmark">
          <span className="mark" aria-hidden="true">
            N
          </span>
          <span>
            Notes <span className="ai">AI</span>
          </span>
        </div>
        <nav className="nav" aria-label="Main">
          <NavLink to="/" end className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
            <NotesIcon />
            Notes
          </NavLink>
          <NavLink to="/capture" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
            <MicIcon />
            Capture
          </NavLink>
          <NavLink to="/new" className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
            <PlusIcon />
            New note
          </NavLink>
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <NotificationBell />
          <UserMenu />
        </header>
        <main className="content">
          <div className="content-inner">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
