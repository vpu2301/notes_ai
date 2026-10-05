import { useMemo, useState, type FormEvent } from "react";
import { useDocumentTitle } from "../../lib/useDocumentTitle";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";
import { messageFor } from "../../lib/errorCopy";
import { browserTimezone } from "../../lib/time";
import { Banner, LoginShell } from "./LoginShell";

/**
 * `/welcome` — asks a new identity (`is_new_identity`) for its name; skipping is fine.
 * The browser's time zone rides the same PATCH (editable later in Settings › Account).
 */
export function WelcomePage() {
  useDocumentTitle("Welcome");
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

  // `identity` lands a tick after first paint on a hard reload; adopt it until the person types.
  const value = touched ? name : name || suggestion;

  /** On to the app; `focusNewMeeting` asks `NotesPage` to focus the recorder. */
  const finish = () => navigate(from, { replace: true, state: { focusNewMeeting: true } });

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      // Time zone is worth the call even with no name; a failed PATCH must not strand anyone.
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
          placeholder="Olena Kovalenko"
          value={value}
          // Selected, not just filled: one key replaces the guess.
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

/** `alex.kim+notes@example.com` → `Alex Kim`; conservative — opaque tokens return "". */
export function suggestName(email: string | undefined): string {
  const local = (email ?? "").split("@")[0] ?? "";
  const words = local
    .replace(/\+.*$/, "") // strip the +tag
    .split(/[._-]+/)
    .filter(Boolean)
    // A digit means an account number, not a name.
    .filter((w) => !/\d/.test(w));
  if (words.length === 0) return "";
  // A single word is offered only when it reads like a name, not a mailbox alias.
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
