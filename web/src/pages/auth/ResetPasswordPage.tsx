import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import * as authApi from "../../api/auth";
import { useToast } from "../../components/Toaster";
import { clearMailToken, mailToken } from "../../lib/mailLink";
import { messageFor } from "../../lib/errorCopy";
import { Banner, LoginShell } from "./LoginShell";

/**
 * `/reset` — forgotten password, both halves.
 *
 * The pack describes an email → code → password flow. The server does not
 * have one: `POST /auth/password/forgot` mails a **link**, and
 * `POST /auth/password/reset` takes the `{token, new_password}` that link
 * carries. So this page is the same two halves, split by whether the load
 * came from that link:
 *
 *   no token  → ask for the address, always answer neutrally;
 *   token     → set the new password.
 *
 * A token can also arrive from `/account-recovery`, which hands one over
 * after ending every session.
 */
export function ResetPasswordPage({
  token: injected,
  notice,
}: {
  token?: string | null;
  /** Set by `/account-recovery`, which reaches this step already holding a token. */
  notice?: string;
}) {
  const navigate = useNavigate();
  const toast = useToast();
  const [token] = useState(() => injected ?? mailToken("/reset"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [sent, setSent] = useState(false);
  const [minLength, setMinLength] = useState(12);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // The policy is public and cheap; asking for it beats hard-coding a
  // number that then drifts from `domain/password_policy.py`.
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    void authApi
      .passwordPolicy()
      .then((p) => !cancelled && setMinLength(p.min_length))
      .catch(() => {
        /* the server enforces it either way; 12 is the documented floor */
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const onRequest = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await authApi.passwordForgot(email.trim());
      setSent(true);
    } catch (err) {
      setError(
        authApi.isUnavailableHere(err)
          ? "Password reset is not available here. Sign in with an emailed code instead."
          : messageFor(err),
      );
    } finally {
      setBusy(false);
    }
  };

  const onReset = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await authApi.passwordReset(token!, password);
      clearMailToken();
      toast.success("Password changed. Every other session was signed out.");
      navigate("/login/password", { replace: true });
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  // ── set a new password ────────────────────────────────────────────
  if (token) {
    return (
      <LoginShell
        title="Choose a new password"
        subtitle={`At least ${minLength} characters. Length beats punctuation — a few words you'll remember is a good password.`}
        onSubmit={(e) => void onReset(e)}
      >
        {notice && <Banner tone="info">{notice}</Banner>}
        <label className="login-field">
          <span>New password</span>
          <input
            name="new-password"
            type="password"
            autoComplete="new-password"
            required
            autoFocus
            minLength={minLength}
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              setError(null);
            }}
          />
        </label>

        {error && <Banner>{error}</Banner>}

        <button className="btn primary lg block login-submit" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Set password and sign in"}
        </button>

        <p className="login-hint">
          Setting a new password signs out every other device on this account.
        </p>
      </LoginShell>
    );
  }

  // ── ask for the address ───────────────────────────────────────────
  if (sent) {
    return (
      <LoginShell
        title="Check your email"
        subtitle="If that address has an account with a password, a reset link is on its way. The link works once and expires in an hour."
      >
        <p className="login-foot">
          <Link className="link-btn" to="/login">
            Back to sign in
          </Link>
        </p>
      </LoginShell>
    );
  }

  return (
    <LoginShell
      title="Reset your password"
      subtitle="We'll email you a link to set a new one."
      onSubmit={(e) => void onRequest(e)}
    >
      <label className="login-field">
        <span>Email</span>
        <input
          name="email"
          type="email"
          autoComplete="username"
          required
          autoFocus
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </label>

      {error && <Banner>{error}</Banner>}

      <button className="btn primary lg block login-submit" type="submit" disabled={busy}>
        {busy ? "Sending…" : "Email me a reset link"}
      </button>

      <p className="login-foot">
        <Link className="link-btn" to="/login">
          Sign in with a code instead
        </Link>
      </p>
    </LoginShell>
  );
}
