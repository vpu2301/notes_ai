import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../../api/http";
import { addMember, listMembers, removeMember, setMemberRole } from "../../api/tenants";
import type { TenantMember } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Select } from "../../components/Select";
import { Skeleton } from "../../components/Skeleton";
import { useToast } from "../../components/Toaster";
import { messageFor } from "../../lib/errorCopy";
import { Problem } from "./AccountSettingsPage";

/** The roles a manager can hand out. Owner is earned by creating the workspace. */
const ROLES = [
  { value: "member", label: "Member" },
  { value: "admin", label: "Admin" },
] as const;

const ROLE_LABEL: Record<string, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
  assistant: "Assistant",
  viewer: "Viewer",
};

/** `/settings/members`. Adding links an EXISTING account (404 otherwise); owner/admin only. */
export function MembersSettingsPage() {
  const { activeTenantId, identity, activeRole } = useAuth();
  const toast = useToast();
  const [members, setMembers] = useState<TenantMember[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<string>("member");
  const [addError, setAddError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<TenantMember | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    if (!activeTenantId) return;
    try {
      setMembers(await listMembers(activeTenantId));
      setError(null);
    } catch (err) {
      setMembers([]);
      setError(messageFor(err));
    }
  }, [activeTenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!activeTenantId) return null;

  const signupLink = `${window.location.origin}/signup`;
  const isOwner = activeRole === "owner";

  const add = async (e: FormEvent) => {
    e.preventDefault();
    const address = email.trim();
    if (!address) return;
    setBusy(true);
    setAddError(null);
    try {
      await addMember(activeTenantId, address, role);
      setEmail("");
      toast.success(`${address} is in the workspace`);
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setAddError("Nobody has signed up with that address yet. Send them the sign-up link, then add them.");
      } else if (err instanceof ApiError && err.status === 409) {
        setAddError("That person is already in this workspace.");
      } else {
        setAddError(messageFor(err));
      }
    } finally {
      setBusy(false);
    }
  };

  const changeRole = async (m: TenantMember, next: string) => {
    if (next === m.role) return;
    setBusy(true);
    try {
      const updated = await setMemberRole(activeTenantId, m.user_sub, next);
      setMembers((prev) => prev?.map((x) => (x.user_sub === m.user_sub ? { ...x, role: updated.role } : x)) ?? null);
    } catch (err) {
      toast.error(err instanceof ApiError && err.status === 409 ? "A workspace needs at least one owner." : messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (m: TenantMember) => {
    setBusy(true);
    try {
      await removeMember(activeTenantId, m.user_sub);
      toast.success(`${nameOf(m)} was removed`);
      setRemoving(null);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError && err.status === 409 ? "A workspace needs at least one owner." : messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(signupLink);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast.error("Could not copy. Select the link and copy it yourself.");
    }
  };

  return (
    <div className="settings-stack">
      <div className="card settings-card">
        <div className="settings-card-h">
          <div>
            <h2 className="settings-h">Add people</h2>
            <span className="help">Anyone with an account can be added by their sign-in address.</span>
          </div>
        </div>
        <form className="settings-pad settings-stack-sm" onSubmit={(e) => void add(e)}>
          <div className="settings-actions">
            <label className="field grow" style={{ flex: 1, minWidth: 220 }}>
              <span className="label">Email</span>
              <input
                type="email"
                autoComplete="off"
                placeholder="name@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={busy}
              />
            </label>
            <label className="field">
              <span className="label">Role</span>
              <Select label="Role" value={role} options={[...ROLES]} onChange={setRole} disabled={busy} />
            </label>
            <button className="btn primary" type="submit" disabled={busy || !email.trim()} style={{ alignSelf: "flex-end" }}>
              Add
            </button>
          </div>
          {addError && <Problem>{addError}</Problem>}
          <p className="help">
            Not signed up yet? Send them this link — they'll be in <strong>{signupLink}</strong>{" "}
            <button type="button" className="link-btn" onClick={() => void copyLink()}>
              {copied ? "Copied" : "Copy link"}
            </button>
          </p>
        </form>
      </div>

      <div className="card settings-card">
        <div className="settings-card-h">
          <div>
            <h2 className="settings-h">In this workspace</h2>
            {members && (
              <span className="help">
                {members.length} {members.length === 1 ? "person" : "people"}
              </span>
            )}
          </div>
        </div>

        {members === null && (
          <div className="settings-pad settings-stack-sm">
            <Skeleton height={38} />
            <Skeleton height={38} />
          </div>
        )}

        {error && (
          <div className="settings-pad">
            <Problem>{error}</Problem>
          </div>
        )}

        {members !== null && members.length > 0 && (
          <div className="row-list">
            {members.map((m) => {
              const me = m.user_sub === identity?.id;
              // Owners can only be changed by another owner; nobody edits themselves here.
              const editable = !me && (m.role !== "owner" || isOwner);
              return (
                <div className="row" key={m.user_sub}>
                  <div className="grow">
                    <div className="row-name">
                      {nameOf(m)}
                      {me && <span className="pill">You</span>}
                      {m.status !== "active" && <span className="pill">{m.status}</span>}
                    </div>
                    {m.email && m.display_name && <span className="help">{m.email}</span>}
                  </div>
                  <div className="settings-actions">
                    {editable && m.role !== "owner" ? (
                      <Select
                        label={`Role for ${nameOf(m)}`}
                        value={m.role}
                        options={[...ROLES]}
                        onChange={(next) => void changeRole(m, next)}
                        disabled={busy}
                        variant="text"
                      />
                    ) : (
                      <span className="help">{ROLE_LABEL[m.role] ?? m.role}</span>
                    )}
                    {editable && (
                      <button className="btn ghost sm" disabled={busy} onClick={() => setRemoving(m)}>
                        Remove
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {removing && (
        <ConfirmDialog
          title={`Remove ${nameOf(removing)}?`}
          subtitle="They lose access to every note in this workspace right away. Their account stays."
          confirmLabel="Remove"
          confirmDanger
          busy={busy}
          onCancel={() => setRemoving(null)}
          onConfirm={() => void remove(removing)}
        />
      )}
    </div>
  );
}

function nameOf(m: TenantMember): string {
  return m.display_name || m.email || "Member";
}
