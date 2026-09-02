import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError, errorMessage } from "../api/http";
import { useAuth } from "../auth/AuthContext";
import { AlertIcon } from "../components/icons";

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
    <div className="login-shell dotted">
      <form className="login-card" onSubmit={(e) => void onSubmit(e)}>
        <div className="login-brand">
          <span className="sb-brand-mark" aria-hidden="true">
            N
          </span>
          <div className="login-brand-name">
            Notes <span className="ai">AI</span>
          </div>
        </div>

        <div>
          <h1 className="login-title">{otpRequired ? "One more step" : "Welcome back"}</h1>
          <p className="login-sub">
            {otpRequired ? "Enter the code from your authenticator app." : "Sign in to your workspace to see your meeting notes."}
          </p>
        </div>

        <label className="login-field">
          <span>Email</span>
          <input
            type="email"
            autoComplete="username"
            required
            autoFocus={!otpRequired}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>

        <label className="login-field">
          <span>Password</span>
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>

        {otpRequired && (
          <label className="login-field">
            <span>One-time code</span>
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="6-digit code"
              required
              autoFocus
              className="mono"
              value={otp}
              onChange={(e) => setOtp(e.target.value)}
            />
            <span className="help" style={{ fontWeight: 400 }}>
              This account has two-factor authentication enabled.
            </span>
          </label>
        )}

        {error && (
          <div className="banner banner-danger" role="alert">
            <AlertIcon size={15} />
            <span className="grow">{error}</span>
          </div>
        )}

        <button className="btn primary lg block login-submit" type="submit" disabled={busy}>
          {busy ? "Signing in…" : otpRequired ? "Verify and sign in" : "Sign in"}
        </button>

        <p className="login-foot">
          <span>
            Dev workspace: <code>member@tenant-a.example</code> / <code>dev-password</code>
          </span>
        </p>
      </form>
    </div>
  );
}
