import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../../api/http";
import { useAuth } from "../../auth/AuthContext";
import { useToast } from "../../components/Toaster";
import { messageFor } from "../../lib/errorCopy";
import { Banner, LoginShell, useCountdown } from "./LoginShell";

interface MfaState {
  challengeId?: string;
  methods?: string[];
  /** The challenge's own lifetime, from the `mfa_required` result. */
  expiresIn?: number;
  from?: string;
}

/**
 * `/login/mfa` — the second factor.
 *
 * Reached only by navigation carrying a `challengeId`, which is what makes
 * this a real route guard rather than a screen: an MFA account whose first
 * factor passed has no session and no token, so `/` is unreachable until
 * this page trades the challenge for one. Arriving here directly (a
 * bookmark, a reload) has no challenge to complete and bounces to `/login`.
 */
export function MfaPage() {
  const { status, completeMfa } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const state = (location.state as MfaState | null) ?? {};

  const [useRecovery, setUseRecovery] = useState(false);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [expiresIn, setExpiresIn] = useState(state.expiresIn ?? 300);

  useCountdown(expiresIn, setExpiresIn);

  const from = state.from ?? "/";
  if (status === "authenticated") return <Navigate to={from} replace />;
  if (!state.challengeId) return <Navigate to="/login" replace />;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      // Recovery codes are shown and mailed as xxxx-xxxx-xxxx; people type
      // them with, without, or halfway through the dashes.
      const cleaned = useRecovery ? code.trim().replace(/[\s-]/g, "") : code.trim();
      const outcome = await completeMfa(
        state.challengeId!,
        useRecovery ? "recovery_code" : "totp",
        cleaned,
      );
      if (outcome.kind === "mfa_required") {
        setError("That challenge is no longer valid. Sign in again.");
        return;
      }
      const left = outcome.recoveryCodesLeft;
      if (left === 0) {
        toast.error("That was your last recovery code. Generate a new set in Settings › Security.");
      } else if (left !== null && left <= 2) {
        toast.info(`${left} recovery ${left === 1 ? "code" : "codes"} left — make a new set in Settings › Security.`);
      }
      navigate(outcome.isNewIdentity ? "/welcome" : from, { replace: true, state: { from } });
    } catch (err) {
      const codeName = err instanceof ApiError ? err.code : undefined;
      if (codeName === "challenge_expired" || codeName === "too_many_attempts") {
        navigate("/login", { replace: true, state: { from } });
        toast.error(messageFor(err));
        return;
      }
      setError(messageFor(err));
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  const canRecover = (state.methods ?? []).includes("recovery_code");

  return (
    <LoginShell
      title="Two-factor authentication"
      subtitle={
        useRecovery
          ? "Enter one of the recovery codes you saved when you set this up."
          : "Enter the 6-digit code from your authenticator app."
      }
      onSubmit={(e) => void onSubmit(e)}
    >
      <label className="login-field">
        <span>{useRecovery ? "Recovery code" : "Authenticator code"}</span>
        <input
          name={useRecovery ? "recovery-code" : "otp"}
          inputMode={useRecovery ? "text" : "numeric"}
          autoComplete="one-time-code"
          placeholder={useRecovery ? "xxxx-xxxx-xxxx" : "123456"}
          className="mono"
          required
          autoFocus
          value={code}
          onChange={(e) => {
            setCode(e.target.value);
            setError(null);
          }}
        />
      </label>

      {error && <Banner>{error}</Banner>}

      <button className="btn primary lg block login-submit" type="submit" disabled={busy}>
        {busy ? "Checking…" : "Verify"}
      </button>

      <p className="login-hint">
        {expiresIn > 0
          ? `This sign-in expires in ${Math.floor(expiresIn / 60)}:${String(expiresIn % 60).padStart(2, "0")}.`
          : "This sign-in has expired — start again."}
      </p>

      {canRecover && (
        <p className="login-foot">
          <button
            type="button"
            className="link-btn"
            onClick={() => {
              setUseRecovery((v) => !v);
              setCode("");
              setError(null);
            }}
          >
            {useRecovery ? "Use my authenticator app" : "Use a recovery code"}
          </button>
        </p>
      )}
    </LoginShell>
  );
}
