import { useEffect, useRef, useState } from "react";
import { useDocumentTitle } from "../../lib/useDocumentTitle";
import { Link } from "react-router-dom";
import * as authApi from "../../api/auth";
import { clearMailToken, mailToken } from "../../lib/mailLink";
import { messageWithRef } from "../../lib/errorCopy";
import { Banner, LoginShell } from "./LoginShell";
import { ResetPasswordPage } from "./ResetPasswordPage";

/**
 * `/account-recovery` — "this wasn't me". Acts on arrival: lockdown ends every session
 * and hands back a reset token that drops straight into the set-password step.
 */
export function AccountRecoveryPage() {
  useDocumentTitle("Account recovery");
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
