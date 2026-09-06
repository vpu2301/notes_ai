import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import * as authApi from "../../api/auth";
import { clearMailToken, mailToken } from "../../lib/mailLink";
import { messageWithRef } from "../../lib/errorCopy";
import { Banner, LoginShell } from "./LoginShell";
import { ResetPasswordPage } from "./ResetPasswordPage";

/**
 * `/account-recovery` — the "this wasn't me" link in a security email.
 *
 * Somebody clicking this believes their account has been taken. The page
 * therefore acts immediately on arrival rather than asking them to confirm:
 * `POST /auth/security/lockdown` ends every session, spends every
 * outstanding link, and hands back a fresh reset token — which drops
 * straight into the set-password step, with no second trip to the inbox.
 *
 * (This is the sprint's `/lockdown/done`, named for the route the server
 * actually mails.)
 */
export function AccountRecoveryPage() {
  const [token] = useState(() => mailToken("/account-recovery"));
  const [resetToken, setResetToken] = useState<string | null>(null);
  const [revoked, setRevoked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // The lockdown is single-use and StrictMode mounts effects twice in dev.
  const fired = useRef(false);

  useEffect(() => {
    if (!token || fired.current) return;
    fired.current = true;
    void (async () => {
      try {
        const result = await authApi.accountLockdown(token);
        clearMailToken();
        setRevoked(result.sessions_revoked);
        setResetToken(result.reset_token);
      } catch (err) {
        setError(messageWithRef(err));
      }
    })();
  }, [token]);

  if (!token && !resetToken) {
    return (
      <LoginShell
        title="Nothing to do here"
        subtitle="This page only works from the link in a security email."
      >
        <p className="login-foot">
          <Link className="link-btn" to="/reset">
            Reset your password
          </Link>
        </p>
      </LoginShell>
    );
  }

  if (error) {
    return (
      <LoginShell title="That link didn't work" subtitle="It may already have been used, or expired.">
        <Banner>{error}</Banner>
        <p className="login-foot">
          <Link className="link-btn" to="/reset">
            Reset your password instead
          </Link>
        </p>
      </LoginShell>
    );
  }

  if (resetToken) {
    return (
      <ResetPasswordPage
        token={resetToken}
        notice={
          revoked
            ? "Every session on this account has been signed out. Choose a new password to get back in."
            : "Your account is secured. Choose a new password to get back in."
        }
      />
    );
  }

  return (
    <LoginShell title="Securing your account…" subtitle="Ending every session.">
      <p className="login-hint">This only takes a moment.</p>
    </LoginShell>
  );
}
