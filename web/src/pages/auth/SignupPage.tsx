import { useEffect, useState, type FormEvent } from "react";
import { useDocumentTitle } from "../../lib/useDocumentTitle";
import { REF_KEY } from "../../lib/storageKeys";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import * as authApi from "../../api/auth";
import { ApiError } from "../../api/http";
import { useAuth } from "../../auth/AuthContext";
import { CodeInput } from "../../components/CodeInput";
import { offerToSavePassword } from "../../lib/credentials";
import { attemptsLeft, messageFor, passwordReasons } from "../../lib/errorCopy";
import { browserTimezone } from "../../lib/time";
import { Banner, LoginShell, useCountdown } from "./LoginShell";

/**
 * `/signup` — self-serve account creation; verification returns no session, so step 2 signs in
 * with the held password. Copy must never imply the server recognised the address: `POST
 * /auth/signup` is a uniform 202 (tests/signup.test.tsx holds that line).
 */
export function SignupPage() {
  useDocumentTitle("Create your account");
  const { status, login, saveProfile } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  /** `email_not_verified` hand-off: opens on the code step, without the password (router state outlives the tab). */
  const handover = (location.state ?? null) as { email?: string; verifyOnly?: boolean } | null;
  // Referral code from the URL or sessionStorage (JoinPage); read once, never stored elsewhere.
  const [params] = useSearchParams();
  const ref = readRef(params.get("ref"));
  const verifyOnly = handover?.verifyOnly === true;

  const [step, setStep] = useState<"form" | "code">(verifyOnly ? "code" : "form");
  const [name, setName] = useState("");
  const [email, setEmail] = useState(handover?.email ?? "");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [invalid, setInvalid] = useState(false);
  const [minLength, setMinLength] = useState(12);
  const [error, setError] = useState<string | null>(null);
  /** The `reasons[]` of a `password_policy` refusal, listed under the field. */
  const [weak, setWeak] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [resendIn, setResendIn] = useState(0);
  const [resent, setResent] = useState(false);

  useCountdown(resendIn, setResendIn);

  // Keeps the field's `minLength` in step with the server policy; the server enforces it anyway.
  useEffect(() => {
    let cancelled = false;
    void authApi
      .passwordPolicy()
      .then((p) => !cancelled && setMinLength(p.min_length))
      .catch(() => {
        /* 12 is the documented floor */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (status === "authenticated") return <Navigate to="/" replace />;

  const failed = (err: unknown) => {
    setWeak(passwordReasons(err));
    setError(
      authApi.isUnavailableHere(err)
        ? "Creating an account is not available here. Ask for an invitation, or sign in with an emailed code."
        : messageFor(err),
    );
  };

  // ── step 1: the account ─────────────────────────────────────────────

  const onCreate = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setWeak([]);
    setBusy(true);
    try {
      const accepted = await authApi.signup({
        email: email.trim(),
        password,
        display_name: name.trim(),
        ref: ref ?? undefined,
      });
      setResendIn(accepted.resend_after);
      setCode("");
      setStep("code");
    } catch (err) {
      failed(err);
    } finally {
      setBusy(false);
    }
  };

  // ── step 2: the mailed code ─────────────────────────────────────────

  /** Verified; sign in with the step-1 password. If that fails the account still exists, so go to the password form. */
  const signInAfterVerify = async () => {
    const address = email.trim();
    try {
      await login(address, password);
    } catch {
      navigate("/login/password", {
        replace: true,
        state: { email: address, info: "Your email is confirmed. Sign in to finish." },
      });
      return;
    }
    void offerToSavePassword(address, password);
    // Send the time zone silently (the name was step 1). Best-effort: 404 in keycloak mode must not block.
    const zone = browserTimezone();
    if (zone) void saveProfile({ timezone: zone }).catch(() => {});
    // A referred person lands on "record your first meeting".
    if (ref) {
      navigate("/meeting/new?first_run=1", { replace: true });
      return;
    }
    navigate("/", { replace: true, state: { focusNewMeeting: true } });
  };

  const onCodeComplete = async (digits: string) => {
    setError(null);
    setBusy(true);
    try {
      await authApi.signupVerify(email.trim(), digits);
      if (verifyOnly) {
        navigate("/login/password", {
          replace: true,
          state: { email: email.trim(), info: "Your email is confirmed. Sign in to continue." },
        });
        return;
      }
      await signInAfterVerify();
    } catch (err) {
      const codeName = err instanceof ApiError ? err.code : undefined;
      const left = attemptsLeft(err);
      setInvalid(true);
      setCode("");
      setError(
        codeName === "code_invalid" && left !== null && left > 0
          ? `${messageFor(err)} ${left} ${left === 1 ? "try" : "tries"} left.`
          : messageFor(err),
      );
      window.setTimeout(() => setInvalid(false), 500);
    } finally {
      setBusy(false);
    }
  };

  const onResend = async () => {
    setError(null);
    setBusy(true);
    try {
      const accepted = await authApi.signupResend(email.trim());
      setResendIn(accepted.resend_after);
      setCode("");
      setResent(true);
    } catch (err) {
      failed(err);
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
            If <strong>{email.trim()}</strong> is new here, a 6-digit code is on its way. It expires
            in 10 minutes.
          </>
        }
      >
        <CodeInput
          value={code}
          onChange={(v) => {
            setCode(v);
            setError(null);
            setResent(false);
          }}
          onComplete={(v) => void onCodeComplete(v)}
          disabled={busy}
          invalid={invalid}
          label="Confirmation code"
          describedBy="signup-code-help"
        />
        {error && <Banner>{error}</Banner>}
        <p className="login-hint" id="signup-code-help">
          {busy ? "Checking…" : resent ? "Sent. It can take a minute to arrive." : "Paste the code, or type it in."}
        </p>
        <div className="login-actions">
          <button
            type="button"
            className="btn ghost block"
            disabled={busy || resendIn > 0}
            onClick={() => void onResend()}
          >
            {resendIn > 0 ? `Send a new code in ${resendIn}s` : "Send a new code"}
          </button>
          {verifyOnly ? (
            <Link className="link-btn" to="/login/password" state={{ email: email.trim() }}>
              Back to sign in
            </Link>
          ) : (
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                setStep("form");
                setCode("");
                setError(null);
                setResent(false);
              }}
            >
              Use a different address
            </button>
          )}
        </div>
        <p className="login-foot">
          <span>
            Already have an account?{" "}
            <Link className="link-btn" to="/login">
              Sign in instead
            </Link>
          </span>
        </p>
      </LoginShell>
    );
  }

  return (
    <LoginShell
      title="Create your account"
      subtitle="Your notes, written for you. It takes a minute."
      onSubmit={(e) => void onCreate(e)}
    >
      <label className="login-field">
        <span>Your name</span>
        <input
          id="signup-name"
          name="name"
          type="text"
          autoComplete="name"
          required
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>

      <label className="login-field">
        <span>Email</span>
        <input
          id="signup-email"
          name="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </label>

      <label className="login-field">
        <span>Password</span>
        <input
          id="signup-password"
          name="new-password"
          type="password"
          autoComplete="new-password"
          required
          minLength={minLength}
          aria-describedby="signup-password-help"
          value={password}
          onChange={(e) => {
            setPassword(e.target.value);
            setWeak([]);
          }}
        />
      </label>
      <p className="login-hint under-field" id="signup-password-help">
        At least {minLength} characters. Length beats punctuation — a few words you will remember
        is a good password.
      </p>

      {error && <Banner>{error}</Banner>}
      {weak.length > 0 && (
        <ul className="login-reasons">
          {weak.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}

      <button className="btn primary lg block login-submit" type="submit" disabled={busy}>
        {busy ? "Creating your account…" : "Create account"}
      </button>

      <p className="login-foot">
        <span>
          Already have an account?{" "}
          <Link className="link-btn" to="/login">
            Sign in
          </Link>
        </span>
      </p>
    </LoginShell>
  );
}

const REF_RE = /^[a-z2-7]{12}$/;

/** The query wins; otherwise what `/join` remembered for this tab. */
function readRef(fromQuery: string | null): string | null {
  const candidates = [fromQuery];
  try {
    candidates.push(window.sessionStorage.getItem(REF_KEY));
  } catch {
    /* private mode */
  }
  return candidates.find((c): c is string => !!c && REF_RE.test(c)) ?? null;
}
