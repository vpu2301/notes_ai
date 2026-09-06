import { useMemo, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";
import { messageFor } from "../../lib/errorCopy";
import { browserTimezone } from "../../lib/time";
import { Banner, LoginShell } from "./LoginShell";

/**
 * `/welcome` — the one question a brand-new identity is asked.
 *
 * Reached only when `AuthResult.is_new_identity` was true. Skipping is a
 * first-class option: an unnamed account works perfectly well, and the
 * alternative is a wall between somebody and the product they just signed
 * up for.
 *
 * Two things happen here that the person is not asked about:
 *
 *  * The name box starts on the address's local part. It is a guess, and
 *    frequently the right one — somebody signing up as `alex.kim@…` is
 *    usually Alex Kim. It is pre-selected rather than merely filled, so
 *    the first keystroke replaces it instead of appending to it.
 *  * The browser's time zone is sent with the same `PATCH`. It decides
 *    which day a note is filed under, and it is the one setting a person
 *    cannot supply a better answer for than the machine can. Asking would
 *    be a second question for no gain; the value is visible and editable
 *    afterwards in Settings › Account.
 */
export function WelcomePage() {
  const { status, identity, saveProfile } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  /** The address's local part, tidied: `alex.kim` → `Alex Kim`. */
  const suggestion = useMemo(() => suggestName(identity?.email), [identity?.email]);
  const [name, setName] = useState(suggestion);
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const from = (location.state as { from?: string } | null)?.from ?? "/";
  if (status === "anonymous") return <Navigate to="/login" replace />;

  // The name arrives with `identity`, which lands a tick after the first
  // paint on a hard reload. Adopt it until the person types.
  const value = touched ? name : name || suggestion;

  /**
   * On to the app. `focusNewMeeting` asks `NotesPage` to put the caret on
   * the recorder: this is the last screen before the thing they came for,
   * and it should not need a hunt with the mouse.
   */
  const finish = () => navigate(from, { replace: true, state: { focusNewMeeting: true } });

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      // Even with no name, the time zone is worth the call — and a failed
      // `PATCH` must not strand somebody on a screen they may skip.
      await saveProfile({
        display_name: value.trim() || undefined,
        timezone: browserTimezone() ?? undefined,
      });
      finish();
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <LoginShell
      title="Welcome"
      subtitle={
        identity?.email
          ? `You're signed in as ${identity.email}. What should we call you?`
          : "What should we call you?"
      }
      onSubmit={(e) => void onSubmit(e)}
    >
      <label className="login-field">
        <span>Your name</span>
        <input
          name="name"
          type="text"
          autoComplete="name"
          maxLength={120}
          autoFocus
          placeholder="Alex Kim"
          value={value}
          // The guess is selected, not just typed in: somebody whose
          // address does not match their name replaces it with one key.
          onFocus={(e) => !touched && e.currentTarget.select()}
          onChange={(e) => {
            setTouched(true);
            setName(e.target.value);
          }}
        />
      </label>

      {error && <Banner>{error}</Banner>}

      <button className="btn primary lg block login-submit" type="submit" disabled={busy}>
        {busy ? "Saving…" : "Continue"}
      </button>

      <p className="login-foot">
        <button type="button" className="link-btn" onClick={finish} disabled={busy}>
          Skip for now
        </button>
      </p>
    </LoginShell>
  );
}

/**
 * `alex.kim+notes@example.com` → `Alex Kim`.
 *
 * A guess, and deliberately a conservative one: a local part that is
 * mostly digits or a single opaque token (`k1n2m3`, `info`) is left alone
 * rather than Title-Cased into something that looks like a name and is
 * not. An empty return means the box starts empty, which is fine.
 */
export function suggestName(email: string | undefined): string {
  const local = (email ?? "").split("@")[0] ?? "";
  const words = local
    .replace(/\+.*$/, "") // strip the +tag
    .split(/[._-]+/)
    .filter(Boolean)
    // A part with a digit in it is an account number, not a first name.
    .filter((w) => !/\d/.test(w));
  if (words.length === 0) return "";
  // One word tells us nothing a person did not already know, so it is only
  // worth offering when it reads like a name rather than a mailbox alias.
  if (words.length === 1 && (words[0]!.length < 3 || GENERIC.has(words[0]!.toLowerCase()))) return "";
  return words.map((w) => w[0]!.toUpperCase() + w.slice(1).toLowerCase()).join(" ");
}

/** Mailbox names that are a role, not a person. */
const GENERIC = new Set([
  "admin",
  "billing",
  "contact",
  "hello",
  "help",
  "info",
  "mail",
  "me",
  "no-reply",
  "noreply",
  "office",
  "sales",
  "support",
  "team",
  "test",
]);
