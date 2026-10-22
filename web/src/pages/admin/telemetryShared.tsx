import type { ReactNode } from "react";
import { useAuth } from "../../auth/AuthContext";
import { ShieldIcon } from "../../components/icons";

/** The dev-only bootstrap account (telemetry-sprints/design/ADMIN.md §3). */
export const DEV_ADMIN_EMAIL = "admin@dev.notes-ai.test";

/** Platform admins only. Hiding is a convenience: the API refuses everyone else too. */
export function RequirePlatformAdmin({ children }: { children: ReactNode }) {
  const { me, identity } = useAuth();
  if (!me?.claims.roles.includes("platform_admin")) {
    return (
      <div className="doc">
        <div className="banner banner-info" role="alert">
          <ShieldIcon size={16} />
          <span className="grow">
            Not available. The telemetry dashboard is for platform admins.
          </span>
        </div>
      </div>
    );
  }
  return (
    <>
      {identity?.email === DEV_ADMIN_EMAIL && (
        <div className="banner banner-warn" role="status">
          <ShieldIcon size={16} />
          <span className="grow">Development admin account in use.</span>
        </div>
      )}
      {children}
    </>
  );
}

export function seconds(value: number | null | undefined): string {
  return value == null ? "—" : `${value.toFixed(2)} s`;
}

export function ratio(value: number | null | undefined): string {
  return value == null ? "—" : value.toFixed(3);
}

export function percent(value: number | null | undefined): string {
  return value == null ? "—" : `${(value * 100).toFixed(1)} %`;
}

export function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}
