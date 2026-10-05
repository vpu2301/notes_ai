import type { ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";
import {
  BuildingIcon,
  CreditCardIcon,
  LockIcon,
  MonitorIcon,
  ShieldIcon,
  UserIcon,
  UsersIcon,
} from "../../components/icons";
import { useDocumentTitle } from "../../lib/useDocumentTitle";

// The heading over the page, as the menu names it.
const HEADINGS: Record<string, string> = {
  account: "Profile",
  security: "Security",
  data: "Data & AI",
  members: "Members",
  devices: "Room devices",
  workspace: "Branding & sharing",
  billing: "Billing",
};

const TAB_TITLES: Record<string, string> = {
  account: "Account settings",
  security: "Security settings",
  data: "Data & AI settings",
  members: "Members",
  devices: "Room devices",
  workspace: "Workspace settings",
  billing: "Billing",
};

/** `/settings` shell. Hiding manager rows is a convenience, not a boundary: every route re-checks server-side. */
export function SettingsLayout() {
  const { activeRole } = useAuth();
  // Membership role (owner/admin), else the platform role on the user row.
  const manages = activeRole === "owner" || activeRole === "admin" || activeRole === "tenant_admin";
  const { pathname } = useLocation();
  const section = pathname.split("/")[2] ?? "";
  useDocumentTitle(TAB_TITLES[section] ?? "Settings");

  return (
    <div className="settings-layout">
      <nav className="settings-nav" aria-label="Settings sections">
        <h1 className="settings-nav-title">Settings</h1>
        <div className="settings-nav-group">
          <span className="settings-nav-label">Account</span>
          <SettingsLink to="/settings/account" label="Profile" icon={<UserIcon />} />
          <SettingsLink to="/settings/security" label="Security" icon={<LockIcon />} />
        </div>
        <div className="settings-nav-group">
          <span className="settings-nav-label">Workspace</span>
          {/* Every member, not only a manager. */}
          <SettingsLink to="/settings/data" label="Data & AI" icon={<ShieldIcon />} />
          {manages && <SettingsLink to="/settings/members" label="Members" icon={<UsersIcon />} />}
          {manages && (
            <SettingsLink to="/settings/devices" label="Room devices" icon={<MonitorIcon size={16} />} />
          )}
          {manages && (
            <SettingsLink to="/settings/workspace" label="Branding & sharing" icon={<BuildingIcon />} />
          )}
          {manages && <SettingsLink to="/settings/billing" label="Billing" icon={<CreditCardIcon />} />}
        </div>
      </nav>

      <div className="settings-main">
        {HEADINGS[section] && <h2 className="settings-page-title">{HEADINGS[section]}</h2>}
        <Outlet />
      </div>
    </div>
  );
}

function SettingsLink({ to, label, icon }: { to: string; label: string; icon: ReactNode }) {
  return (
    <NavLink to={to} className={({ isActive }) => `settings-link ${isActive ? "on" : ""}`}>
      {icon}
      <span>{label}</span>
    </NavLink>
  );
}
