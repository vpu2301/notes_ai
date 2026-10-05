import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { captureLead, signupConfig } from "../api/auth";
import { messageFor } from "../lib/errorCopy";
import { Banner, LoginShell } from "./auth/LoginShell";
import { SignupPage } from "./auth/SignupPage";

import { REF_KEY } from "../lib/storageKeys";

/** Where the shared page's CTA parks its referral code for `/signup`. */
export const REF_STORAGE_KEY = REF_KEY;

/**
 * `/join` — the CTA landing (`?ref=` referral code). Lead form when signup is off.
 * No auth calls, no session: `AuthContext` skips its silent refresh here on purpose.
 */
export function JoinPage() {
  const [params] = useSearchParams();
  const ref = params.get("ref");
  // Signup on: go to the real thing; off (or no `/config`): the lead form.
  const [signupOn, setSignupOn] = useState<boolean | null>(null);
  useEffect(() => {
    let live = true;
    signupConfig()
      .then((c) => live && setSignupOn(c.enabled))
      .catch(() => live && setSignupOn(false));
    return () => {
      live = false;
    };
  }, []);
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    document.title = "Create your workspace";
    if (ref) {
      try {
        window.sessionStorage.setItem(REF_STORAGE_KEY, ref);
      } catch {
        /* private mode: attribution is best-effort */
      }
    }
  }, [ref]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!consent) {
      setError("Please agree to be contacted about your workspace.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await captureLead(email.trim(), ref);
      setDone(true);
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  if (signupOn === null) {
    return (
      <LoginShell title="Create your own workspace — free">
        <p className="help" aria-busy="true">
          One moment…
        </p>
      </LoginShell>
    );
  }
  if (signupOn) {
    return <SignupPage />;
  }

  if (done) {
    return (
      <LoginShell title="Thanks — you're on the list" subtitle="We'll open your workspace shortly and e-mail you when it's ready.">
        <p className="help">You can close this page.</p>
      </LoginShell>
    );
  }

  return (
    <LoginShell
      title="Create your own workspace — free"
      subtitle="Leave your e-mail and we'll open your workspace shortly."
      onSubmit={(e) => void submit(e)}
    >
      {error && <Banner>{error}</Banner>}
      <label className="field">
        <span className="label">E-mail</span>
        <input
          className="input"
          type="email"
          name="email"
          autoComplete="email"
          required
          autoFocus
          value={email}
          disabled={busy}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@company.com"
        />
      </label>
      <label className="chk-row">
        <input
          type="checkbox"
          className="chk"
          checked={consent}
          disabled={busy}
          onChange={(e) => setConsent(e.target.checked)}
        />
        <span>
          I agree to be contacted about my workspace. See the{" "}
          <a href="/s/privacy" target="_blank" rel="noreferrer">
            privacy notice
          </a>
          .
        </span>
      </label>
      <button className="btn primary" type="submit" disabled={busy || !email.trim()}>
        {busy ? "Sending…" : "Open my workspace"}
      </button>
    </LoginShell>
  );
}
