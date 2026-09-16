import { useState, type FormEvent, type ReactNode } from "react";
import * as account from "../../api/account";
import * as authApi from "../../api/auth";
import { ApiError } from "../../api/http";
import { useAuth } from "../../auth/AuthContext";
import { CodeInput } from "../../components/CodeInput";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { useToast } from "../../components/Toaster";
import { AlertIcon } from "../../components/icons";
import { messageFor } from "../../lib/errorCopy";

/** `/settings/account` — who you are, how you're reached, and leaving. */
export function AccountSettingsPage() {
  const { identity } = useAuth();
  if (!identity) return null;
  return (
    <div className="settings-stack">
      <ProfileCard />
      <EmailCard />
      <PasswordCard />
      <DangerCard />
    </div>
  );
}

// ── profile ─────────────────────────────────────────────────────────────

function ProfileCard() {
  const { identity, setDisplayName } = useAuth();
  const toast = useToast();
  const [name, setName] = useState(identity?.display_name ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const dirty = name.trim() !== (identity?.display_name ?? "");

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await setDisplayName(name.trim());
      toast.success("Name saved.");
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card pad settings-card" onSubmit={(e) => void onSubmit(e)}>
      <h2 className="settings-h">Profile</h2>
      <label className="field">
        <span className="label">Name</span>
        <input
          type="text"
          autoComplete="name"
          maxLength={120}
          placeholder="Not set"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <span className="help">Shown on your notes and to other people in your workspaces.</span>
      </label>
      {error && <Problem>{error}</Problem>}
      <div className="settings-actions">
        <button className="btn primary" type="submit" disabled={busy || !dirty}>
          {busy ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}

// ── email ───────────────────────────────────────────────────────────────

/**
 * Changing the login address is a two-step: a code proves the new mailbox,
 * and the old one is then sent a revert link. Both halves are the server's;
 * this only drives them.
 */
function EmailCard() {
  const { identity, refreshIdentity } = useAuth();
  const toast = useToast();
  const [step, setStep] = useState<"idle" | "address" | "code">("idle");
  const [newEmail, setNewEmail] = useState("");
  const [challengeId, setChallengeId] = useState("");
  const [code, setCode] = useState("");
  const [invalid, setInvalid] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setStep("idle");
    setNewEmail("");
    setChallengeId("");
    setCode("");
    setError(null);
  };

  const start = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      // A 403 `reauth_required` here is caught by http.ts, which opens the
      // dialog and replays this call — nothing to handle locally.
      const challenge = await account.startEmailChange(newEmail.trim());
      setChallengeId(challenge.challenge_id);
      setStep("code");
    } catch (err) {
      setError(
        authApi.isUnavailableHere(err)
          ? "Changing your email isn't available in this deployment."
          : messageFor(err),
      );
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (digits: string) => {
    setError(null);
    setBusy(true);
    try {
      await account.confirmEmailChange(challengeId, digits);
      toast.success("Email changed. A revert link was sent to your previous address.");
      // The sidebar shows the address; re-read rather than leave it stale.
      await refreshIdentity();
      reset();
    } catch (err) {
      const codeName = err instanceof ApiError ? err.code : undefined;
      if (codeName === "challenge_expired" || codeName === "challenge_consumed") {
        setStep("address");
        setError(messageFor(err));
      } else {
        setInvalid(true);
        setCode("");
        setError(messageFor(err));
        window.setTimeout(() => setInvalid(false), 500);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card pad settings-card">
      <h2 className="settings-h">Email</h2>

      {step === "idle" && (
        <>
          <div className="settings-row">
            <div>
              <div className="settings-value">{identity?.email}</div>
              <span className="help">This is the address you sign in with.</span>
            </div>
            <button className="btn ghost" onClick={() => setStep("address")}>
              Change
            </button>
          </div>
        </>
      )}

      {step === "address" && (
        <form onSubmit={(e) => void start(e)} className="settings-stack-sm">
          <label className="field">
            <span className="label">New email</span>
            <input
              type="email"
              autoComplete="email"
              required
              autoFocus
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
            />
            <span className="help">
              We'll send a code there, then a revert link to {identity?.email}.
            </span>
          </label>
          {error && <Problem>{error}</Problem>}
          <div className="settings-actions">
            <button type="button" className="btn ghost" onClick={reset} disabled={busy}>
              Cancel
            </button>
            <button type="submit" className="btn primary" disabled={busy}>
              {busy ? "Sending…" : "Send code"}
            </button>
          </div>
        </form>
      )}

      {step === "code" && (
        <div className="settings-stack-sm">
          <p className="help">
            Enter the 6-digit code we sent to <strong>{newEmail}</strong>.
          </p>
          <CodeInput
            value={code}
            onChange={(v) => {
              setCode(v);
              setError(null);
            }}
            onComplete={(v) => void confirm(v)}
            disabled={busy}
            invalid={invalid}
            label="Email change code"
          />
          {error && <Problem>{error}</Problem>}
          <div className="settings-actions">
            <button type="button" className="btn ghost" onClick={reset} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── password ────────────────────────────────────────────────────────────

/**
 * There is no password surface on a native deployment yet.
 *
 * IDX-A4 — "Passwords: set/change/forgot/reset, step-up, legacy hash
 * import" — has not been run, so `PUT /auth/password` and
 * `DELETE /auth/password` (which W2 §E lists) do not exist, and
 * `/auth/password/*` is mounted only in Keycloak mode against Keycloak's
 * own store. Rather than a form that 404s, the card says what is true.
 */
function PasswordCard() {
  const { identity } = useAuth();
  return (
    <div className="card pad settings-card">
      <h2 className="settings-h">Password</h2>
      <div className="settings-row">
        <div>
          <div className="settings-value">
            {identity?.has_password ? "Set" : "You sign in with an emailed code"}
          </div>
          <span className="help">
            {identity?.has_password
              ? "Change it from the sign-in screen's “Forgot password?” link."
              : "No password is needed — each sign-in uses a fresh code sent to your email."}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── deletion ────────────────────────────────────────────────────────────

function DangerCard() {
  const toast = useToast();
  const { logout } = useAuth();
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");
  const [blockers, setBlockers] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const close = () => {
    setConfirming(false);
    setTyped("");
    setError(null);
    setBlockers(null);
  };

  const remove = async () => {
    setError(null);
    setBusy(true);
    try {
      const result = await account.deleteAccount();
      const when = new Date(result.purge_after).toLocaleDateString();
      toast.info(`Account scheduled for deletion on ${when}. Signing in again cancels it.`);
      await logout();
    } catch (err) {
      if (err instanceof ApiError && err.code === "sole_owner_with_members") {
        const tenants = err.extra<{ name?: string }[]>("tenants") ?? [];
        setBlockers(tenants.map((t, i) => t.name ?? `Workspace ${i + 1}`));
        setError(messageFor(err));
      } else {
        setError(messageFor(err));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card pad settings-card danger-card">
      <h2 className="settings-h">Delete account</h2>
      <p className="help">
        Your notes, recordings and workspaces are removed after a 30-day grace period. Signing in
        during that time cancels the deletion.
      </p>
      <div className="settings-actions">
        <button className="btn danger" onClick={() => setConfirming(true)}>
          Delete my account
        </button>
      </div>

      {confirming && (
        <ConfirmDialog
          title="Delete this account?"
          subtitle="Type DELETE to confirm. You have 30 days to change your mind."
          confirmLabel="Delete account"
          confirmDanger
          busy={busy}
          error={error}
          onCancel={close}
          onConfirm={() => typed === "DELETE" && void remove()}
        >
          <label className="field">
            <span className="label">Type DELETE</span>
            <input
              type="text"
              autoFocus
              className="mono"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
            />
          </label>
          {blockers && blockers.length > 0 && (
            <>
              <p className="help">
                You are the only owner of {blockers.length === 1 ? "a workspace" : "workspaces"} other
                people still use. Hand {blockers.length === 1 ? "it" : "them"} over first:
              </p>
              <ul className="help">
                {blockers.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            </>
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}

export function Problem({ children }: { children: ReactNode }) {
  return (
    <div className="banner banner-danger" role="alert">
      <AlertIcon size={15} />
      <span className="grow">{children}</span>
    </div>
  );
}
