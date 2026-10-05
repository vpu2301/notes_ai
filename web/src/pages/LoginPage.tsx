import { useState, type FormEvent } from "react";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import * as authApi from "../api/auth";
import { ApiError } from "../api/http";
import { useAuth, type SignInOutcome } from "../auth/AuthContext";
import { CodeInput } from "../components/CodeInput";
import { useToast } from "../components/Toaster";
import { attemptsLeft, messageFor, retryAfterSeconds } from "../lib/errorCopy";
import { Banner, LoginShell, useCountdown } from "./auth/LoginShell";

/** `/login` — sign up and sign in. The server's 202 is uniform; copy must never imply the address is known. */
export function LoginPage() {
  useDocumentTitle("Sign in");
  const { status, signInWithEmailCode } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();

  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [challengeId, setChallengeId] = useState("");
  const [code, setCode] = useState("");
  const [invalid, setInvalid] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [resendIn, setResendIn] = useState(0);

  const from = (location.state as { from?: string } | null)?.from ?? "/";

  useCountdown(resendIn, setResendIn);

  if (status === "authenticated") return <Navigate to={from} replace />;

  const backToEmail = (reason: string) => {
    setStep("email");
    setCode("");
    setChallengeId("");
    setError(reason);
  };

  const requestCode = async (address: string) => {
    setError(null);
    setBusy(true);
    try {
      const challenge = await authApi.emailStart(address);
      setChallengeId(challenge.challenge_id);
      setResendIn(challenge.resend_after);
      setStep("code");
    } catch (err) {
      const wait = retryAfterSeconds(err);
      if (wait) setResendIn(wait);
      if (authApi.isUnavailableHere(err)) {
        setError("Sign-in by email code is not enabled here. Use a password instead.");
      } else {
        setError(messageFor(err));
      }
    } finally {
      setBusy(false);
    }
  };

  const onEmailSubmit = (e: FormEvent) => {
    e.preventDefault();
    void requestCode(email.trim());
  };

  const onCodeComplete = async (digits: string) => {
    setError(null);
    setBusy(true);
    try {
      const outcome: SignInOutcome = await signInWithEmailCode(challengeId, digits);
      if (outcome.kind === "mfa_required") {
        navigate("/login/mfa", {
          replace: true,
          state: {
            challengeId: outcome.challengeId,
            methods: outcome.methods,
            expiresIn: outcome.expiresIn,
            from,
          },
        });
        return;
      }
      if (outcome.recoveryCodesLeft !== null && outcome.recoveryCodesLeft <= 2) {
        toast.info(`${outcome.recoveryCodesLeft} recovery codes left — make a new set in Settings.`);
      }
      navigate(outcome.isNewIdentity ? "/welcome" : from, { replace: true, state: { from } });
    } catch (err) {
      const codeName = err instanceof ApiError ? err.code : undefined;
      if (codeName === "use_password") {
        // Keycloak accounts (dual mode) cannot sign in by code; carry the address to the password form.
        navigate("/login/password", {
          replace: true,
          state: { from, email: email.trim(), notice: messageFor(err) },
        });
        return;
      }
      if (codeName === "challenge_expired" || codeName === "challenge_consumed") {
        backToEmail(messageFor(err));
      } else if (codeName === "too_many_attempts") {
        backToEmail(messageFor(err));
      } else {
        const left = attemptsLeft(err);
        setInvalid(true);
        setCode("");
        setError(
          left !== null && left > 0
            ? `${messageFor(err)} ${left} ${left === 1 ? "try" : "tries"} left.`
            : messageFor(err),
        );
        window.setTimeout(() => setInvalid(false), 500);
      }
    } finally {
      setBusy(false);
    }
  };

  if (step === "code") {
    return (
      <LoginShell
        title="Check your email"
        subtitle={
          <>
            If <strong>{email}</strong> is a valid address, a 6-digit code is on its way. It expires
            in 10 minutes.
          </>
        }
      >
        <CodeInput
          value={code}
          onChange={(v) => {
            setCode(v);
            setError(null);
          }}
          onComplete={(v) => void onCodeComplete(v)}
          disabled={busy}
          invalid={invalid}
          label="Sign-in code"
          describedBy="code-help"
        />
        {error && <Banner>{error}</Banner>}
        <p className="login-hint" id="code-help">
          {busy ? "Checking…" : "Paste the code, or type it in."}
        </p>
        <div className="login-actions">
          <button
            type="button"
            className="btn ghost block"
            disabled={busy || resendIn > 0}
            onClick={() => void requestCode(email.trim())}
          >
            {resendIn > 0 ? `Send a new code in ${resendIn}s` : "Send a new code"}
          </button>
          <button
            type="button"
            className="link-btn"
            onClick={() => {
              setStep("email");
              setCode("");
              setError(null);
            }}
          >
            Use a different address
          </button>
        </div>
      </LoginShell>
    );
  }

  return (
    <LoginShell
      title="Sign in"
      subtitle="Enter your email and we'll send you a code. No password needed."
      onSubmit={onEmailSubmit}
    >
      <label className="login-field">
        <span>Email</span>
        <input
          id="login-email"
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
        {busy ? "Sending…" : "Email me a code"}
      </button>

      <p className="login-foot">
        <Link
          className="link-btn"
          to="/login/password"
          state={{ ...(location.state as object | null), from, email: email.trim() }}
        >
          Use a password instead
        </Link>
        {/* In keycloak/dual mode this screen cannot create anything; `/signup` is the way in. */}
        <Link className="link-btn" to="/join">
          Create a free workspace
        </Link>
      </p>
    </LoginShell>
  );
}
