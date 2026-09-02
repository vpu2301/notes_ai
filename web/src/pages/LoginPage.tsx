import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError, errorMessage } from "../api/http";
import { useAuth } from "../auth/AuthContext";

export function LoginPage() {
  const { status, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [otpRequired, setOtpRequired] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (status === "authenticated") {
    const from = (location.state as { from?: string } | null)?.from ?? "/";
    return <Navigate to={from} replace />;
  }

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email.trim(), password, otpRequired && otp ? otp.trim() : undefined);
      const from = (location.state as { from?: string } | null)?.from ?? "/";
      navigate(from, { replace: true });
    } catch (err) {
      // The auth service signals MFA with machine codes on a 401 problem:
      // otp_required (reveal the field) / otp_invalid (wrong code).
      if (err instanceof ApiError && err.code === "otp_required") {
        setOtpRequired(true);
        setError(null);
      } else if (err instanceof ApiError && err.code === "otp_invalid") {
        setOtpRequired(true);
        setError(err.detail);
      } else {
        setError(errorMessage(err));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="card login-card" onSubmit={(e) => void onSubmit(e)}>
        <div className="wordmark">
          <span className="mark" aria-hidden="true">
            N
          </span>
          <span>
            Notes <span className="ai">AI</span>
          </span>
        </div>
        <p style={{ color: "var(--ink-2)", fontSize: "var(--text-md)" }}>
          Sign in to your workspace.
        </p>

        <div className="field">
          <label className="label" htmlFor="login-email">
            Email
          </label>
          <input
            id="login-email"
            className="input"
            type="email"
            autoComplete="username"
            required
            autoFocus
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>

        <div className="field">
          <label className="label" htmlFor="login-password">
            Password
          </label>
          <input
            id="login-password"
            className="input"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        {otpRequired && (
          <div className="field">
            <label className="label" htmlFor="login-otp">
              One-time code
            </label>
            <input
              id="login-otp"
              className="input"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="6-digit code"
              required
              autoFocus
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
            />
            <span className="hint">This account has two-factor authentication enabled.</span>
          </div>
        )}

        {error && (
          <div className="banner banner-danger" role="alert">
            {error}
          </div>
        )}

        <button className="btn btn-primary btn-lg" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>

        <p className="dev-hint">
          Dev workspace: <code>member@tenant-a.example</code> / <code>dev-password</code>
        </p>
      </form>
    </div>
  );
}
