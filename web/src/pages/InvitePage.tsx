import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { acceptInvitation, lookupInvitation } from "../api/account";
import { ApiError } from "../api/http";
import { roleLabel, type InvitationLookup } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { messageFor } from "../lib/errorCopy";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { Banner, LoginShell } from "./auth/LoginShell";

/**
 * `/invite/:token` — outside `RequireAuth`. The token only shows the invitation; joining needs
 * a session for the invited address, which the server checks. `?accept=1` is the way back from
 * `/login`: the person already chose to continue, so the page accepts without another click.
 */
export function InvitePage() {
  useDocumentTitle("Invitation");
  const { token = "" } = useParams();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { status, identity, enterWorkspace, logout } = useAuth();
  const [invitation, setInvitation] = useState<InvitationLookup | null>(null);
  const [screen, setScreen] = useState<"loading" | "ready" | "invalid" | "mismatch">("loading");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const autoAccepted = useRef(false);

  useEffect(() => {
    let live = true;
    lookupInvitation(token)
      .then((found) => {
        if (!live) return;
        setInvitation(found);
        setScreen("ready");
      })
      .catch((err) => {
        if (!live) return;
        if (err instanceof ApiError && err.status === 404) {
          setScreen("invalid");
        } else {
          setError(messageFor(err));
          setScreen("ready");
        }
      });
    return () => {
      live = false;
    };
  }, [token]);

  const accept = useCallback(async () => {
    if (!invitation) return;
    setBusy(true);
    setError(null);
    try {
      const joined = await acceptInvitation(token);
      // The server already moved the session; this adopts its token and raises the banner.
      await enterWorkspace(joined.token, invitation.workspace_name);
      navigate("/", { replace: true });
    } catch (err) {
      const code = err instanceof ApiError ? err.code : undefined;
      if (code === "invitation_email_mismatch") setScreen("mismatch");
      else if (code === "invitation_not_found") setScreen("invalid");
      else setError(messageFor(err));
      setBusy(false);
    }
  }, [invitation, token, enterWorkspace, navigate]);

  useEffect(() => {
    if (status !== "authenticated" || !invitation || params.get("accept") !== "1" || autoAccepted.current) return;
    autoAccepted.current = true;
    void accept();
  }, [status, invitation, params, accept]);

  /** `/login`, pre-filled when the link carried the address, back here to accept. */
  const continueToSignIn = () => {
    const query = new URLSearchParams({ next: `/invite/${token}?accept=1` });
    const email = params.get("email");
    if (email) query.set("email", email);
    navigate(`/login?${query.toString()}`);
  };

  const signOutAndContinue = async () => {
    setBusy(true);
    await logout();
    continueToSignIn();
  };

  if (screen === "invalid") {
    return (
      <LoginShell
        title="This invitation is no longer valid"
        subtitle="Ask the person who invited you for a new one."
      >
        <Link className="btn ghost lg block" to="/">
          Go to Notes AI
        </Link>
      </LoginShell>
    );
  }

  if (screen === "loading" || status === "restoring" || !invitation) {
    return (
      <LoginShell title="Invitation" subtitle={error ? undefined : "Opening your invitation…"}>
        {error && <Banner>{error}</Banner>}
      </LoginShell>
    );
  }

  if (screen === "mismatch") {
    return (
      <LoginShell
        title="This invitation is for someone else"
        subtitle={
          <>
            You're signed in as <strong>{identity?.email}</strong>. Sign out and continue as{" "}
            <strong>{invitation.email_masked}</strong>?
          </>
        }
      >
        <button className="btn primary lg block" disabled={busy} onClick={() => void signOutAndContinue()}>
          Sign out and continue
        </button>
        <p className="login-foot">
          <Link className="link-btn" to="/">
            Not now
          </Link>
        </p>
      </LoginShell>
    );
  }

  return (
    <LoginShell
      title={`Join ${invitation.workspace_name}`}
      subtitle={
        <>
          {invitation.inviter_display} invited you to <strong>{invitation.workspace_name}</strong> as{" "}
          {article(roleLabel(invitation.role))} {roleLabel(invitation.role).toLowerCase()}
          {invitation.note_title ? (
            <>
              {" "}
              to see <strong>{invitation.note_title}</strong>
            </>
          ) : null}
          .
        </>
      }
    >
      {error && <Banner>{error}</Banner>}
      {status === "authenticated" ? (
        <button className="btn primary lg block" disabled={busy} onClick={() => void accept()}>
          {busy ? "Joining…" : `Join ${invitation.workspace_name}`}
        </button>
      ) : (
        <button className="btn primary lg block" onClick={continueToSignIn}>
          Continue with {invitation.email_masked}
        </button>
      )}
      <p className="login-hint">
        {status === "authenticated"
          ? `Signed in as ${identity?.email ?? "you"}.`
          : "We'll email you a code — no password needed."}
      </p>
    </LoginShell>
  );
}

function article(word: string): string {
  return /^[aeiou]/i.test(word) ? "an" : "a";
}
