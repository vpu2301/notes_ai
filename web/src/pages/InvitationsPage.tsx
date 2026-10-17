import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { acceptMyInvitation, declineMyInvitation, myInvitations } from "../api/account";
import { roleLabel, type MyInvitation } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { EmptyState } from "../components/EmptyState";
import { MailIcon } from "../components/icons";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toaster";
import { messageFor } from "../lib/errorCopy";
import { timeUntil } from "../lib/time";
import { useDocumentTitle } from "../lib/useDocumentTitle";

/** `/invitations` — workspaces that invited this address. Accept moves you there; Decline closes it. */
export function InvitationsPage() {
  useDocumentTitle("Invitations");
  const { enterWorkspace } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [items, setItems] = useState<MyInvitation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    myInvitations()
      .then((r) => live && setItems(r))
      .catch((err) => {
        if (!live) return;
        setItems([]);
        setError(messageFor(err));
      });
    return () => {
      live = false;
    };
  }, []);

  const accept = async (inv: MyInvitation) => {
    setBusy(inv.id);
    try {
      const joined = await acceptMyInvitation(inv.id);
      // Remounts the signed-in tree in the new workspace.
      await enterWorkspace(joined.token, inv.workspace_name);
      navigate("/");
    } catch (err) {
      toast.error(messageFor(err));
      setBusy(null);
    }
  };

  const decline = async (inv: MyInvitation) => {
    setBusy(inv.id);
    try {
      await declineMyInvitation(inv.id);
      setItems((prev) => prev?.filter((x) => x.id !== inv.id) ?? null);
    } catch (err) {
      toast.error(messageFor(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="doc">
      <div className="page-h">
        <h1>Invitations</h1>
      </div>
      {error && (
        <div className="banner banner-danger" role="alert">
          <span className="grow">{error}</span>
        </div>
      )}
      {items === null && (
        <div className="settings-stack-sm">
          <Skeleton height={52} />
        </div>
      )}
      {items !== null && items.length === 0 && !error && (
        <EmptyState
          icon={<MailIcon size={22} />}
          title="No open invitations"
          message="When someone invites you to a workspace, it shows up here."
        />
      )}
      {items !== null && items.length > 0 && (
        <div className="card settings-card">
          <div className="row-list">
            {items.map((inv) => (
              <div className="row" key={inv.id}>
                <div className="grow">
                  <div className="row-name">{inv.workspace_name}</div>
                  <span className="help">
                    {inv.inviter_display} invited you as {roleLabel(inv.role).toLowerCase()} · expires{" "}
                    {timeUntil(inv.expires_at)}
                  </span>
                </div>
                <div className="settings-actions">
                  <button className="btn ghost sm" disabled={busy !== null} onClick={() => void decline(inv)}>
                    Decline
                  </button>
                  <button className="btn moss sm" disabled={busy !== null} onClick={() => void accept(inv)}>
                    {busy === inv.id ? "Joining…" : "Accept"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
