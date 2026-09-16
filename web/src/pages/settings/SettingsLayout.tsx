import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";

/**
 * `/settings` — the account's own screens, inside the app shell.
 *
 * The Devices tab appears only for a workspace manager. That is a
 * convenience, not a boundary: `routers/credentials.py` re-checks the role
 * on every call, and a member who reaches the route by typing it gets a
 * 403 rendered as a message rather than a broken page.
 */
export function SettingsLayout() {
  const { activeRole } = useAuth();
  const manages = activeRole === "owner" || activeRole === "admin";

  return (
    <div className="page-h-stack">
      <div className="page-h">
        <div>
          <h1>Settings</h1>
          <p className="sub">Your account, how you sign in, and the devices in this workspace.</p>
        </div>
      </div>

      {/* The house tab is the segmented pill (components.css), marked with
          `on` rather than react-router's default `active` class. */}
      <nav className="tabs" aria-label="Settings sections">
        <SettingsTab to="/settings/account" label="Account" />
        <SettingsTab to="/settings/security" label="Security" />
        {manages && <SettingsTab to="/settings/devices" label="Room devices" />}
      </nav>

      <Outlet />
    </div>
  );
}

function SettingsTab({ to, label }: { to: string; label: string }) {
  return (
    <NavLink to={to} className={({ isActive }) => `tab ${isActive ? "on" : ""}`}>
      {label}
    </NavLink>
  );
}
