import { useCallback, useEffect, useState, type FormEvent } from "react";
import * as account from "../../api/account";
import { isUnavailableHere } from "../../api/auth";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { QrCode } from "../../components/QrCode";
import { SecretOnce } from "../../components/SecretOnce";
import { useToast } from "../../components/Toaster";
import { Skeleton } from "../../components/Skeleton";
import { messageFor } from "../../lib/errorCopy";
import type { SessionInfo, TotpEnrolment } from "../../api/types";
import { Problem } from "./AccountSettingsPage";
import { relativeTime } from "../../lib/time";

/** `/settings/security` — the second factor, and where you are signed in. */
export function SecuritySettingsPage() {
  return (
    <div className="settings-stack">
      <MfaCard />
      <SessionsCard />
    </div>
  );
}

// ── second factor ───────────────────────────────────────────────────────

type MfaStage =
  | { name: "idle" }
  | { name: "enrolling"; enrolment: TotpEnrolment }
  | { name: "codes"; codes: string[]; reason: "enrolled" | "regenerated" };

/** Base32 in groups of four — a 32-character run is unreadable and untypable. */
function grouped(secret: string): string {
  return (secret.match(/.{1,4}/g) ?? [secret]).join(" ");
}

function MfaCard() {
  const { identity, refreshIdentity } = useAuth();
  const toast = useToast();
  const [stage, setStage] = useState<MfaStage>({ name: "idle" });
  const [code, setCode] = useState("");
  const [saved, setSaved] = useState(false);
  const [disabling, setDisabling] = useState(false);
  const [disableCode, setDisableCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const enabled = identity?.mfa_enabled ?? false;

  const begin = async () => {
    setError(null);
    setBusy(true);
    try {
      // Step-up gated: a 403 here is handled by http.ts and this call is
      // replayed once the dialog is satisfied.
      const enrolment = await account.startTotpEnrolment();
      setStage({ name: "enrolling", enrolment });
    } catch (err) {
      setError(
        isUnavailableHere(err)
          ? "Two-factor authentication isn't available in this deployment."
          : messageFor(err),
      );
    } finally {
      setBusy(false);
    }
  };

  const confirm = async (e: FormEvent) => {
    e.preventDefault();
    if (stage.name !== "enrolling") return;
    setError(null);
    setBusy(true);
    try {
      const { recovery_codes } = await account.confirmTotpEnrolment(
        stage.enrolment.enrollment_id,
        code.trim(),
      );
      setCode("");
      setSaved(false);
      setStage({ name: "codes", codes: recovery_codes, reason: "enrolled" });
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const regenerate = async () => {
    setError(null);
    setBusy(true);
    try {
      const { recovery_codes } = await account.regenerateRecoveryCodes();
      setSaved(false);
      setStage({ name: "codes", codes: recovery_codes, reason: "regenerated" });
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setError(null);
    setBusy(true);
    try {
      const raw = disableCode.trim();
      // A recovery code is four-four-four; a TOTP code is six digits.
      const isRecovery = /[^0-9]/.test(raw) || raw.replace(/\D/g, "").length > 6;
      await account.disableMfa(
        isRecovery ? "recovery_code" : "totp",
        isRecovery ? raw.replace(/[\s-]/g, "") : raw,
      );
      setDisabling(false);
      setDisableCode("");
      toast.success("Two-factor authentication is off. Other sessions were signed out.");
      await refreshIdentity();
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  // ── the one-time codes screen ──────────────────────────────────────
  if (stage.name === "codes") {
    return (
      <div className="card pad settings-card">
        <h2 className="settings-h">
          {stage.reason === "enrolled" ? "Two-factor authentication is on" : "New recovery codes"}
        </h2>
        {stage.reason === "enrolled" && (
          <div className="banner banner-info" role="status">
            <span className="grow">
              Every other session was signed out. You'll be asked for a code from now on.
            </span>
          </div>
        )}
        <SecretOnce
          title="Recovery codes"
          values={stage.codes}
          filename="notes-ai-recovery-codes.txt"
          hint={
            <>
              Each works once, if you lose your phone. <strong>This is the only time they are
              shown</strong> — the server keeps only their hashes.
              {stage.reason === "regenerated" && " Your previous codes no longer work."}
            </>
          }
        />
        <label className="chk-row">
          <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
          <span>I've saved these somewhere safe</span>
        </label>
        <div className="settings-actions">
          <button
            className="btn primary"
            disabled={!saved}
            onClick={() => {
              // Unmounting is what makes "shown once" true.
              setStage({ name: "idle" });
              if (stage.reason === "enrolled") void refreshIdentity();
            }}
          >
            Done
          </button>
        </div>
      </div>
    );
  }

  // ── enrolment ──────────────────────────────────────────────────────
  if (stage.name === "enrolling") {
    return (
      <form className="card pad settings-card" onSubmit={(e) => void confirm(e)}>
        <h2 className="settings-h">Set up two-factor authentication</h2>
        <p className="help">
          Scan this with an authenticator app (1Password, Authy, Google Authenticator), then enter
          the code it shows.
        </p>
        <div className="mfa-enrol">
          <QrCode value={stage.enrolment.otpauth_uri} label="Scan to add this account" />
          <div className="mfa-enrol-key">
            <span className="label">Or enter this key by hand</span>
            <code className="mfa-key">{grouped(stage.enrolment.secret)}</code>
            <span className="help">Time-based, 6 digits, 30-second period.</span>
          </div>
        </div>
        <label className="field">
          <span className="label">Code from the app</span>
          <input
            inputMode="numeric"
            autoComplete="one-time-code"
            className="mono"
            placeholder="123456"
            required
            value={code}
            onChange={(e) => {
              setCode(e.target.value);
              setError(null);
            }}
          />
        </label>
        {error && <Problem>{error}</Problem>}
        <p className="help">Turning this on signs out every other session.</p>
        <div className="settings-actions">
          <button
            type="button"
            className="btn ghost"
            disabled={busy}
            onClick={() => {
              setStage({ name: "idle" });
              setCode("");
              setError(null);
            }}
          >
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={busy}>
            {busy ? "Checking…" : "Turn on"}
          </button>
        </div>
      </form>
    );
  }

  // ── idle ───────────────────────────────────────────────────────────
  return (
    <div className="card pad settings-card">
      <h2 className="settings-h">Two-factor authentication</h2>
      <div className="settings-row">
        <div>
          <div className="settings-value">{enabled ? "On" : "Off"}</div>
          <span className="help">
            {enabled
              ? "You're asked for a code from your authenticator app when you sign in."
              : "Add a second step to sign-in, so a stolen password isn't enough."}
          </span>
        </div>
        {enabled ? (
          <div className="settings-actions">
            <button className="btn ghost" disabled={busy} onClick={() => void regenerate()}>
              New recovery codes
            </button>
            <button className="btn danger" disabled={busy} onClick={() => setDisabling(true)}>
              Turn off
            </button>
          </div>
        ) : (
          <button className="btn primary" disabled={busy} onClick={() => void begin()}>
            {busy ? "Starting…" : "Turn on"}
          </button>
        )}
      </div>
      {error && <Problem>{error}</Problem>}

      {disabling && (
        <ConfirmDialog
          title="Turn off two-factor authentication?"
          subtitle="Enter a code from your app, or one of your recovery codes."
          confirmLabel="Turn off"
          confirmDanger
          busy={busy}
          error={error}
          onCancel={() => {
            setDisabling(false);
            setDisableCode("");
            setError(null);
          }}
          onConfirm={() => void disable()}
        >
          <label className="field">
            <span className="label">Code</span>
            <input
              className="mono"
              autoComplete="one-time-code"
              autoFocus
              value={disableCode}
              onChange={(e) => setDisableCode(e.target.value)}
            />
          </label>
          <p className="help">This also signs out every other session.</p>
        </ConfirmDialog>
      )}
    </div>
  );
}

// ── sessions ────────────────────────────────────────────────────────────

function SessionsCard() {
  const toast = useToast();
  const [sessions, setSessions] = useState<SessionInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmAll, setConfirmAll] = useState(false);

  const load = useCallback(async () => {
    try {
      setSessions(await account.listSessions());
      setError(null);
    } catch (err) {
      setSessions([]);
      setError(
        isUnavailableHere(err)
          ? "This deployment doesn't track sessions yet."
          : messageFor(err),
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const revoke = async (sid: string) => {
    // Optimistic: the row is the thing being removed, so leaving it in
    // place while the request flies reads as "the button did nothing".
    const before = sessions;
    setSessions((list) => (list ?? []).filter((s) => s.sid !== sid));
    try {
      await account.revokeSession(sid);
    } catch (err) {
      setSessions(before);
      toast.error(messageFor(err));
    }
  };

  const revokeOthers = async () => {
    setBusy(true);
    try {
      const { revoked } = await account.revokeOtherSessions();
      toast.success(
        revoked === 0
          ? "No other sessions were open."
          : `Signed out ${revoked} other ${revoked === 1 ? "session" : "sessions"}.`,
      );
      setConfirmAll(false);
      await load();
    } catch (err) {
      toast.error(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const others = (sessions ?? []).filter((s) => !s.current).length;

  return (
    <div className="card settings-card">
      <div className="settings-card-h">
        <h2 className="settings-h">Where you're signed in</h2>
        {others > 0 && (
          <button className="btn ghost sm" onClick={() => setConfirmAll(true)}>
            Sign out everywhere else
          </button>
        )}
      </div>

      {sessions === null && (
        <div className="settings-pad settings-stack-sm">
          <Skeleton height={38} />
          <Skeleton height={38} />
          <Skeleton height={38} />
        </div>
      )}

      {error && (
        <div className="settings-pad">
          <Problem>{error}</Problem>
        </div>
      )}

      {sessions !== null && sessions.length > 0 && (
        <div className="row-list">
          {sessions.map((s) => (
            <div className="row" key={s.sid}>
              <div className="grow">
                <div className="row-name">
                  {s.device_name || s.client_type}
                  {s.current && <span className="pill">This browser</span>}
                </div>
                <span className="help">
                  {s.ip_last || "unknown address"} · last used {relativeTime(s.last_used_at)}
                </span>
              </div>
              {!s.current && (
                <button className="btn ghost sm" onClick={() => void revoke(s.sid)}>
                  Sign out
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {confirmAll && (
        <ConfirmDialog
          title="Sign out everywhere else?"
          subtitle="This browser stays signed in. Every other device has to sign in again."
          confirmLabel="Sign out others"
          busy={busy}
          onCancel={() => setConfirmAll(false)}
          onConfirm={() => void revokeOthers()}
        />
      )}
    </div>
  );
}
