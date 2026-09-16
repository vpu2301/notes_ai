import { useEffect, useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import * as authApi from "../../api/auth";
import { ApiError } from "../../api/http";
import { useAuth } from "../../auth/AuthContext";
import { CodeInput } from "../../components/CodeInput";
import { offerToSavePassword } from "../../lib/credentials";
import { attemptsLeft, messageFor, passwordReasons } from "../../lib/errorCopy";
import { browserTimezone } from "../../lib/time";
import { Banner, LoginShell, useCountdown } from "./LoginShell";

/**
 * `/signup` — self-serve account creation (BE-0).
 *
 * The route macOS and iOS open in a browser when somebody taps "Create
 * one", and the only way into the product on a `keycloak` or `dual`
 * deployment, where `/auth/email/*` is not mounted and `/login` cannot
 * create anything.
 *
 * Two steps, one screen each: name + address + password, then the 6-digit
 * code that confirms the address. Verification hands back no session
 * (`{verified: true}` is the whole body), so this page signs in with the
 * password it is still holding and lands the person in the app — the
 * alternative is asking somebody to type a password they chose forty
 * seconds ago.
 *
 * ── What this screen must not say ────────────────────────────────────
 *
 * `POST /auth/signup` answers the same 202 whether or not the address
 * already has an account, so that it cannot be used to ask "is this
 * person a customer?". The code step is worded to match: *if* the address
 * is new, a code is on its way. Any copy here that implies the server
 * recognised the address gives away exactly what the uniform 202 protects,
 * and `tests/signup.test.tsx` holds that line.
 */
export function SignupPage() {
  const { status, login, saveProfile } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  /**
   * `/login/password` sends people here when `/auth/login` answered
   * `email_not_verified` — the account exists and only the confirmation is
   * missing, so this page opens on the code step.
   *
   * It deliberately arrives without the password. Router state is written
   * into the browser's history entry, which outlives the tab, and a
   * password does not belong there. The cost is one retype on that path
   * only: verifying goes back to the password form rather than into the
   * app.
   */
  const handover = (location.state ?? null) as { email?: string; verifyOnly?: boolean } | null;
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

  // Public and cheap, and it keeps the `minLength` on the field in step
  // with `domain/password_policy.py` instead of drifting from it. The
  // server enforces the real number either way.
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

  /**
   * Verified, and now signed in with the password from step 1.
   *
   * The sign-in is a second call that can fail on its own; when it does,
   * the account is still made and confirmed, so the person is sent to the
   * password form rather than left staring at an error on a screen with
   * nothing left to do.
   */
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
    // `/welcome` exists to ask a new identity for its name and to send the
    // browser's time zone. The name was step 1, so only the second half is
    // left — and it is worth doing silently rather than showing a screen
    // with one prefilled box on it. Best-effort: `PATCH /auth/me` is not
    // mounted in `keycloak` mode, and a 404 here must not block the way in.
    const zone = browserTimezone();
    if (zone) void saveProfile({ timezone: zone }).catch(() => {});
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
      // Nothing else on this screen changes, and silence after a click
      // reads as broken — so the one button whose effect is invisible says
      // so itself.
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
        {/* The one thing the uniform 202 cannot tell them, said plainly
            rather than left to be discovered by waiting for a code that
            is never coming. */}
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
