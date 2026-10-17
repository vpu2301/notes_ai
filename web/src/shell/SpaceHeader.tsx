import type React from "react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listMembers } from "../api/tenants";
import { roleLabel, workspaceLabel, type TenantMember } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { HomeIcon, UserPlusIcon } from "../components/icons";
import { speakerInitials, speakerTint } from "../lib/speakers";

/** Personal workspaces get a house, team ones their first letter in a circle. */
export function WorkspaceMark({ kind, name }: { kind?: string; name: string }) {
  return (
    <span className={`sb-ws-mark ${kind === "personal" ? "personal" : ""}`} aria-hidden="true">
      {kind === "personal" ? <HomeIcon size={11} /> : (name.trim().charAt(0) || "?").toUpperCase()}
    </span>
  );
}

/** The active workspace as the topbar shows it: Personal is private, a team one is shared. */
export function useActiveSpace() {
  const { me, memberships, activeTenantId, activeRole } = useAuth();
  const active = memberships.find((m) => m.tenant_id === activeTenantId) ?? me?.active_membership ?? null;
  const personal = active?.kind === "personal" || (!!activeTenantId && me?.personal_tenant_id === activeTenantId);
  return {
    tenantId: activeTenantId,
    name: active ? workspaceLabel(active) : "",
    kind: personal ? "personal" : active?.kind,
    personal,
    guest: activeRole === "guest",
    manages: activeRole === "owner" || activeRole === "admin" || activeRole === "tenant_admin",
  };
}

const SHOWN = 4;

function nameOf(m: TenantMember): string {
  return m.display_name || m.email || "Member";
}

/** Who is in this workspace, and the one click to invite. Nothing in Personal: it is just you. */
export function SpacePeople() {
  const { tenantId, name, personal, guest, manages } = useActiveSpace();
  const navigate = useNavigate();
  const [members, setMembers] = useState<TenantMember[]>([]);
  // Hover or keyboard focus on the avatars opens the roster card.
  const [peek, setPeek] = useState(false);

  // A guest cannot read the roster, and Personal has nobody else in it: no request either way.
  const loads = !!tenantId && !personal && !guest;
  useEffect(() => {
    if (!loads || !tenantId) {
      setMembers([]);
      return;
    }
    let live = true;
    listMembers(tenantId)
      .then((r) => live && setMembers(r.items.filter((m) => m.status === "active")))
      .catch(() => live && setMembers([]));
    return () => {
      live = false;
    };
  }, [loads, tenantId]);

  if (!tenantId || personal) return null;
  return (
    <>
      {members.length > 0 && (
        <span
          className="tb-people-host"
          onMouseEnter={() => setPeek(true)}
          onMouseLeave={() => setPeek(false)}
          onFocus={() => setPeek(true)}
          onBlur={() => setPeek(false)}
        >
          <button
            className="tb-people"
            aria-label={`${members.length} ${members.length === 1 ? "person" : "people"} in ${name}`}
            onClick={() => navigate("/settings/members")}
          >
            {members.slice(0, SHOWN).map((m) => (
              <span
                key={m.user_sub}
                className="speaker-avatar presence-avatar"
                style={{ "--tint": speakerTint(nameOf(m)) } as React.CSSProperties}
                aria-hidden="true"
              >
                {speakerInitials(nameOf(m))}
              </span>
            ))}
            {members.length > SHOWN && (
              <span className="presence-more" aria-hidden="true">
                +{members.length - SHOWN}
              </span>
            )}
          </button>
          {peek && (
            <div className="people-card" role="tooltip">
              <div className="people-card-head">
                {members.length} {members.length === 1 ? "person" : "people"} in {name}
              </div>
              <ul>
                {members.map((m) => (
                  <li key={m.user_sub}>
                    <span
                      className="speaker-avatar"
                      style={{ "--tint": speakerTint(nameOf(m)) } as React.CSSProperties}
                      aria-hidden="true"
                    >
                      {speakerInitials(nameOf(m))}
                    </span>
                    <span className="people-card-name">{nameOf(m)}</span>
                    <span className="people-card-role">{roleLabel(m.role)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </span>
      )}
      {manages && (
        <button className="tb-invite" onClick={() => navigate("/settings/members?invite=1")}>
          <UserPlusIcon size={14} />
          Invite
        </button>
      )}
    </>
  );
}
