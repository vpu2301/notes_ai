import type React from "react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "../../api/http";
import {
  archiveWorkspace,
  dissolveWorkspace,
  invite,
  leaveWorkspace,
  listInvitations,
  listMembers,
  removeMember,
  resendInvitation,
  revokeInvitation,
  setMemberRole,
} from "../../api/tenants";
import {
  roleLabel,
  workspaceLabel,
  type InvitationOut,
  type InvitationRole,
  type SeatMeter,
  type TenantMember,
} from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { CharCount, ChipResults, EmailChips, useEmailChips, type ChipResult } from "../../components/EmailChips";
import { Select } from "../../components/Select";
import { Skeleton } from "../../components/Skeleton";
import { useToast } from "../../components/Toaster";
import { messageFor } from "../../lib/errorCopy";
import { collabTint } from "../../lib/speakers";
import { timeUntil } from "../../lib/time";
import { Problem } from "./AccountSettingsPage";

/** The roles a manager can hand out. Owner is earned by creating the workspace. */
const ROLES = [
  { value: "member", label: "Member" },
  { value: "admin", label: "Admin" },
  { value: "viewer", label: "Viewer" },
] as const;

/** An owner may also make or unmake owners; nobody else sees the option. */
const OWNER_ROLES = [{ value: "owner", label: "Owner" }, ...ROLES];

const LAST_OWNER = "A workspace needs at least one owner.";

/**
 * `/settings/members`. Everyone sees the roster and can leave; owners and admins invite and manage
 * (the API re-checks every call, and step-up 403s are answered by `http.ts`). `?first=1` is the
 * landing right after "New workspace…".
 */
