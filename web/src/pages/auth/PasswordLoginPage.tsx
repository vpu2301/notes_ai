import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import * as authApi from "../../api/auth";
import { ApiError } from "../../api/http";
import { useAuth } from "../../auth/AuthContext";
import { offerToSavePassword } from "../../lib/credentials";
import { messageFor } from "../../lib/errorCopy";
import { Banner, LoginShell } from "./LoginShell";

/**
 * `/login/password` — the alternative to an emailed code.
 *
 * Still Keycloak-backed (`routers/login.py` runs in both `MDX_IDP_MODE`s),
 * so the second factor arrives as the sprint-16 `otp_required` /
 * `otp_invalid` pair on a 401 rather than as an `mfa_required` AuthResult.
 * Both shapes are handled: the code path here, the AuthResult path at
 * `/login/mfa`.
 */
export function PasswordLoginPage() {
  const { status, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  /**
   * `/login` hands over the address it already has — either because the
   * person chose "Use a password instead", or because the code step was
   * refused with `use_password` and sent them here. `notice` is the
   * explanation that goes with the second case; there is none for the
   * first, because choosing a different way in needs no apology.
   */
  const handover = (location.state ?? null) as {
    from?: string;
    email?: string;
    notice?: string;
    /** A success line, set by `/signup` after it confirmed the address. */
    info?: string;
  } | null;

  const [email, setEmail] = useState(handover?.email ?? "");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [otpRequired, setOtpRequired] = useState(false);
  const [error, setError] = useState<string | null>(handover?.notice ?? null);
  const [info, setInfo] = useState<string | null>(handover?.info ?? null);
  /** `email_not_verified`: right password, unconfirmed address (BE-0). */
  const [unverified, setUnverified] = useState(false);
  const [resent, setResent] = useState(false);
  const [busy, setBusy] = useState(false);

  const from = handover?.from ?? "/";
  if (status === "authenticated") return <Navigate to={from} replace />;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setBusy(true);
    try {
      await login(email.trim(), password, otpRequired && otp ? otp.trim() : undefined);
      // Not awaited: Chromium's save bubble outlives this client-side route
      // change, and the button should not sit on "Signing in…" while the
      // user decides.
      void offerToSavePassword(email.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      const code = err instanceof ApiError ? err.code : undefined;
      if (code === "email_not_verified") {
        // The password was right — this is the one 403 on this screen that
        // is not about credentials, so it gets a way forward rather than a
        // red line telling somebody to re-check something that was fine.
        setUnverified(true);
        setError(messageFor(err));
      } else if (code === "otp_required") {
        setOtpRequired(true);
        setError(null);
      } else if (code === "otp_invalid" || code === "otp_unavailable") {
        setOtpRequired(true);
        setError(messageFor(err));
      } else if (authApi.isUnavailableHere(err)) {
        // `/auth/login` is mounted only under `MDX_IDP_MODE=keycloak`. A
        // native deployment answers 404, and "Not Found" under a password
        // box reads as a wrong address rather than an absent flow.
        setError("Password sign-in is not enabled here. Use an emailed code instead.");
      } else {
        setError(messageFor(err));
      }
    } finally {
      setBusy(false);
    }
  };

  /**
   * Another confirmation code, from the screen where the person learned
   * they needed one. Unauthenticated by necessity — not being able to sign
   * in is the problem being solved — and answered with a 202 either way,
   * so the button reports on success as well as failure: nothing else here
   * changes, and silence reads as broken.
   */
  const onResend = async () => {
    setBusy(true);
    try {
      await authApi.signupResend(email.trim());
      setResent(true);
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <LoginShell
      title={otpRequired ? "One more step" : "Sign in with a password"}
      subtitle={
        otpRequired
          ? "Enter the code from your authenticator app."
          : "Or go back and we'll email you a code instead."
      }
      onSubmit={(e) => void onSubmit(e)}
    >
      <label className="login-field">
        <span>Email</span>
        <input
          id="login-email"
          name="email"
          type="email"
          autoComplete="username"
          required
          autoFocus={!otpRequired && !handover?.email}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </label>

      <label className="login-field">
        <span>Password</span>
        <input
          id="login-password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          // Prefilled address ⇒ the only thing left to type is here.
          autoFocus={!otpRequired && !!handover?.email}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>

      {otpRequired && (
        <label className="login-field">
          <span>One-time code</span>
          <input
            id="login-otp"
            name="otp"
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="6-digit code"
            required
            autoFocus
            className="mono"
            value={otp}
            onChange={(e) => setOtp(e.target.value)}
          />
        </label>
      )}

      {info && <Banner tone="info">{info}</Banner>}
      {error && <Banner>{error}</Banner>}

      {unverified && (
        <div className="login-actions">
          <button
            type="button"
            className="btn ghost block"
            disabled={busy || resent}
            onClick={() => void onResend()}
          >
            {resent ? "Code sent — check your inbox" : "Email me the code again"}
          </button>
          <Link
            className="link-btn"
            to="/signup"
            state={{ email: email.trim(), verifyOnly: true }}
          >
            I have the code
          </Link>
        </div>
      )}

      <button className="btn primary lg block login-submit" type="submit" disabled={busy}>
        {busy ? "Signing in…" : otpRequired ? "Verify and sign in" : "Sign in"}
      </button>

      <p className="login-foot">
        <Link className="link-btn" to="/login" state={{ from }}>
          Email me a code instead
        </Link>
        <Link className="link-btn" to="/reset">
          Forgot password?
        </Link>
        <Link className="link-btn" to="/signup">
          Create an account
        </Link>
      </p>

      {/* The seeded dev account. Stripped from production bundles — a
          working credential in shipped HTML is not a convenience. */}
      {import.meta.env.DEV && (
        <p className="login-foot">
          <span>
            Dev workspace: <code>member@tenant-a.example</code> / <code>dev-password</code>
          </span>
        </p>
      )}
    </LoginShell>
  );
}