export function MembersSettingsPage() {
  const { activeTenantId, identity, activeRole, memberships, me, enterWorkspace, switchWorkspace } = useAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [members, setMembers] = useState<TenantMember[] | null>(null);
  const [seats, setSeats] = useState<SeatMeter | null>(null);
  const [pending, setPending] = useState<InvitationOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [removing, setRemoving] = useState<TenantMember | null>(null);
  const [leaving, setLeaving] = useState(false);
  const [archiving, setArchiving] = useState(false);
  /** Delete first offers archiving; only "Delete anyway" reaches the type-the-name step. */
  const [deleteOffer, setDeleteOffer] = useState(false);
  const [dissolving, setDissolving] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const [dialogError, setDialogError] = useState<string | null>(null);
  /** Rows the server refused to demote or remove (409, last owner), with why. */
  const [ownerBlocked, setOwnerBlocked] = useState<Record<string, string>>({});

  const active = memberships.find((m) => m.tenant_id === activeTenantId) ?? me?.active_membership ?? null;
  const personal = active?.kind === "personal" || (!!activeTenantId && me?.personal_tenant_id === activeTenantId);
  const workspaceName = active ? workspaceLabel(active) : "";
  const isOwner = activeRole === "owner";
  const manages = isOwner || activeRole === "admin" || activeRole === "tenant_admin";

  const load = useCallback(async () => {
    if (!activeTenantId) return;
    try {
      const list = await listMembers(activeTenantId);
      setMembers(list.items);
      setSeats(list.seat_meter ?? null);
      setError(null);
    } catch (err) {
      setMembers([]);
      setError(messageFor(err));
    }
    if (manages && !personal) {
      try {
        setPending(await listInvitations(activeTenantId));
      } catch {
        /* the roster is the page; a missing pending list is not worth a banner */
      }
    }
  }, [activeTenantId, manages, personal]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!activeTenantId) return null;

  const others = (members ?? []).filter((m) => m.user_sub !== identity?.id && m.status === "active");
  const activeOwners = (members ?? []).filter((m) => m.role === "owner" && m.status === "active").length;
  const lastOwner = isOwner && members !== null && activeOwners <= 1;

  /** The server's answer replaces any row with the same id (a re-invite is a resend). */
  const upsertPending = (inv: InvitationOut) =>
    setPending((prev) => [inv, ...prev.filter((p) => p.id !== inv.id)]);

  const changeRole = async (m: TenantMember, next: string) => {
    if (next === m.role) return;
    setBusy(true);
    try {
      const updated = await setMemberRole(activeTenantId, m.user_sub, next);
      setMembers((prev) => prev?.map((x) => (x.user_sub === m.user_sub ? { ...x, role: updated.role } : x)) ?? null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // The server's last-owner rule: kept on the row as its tooltip.
        setOwnerBlocked((prev) => ({ ...prev, [m.user_sub]: LAST_OWNER }));
        toast.error(LAST_OWNER);
      } else {
        toast.error(messageFor(err));
      }
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
      if (err instanceof ApiError && err.status === 409) {
        setOwnerBlocked((prev) => ({ ...prev, [m.user_sub]: LAST_OWNER }));
        toast.error(LAST_OWNER);
      } else {
        toast.error(messageFor(err));
      }
    } finally {
      setBusy(false);
    }
  };

  const resend = async (inv: InvitationOut) => {
    setBusy(true);
    try {
      upsertPending(await resendInvitation(activeTenantId, inv.id));
      toast.success(`Sent again to ${inv.email}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "not_pending") {
        setPending((prev) => prev.filter((p) => p.id !== inv.id));
      }
      toast.error(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (inv: InvitationOut) => {
    setBusy(true);
    try {
      await revokeInvitation(activeTenantId, inv.id);
      setPending((prev) => prev.filter((p) => p.id !== inv.id));
      toast.success(`Invitation to ${inv.email} revoked`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "not_pending") {
        setPending((prev) => prev.filter((p) => p.id !== inv.id));
      }
      toast.error(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const leave = async () => {
    setBusy(true);
    setDialogError(null);
    try {
      const { token } = await leaveWorkspace(activeTenantId);
      toast.success(`You left ${workspaceName}`);
      // The session is already in Personal; this remounts the signed-in tree there.
      await enterWorkspace(token);
      navigate("/");
    } catch (err) {
      setDialogError(messageFor(err));
      setBusy(false);
    }
  };

  const archive = async () => {
    setBusy(true);
    setDialogError(null);
    try {
      const { token } = await archiveWorkspace(activeTenantId);
      toast.success(`${workspaceName} was archived — restore it from the workspace menu`);
      // The session is already in Personal when the server says so; otherwise move there.
      if (token) {
        await enterWorkspace(token);
      } else {
        const home = memberships.find((m) => m.kind === "personal")?.tenant_id ?? me?.personal_tenant_id;
        if (home) await switchWorkspace(home);
      }
      navigate("/");
    } catch (err) {
      setDialogError(messageFor(err));
      setBusy(false);
    }
  };

  const dissolve = async () => {
    setBusy(true);
    setDialogError(null);
    try {
      await dissolveWorkspace(activeTenantId, confirmName);
      toast.success(`${workspaceName} was deleted`);
      const home = memberships.find((m) => m.kind === "personal")?.tenant_id ?? me?.personal_tenant_id;
      if (home) await switchWorkspace(home);
      navigate("/");
    } catch (err) {
      setDialogError(messageFor(err));
      setBusy(false);
    }
  };

  return (
    <div className="settings-stack">
      {personal && (
        <div className="card settings-card">
          <div className="settings-card-h">
            <div>
              <h2 className="settings-h">Your personal workspace</h2>
              <span className="help">
                Only you are in it. To work with others, create a workspace from the workspace menu at the top of
                the sidebar.
              </span>
            </div>
          </div>
        </div>
      )}

      {manages && !personal && (
        <InviteCard
          tenantId={activeTenantId}
          first={params.get("first") === "1"}
          focus={params.get("invite") === "1"}
          onInvited={upsertPending}
        />
      )}

      <div className="card settings-card">
        <div className="settings-card-h">
          <div>
            <h2 className="settings-h">In this workspace</h2>
            {members && <SeatLine seats={seats} people={members.filter((m) => m.status === "active").length} manages={manages} />}
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
              const self = m.user_sub === identity?.id;
              const left = m.status === "suspended" && !!m.left_at;
              // Owners can only be changed by another owner; nobody edits themselves here.
              const editable = manages && !self && !left && (m.role !== "owner" || isOwner);
              const roleOptions = isOwner ? OWNER_ROLES : [...ROLES];
              return (
                <div className="row" key={m.user_sub} title={ownerBlocked[m.user_sub]}>
                  <span
                    className="avatar member-avatar collab-avatar"
                    style={{ "--tint": collabTint(nameOf(m)) } as React.CSSProperties}
                    aria-hidden="true"
                  >
                    {nameOf(m).trim().charAt(0).toUpperCase()}
                  </span>
                  <div className="grow">
                    <div className="row-name">
                      {nameOf(m)}
                      {self && <span className="pill">You</span>}
                      {left ? (
                        <span className="pill">Left {new Date(m.left_at!).toLocaleDateString()}</span>
                      ) : (
                        m.status !== "active" && <span className="pill">{m.status}</span>
                      )}
                    </div>
                    {m.email && m.display_name && <span className="help">{m.email}</span>}
                    {ownerBlocked[m.user_sub] && <span className="help">{ownerBlocked[m.user_sub]}</span>}
                  </div>
                  <div className="settings-actions">
                    {/* Guest and legacy assistant are shown, never picked here; owner only by an owner. */}
                    {editable && roleOptions.some((r) => r.value === m.role) ? (
                      <Select
                        label={`Role for ${nameOf(m)}`}
                        value={m.role}
                        options={roleOptions}
                        onChange={(next) => void changeRole(m, next)}
                        disabled={busy}
                        variant="text"
                      />
                    ) : (
                      <span className="help">{roleLabel(m.role)}</span>
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

      {manages && pending.length > 0 && (
        <div className="card settings-card">
          <div className="settings-card-h">
            <div>
              <h2 className="settings-h">Pending</h2>
              <span className="help">Invited, not joined yet.</span>
            </div>
          </div>
          <div className="row-list" aria-label="Pending invitations">
            {pending.map((inv) => {
              const notSent = inv.sent_count === 0 || inv.delivery === "queued_failed";
              return (
                <div className="row" key={inv.id}>
                  <div className="grow">
                    <div className="row-name">{inv.email}</div>
                    <span className="help">
                      {roleLabel(inv.role)} · {notSent ? "Not sent" : `sent ${inv.sent_count}×`} · expires{" "}
                      {timeUntil(inv.expires_at)}
                    </span>
                  </div>
                  <div className="settings-actions">
                    <button className="btn ghost sm" disabled={busy} onClick={() => void resend(inv)}>
                      Resend
                    </button>
                    <button className="btn ghost sm" disabled={busy} onClick={() => void revoke(inv)}>
                      Revoke
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {!personal && (
        <div className="card settings-card">
          <div className="settings-card-h">
            <div>
              <h2 className="settings-h">Leave workspace</h2>
              <span className="help">
                {lastOwner
                  ? "You're the only owner, so you can't leave. Make someone else an owner first."
                  : "You lose access to its notes. Your account and your personal workspace stay."}
              </span>
            </div>
            <button
              className="btn ghost sm"
              disabled={busy || lastOwner}
              onClick={() => {
                setDialogError(null);
                setLeaving(true);
              }}
            >
              Leave…
            </button>
          </div>
        </div>
      )}

      {isOwner && !personal && (
        <div className="card settings-card">
          <div className="settings-card-h">
            <div>
              <h2 className="settings-h">Archive or delete</h2>
              <span className="help">
                Archiving closes this workspace for everyone and keeps every note and member — restore it any time.
                Deleting removes it.
              </span>
            </div>
            <div className="row-actions">
              <button
                className="btn sm"
                disabled={busy}
                onClick={() => {
                  setDialogError(null);
                  setArchiving(true);
                }}
              >
                Archive…
              </button>
              <button
                className="btn danger sm"
                disabled={busy || members === null}
                onClick={() => {
                  setDialogError(null);
                  setDeleteOffer(true);
                }}
              >
                Delete…
              </button>
            </div>
          </div>
        </div>
      )}

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

      {leaving && (
        <ConfirmDialog
          title={`Leave ${workspaceName}?`}
          subtitle="You lose access to its notes right away. Someone there can invite you back."
          confirmLabel="Leave"
          confirmDanger
          busy={busy}
          error={dialogError}
          onCancel={() => setLeaving(false)}
          onConfirm={() => void leave()}
        />
      )}

      {archiving && (
        <ConfirmDialog
          title={`Archive ${workspaceName}?`}
          subtitle="Nobody can open it until you restore it. Notes and members stay as they are; open invitations are cancelled."
          confirmLabel="Archive"
          busy={busy}
          error={dialogError}
          onCancel={() => setArchiving(false)}
          onConfirm={() => void archive()}
        />
      )}

      {deleteOffer && (
        <DeleteOffer
          name={workspaceName}
          others={others.length}
          busy={busy}
          error={dialogError}
          onArchive={() => void archive()}
          onDelete={() => {
            setDeleteOffer(false);
            setConfirmName("");
            setDialogError(null);
            setDissolving(true);
          }}
          onCancel={() => setDeleteOffer(false)}
        />
      )}

      {dissolving && (
        <ConfirmDialog
          title={`Delete ${workspaceName}?`}
          subtitle="Nobody can open it or its notes afterwards."
          confirmLabel="Delete"
          confirmDanger
          busy={busy}
          confirmDisabled={confirmName !== workspaceName}
          error={dialogError}
          onCancel={() => setDissolving(false)}
          onConfirm={() => void dissolve()}
        >
          <label className="field">
            <span className="label">
              Type <strong>{workspaceName}</strong> to confirm
            </span>
            <input
              autoFocus
              autoComplete="off"
              value={confirmName}
              onChange={(e) => setConfirmName(e.target.value)}
              disabled={busy}
            />
          </label>
        </ConfirmDialog>
      )}
    </div>
  );
}

/** "4 of 3 free seats": display only; nothing blocks an invite on it. */
function SeatLine({ seats, people, manages }: { seats: SeatMeter | null; people: number; manages: boolean }) {
  if (!seats || seats.limit === null) {
    return (
      <span className="help">
        {people} {people === 1 ? "person" : "people"}
      </span>
    );
  }
  const over = seats.active > seats.limit;
  return (
    <span className="seat-meter">
      <span className="help">
        {seats.active} of {seats.limit} free seats
        {manages && (
          <>
            {" · "}
            <Link to="/settings/billing">Billing</Link>
          </>
        )}
      </span>
      <span
        className="meter"
        role="meter"
        aria-label="Seats used"
        aria-valuenow={seats.active}
        aria-valuemin={0}
        aria-valuemax={seats.limit}
      >
        <span
          className={`meter-fill${over ? " over" : ""}`}
          style={{ width: `${Math.min(100, (seats.active / Math.max(1, seats.limit)) * 100)}%` }}
        />
      </span>
    </span>
  );
}

const MESSAGE_MAX = 500;

/** Addresses as chips, one role, an optional note. Each address is its own invitation. */
function InviteCard({
  tenantId,
  first,
  focus,
  onInvited,
}: {
  tenantId: string;
  first: boolean;
  /** The topbar's Invite button lands here: the e-mail field takes focus. */
  focus: boolean;
  onInvited: (inv: InvitationOut) => void;
}) {
  const toast = useToast();
  const navigate = useNavigate();
  const box = useEmailChips();
  const [role, setRole] = useState<InvitationRole>("member");
  const [message, setMessage] = useState("");
  const [withMessage, setWithMessage] = useState(false);
  const [results, setResults] = useState<ChipResult[]>([]);
  const [busy, setBusy] = useState(false);

  const send = async (e: FormEvent) => {
    e.preventDefault();
    const to = box.collect();
    if (!to) return;
    setBusy(true);
    setResults([]);
    const failed: string[] = [];
    const lines: ChipResult[] = [];
    let sent = 0;
    // One at a time: the first call may open the reauth dialog; the rest ride on that proof.
    for (const email of to) {
      try {
        const inv = await invite(tenantId, { email, role, message: message.trim() || undefined });
        onInvited(inv);
        if (inv.delivery === "queued_failed") {
          lines.push({ email, ok: false, text: "Saved, but the email didn't go out. Resend it from Pending." });
        } else {
          sent += 1;
          lines.push({ email, ok: true, text: "Sent" });
        }
      } catch (err) {
        if (err instanceof ApiError && err.code === "already_member") {
          lines.push({ email, ok: true, text: messageFor(err) });
        } else {
          failed.push(email);
          lines.push({ email, ok: false, text: messageFor(err) });
        }
      }
    }
    box.setChips(failed);
    box.setDraft("");
    setResults(lines);
    if (sent > 0) toast.success(sent === 1 ? "Invitation sent" : `${sent} invitations sent`);
    if (failed.length === 0) {
      setMessage("");
      setWithMessage(false);
    }
    setBusy(false);
  };

  return (
    <div className="card settings-card">
      <div className="settings-card-h">
        <div>
          <h2 className="settings-h">{first ? "Invite your first teammate" : "Invite people"}</h2>
          <span className="help">They'll get an email from Notes AI. Nothing is shared until they accept.</span>
        </div>
      </div>
      <form className="settings-pad settings-stack-sm" onSubmit={(e) => void send(e)}>
        <div className="settings-actions">
          <div className="grow" style={{ flex: 1, minWidth: 220 }}>
            <EmailChips box={box} label="Email" placeholder="name@company.com" disabled={busy} autoFocus={first || focus} />
          </div>
          <Select
            label="Role"
            value={role}
            options={[...ROLES]}
            onChange={(v) => setRole(v as InvitationRole)}
            disabled={busy}
          />
          <button className="btn primary" type="submit" disabled={busy || !box.ready}>
            {busy ? "Sending…" : "Invite"}
          </button>
        </div>
        {withMessage ? (
          <>
            <textarea
              className="textarea"
              aria-label="Message"
              placeholder="Add a note to the email (optional)"
              maxLength={MESSAGE_MAX}
              rows={2}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              disabled={busy}
            />
            <CharCount value={message} max={MESSAGE_MAX} />
          </>
        ) : (
          <button type="button" className="link-btn" onClick={() => setWithMessage(true)}>
            Add a message
          </button>
        )}
        <ChipResults results={results} label="Invitation results" />
        {first && (
          <button type="button" className="link-btn" onClick={() => navigate("/")}>
            You can do this later
          </button>
        )}
      </form>
    </div>
  );
}

function nameOf(m: TenantMember): string {
  return m.display_name || m.email || "Member";
}

/** Delete asks first whether archiving would do: same result for everyone, and nothing is lost. */
function DeleteOffer({
  name,
  others,
  busy,
  error,
  onArchive,
  onDelete,
  onCancel,
}: {
  name: string;
  /** Other active members; deleting needs them gone first. */
  others: number;
  busy: boolean;
  error: string | null;
  onArchive: () => void;
  onDelete: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel, busy]);

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && !busy && onCancel()}>
      <div className="modal" role="alertdialog" aria-modal="true" aria-label={`Archive ${name} instead?`}>
        <div className="modal-h">
          <h2>Archive {name} instead?</h2>
          <p>
            Archiving closes it for everyone just like deleting, but keeps every note and member. You can restore it any
            time from the workspace menu.
          </p>
        </div>
        <div className="modal-b">
          <span className="help">
            {others > 0
              ? `To delete it, remove the ${others} other ${others === 1 ? "member" : "members"} first. Archiving needs nothing.`
              : "Deleting can't be undone from the app."}
          </span>
          {error && (
            <div className="banner banner-danger" role="alert">
              <span className="grow">{error}</span>
            </div>
          )}
        </div>
        <div className="modal-f">
          <button className="btn ghost danger-text" disabled={busy || others > 0} onClick={onDelete}>
            Delete anyway…
          </button>
          <span className="grow" />
          <button className="btn ghost" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
          <button className="btn moss" autoFocus disabled={busy} onClick={onArchive}>
            {busy ? "Archiving…" : "Archive instead"}
          </button>
        </div>
      </div>
    </div>
  );
}
