import { useEffect, useState, type FormEvent } from "react";
import * as authApi from "../api/auth";
import { useAuth } from "../auth/AuthContext";
import { messageFor } from "../lib/errorCopy";
import { AlertIcon } from "./icons";
import type { ReauthOptions } from "../api/types";

/**
 * The single step-up prompt.
 *
 * Mounted once, at the root. `http.ts` opens it on a 403 `reauth_required`
 * and retries the original request when it resolves — so no page handles a
 * step-up itself, and no page can forget to.
 *
 * The **server** decides how the person proves themselves
 * (`POST /auth/reauth/start`): an MFA account is asked for its
 * authenticator, everyone else is mailed a code. Offering a menu here would
 * let a caller pick the weakest option on the account.
 */
export function ReauthDialog() {
  const { reauthPending, resolveReauth } = useAuth();
  const [options, setOptions] = useState<ReauthOptions | null>(null);
  const [method, setMethod] = useState<"totp" | "recovery_code" | "email_code">("email_code");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!reauthPending) {
      setOptions(null);
      setCode("");
      setError(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const opts = await authApi.reauthStart();
        if (cancelled) return;
        setOptions(opts);
        setMethod(opts.methods.includes("totp") ? "totp" : "email_code");
      } catch (err) {
        if (cancelled) return;
        setError(messageFor(err));
        setOptions({ methods: [], challenge_id: null, expires_in: 0 });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [reauthPending]);

  useEffect(() => {
    if (!reauthPending) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") resolveReauth(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [reauthPending, resolveReauth]);

  if (!reauthPending) return null;

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const cleaned = method === "recovery_code" ? code.trim().replace(/[\s-]/g, "") : code.trim();
      await authApi.reauth(method, cleaned, options?.challenge_id);
      resolveReauth(true);
    } catch (err) {
      setError(messageFor(err));
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  const canRecover = (options?.methods ?? []).includes("recovery_code");
  const prompt =
    method === "totp"
      ? "Enter the code from your authenticator app."
      : method === "recovery_code"
        ? "Enter one of your recovery codes."
        : "We emailed you a code. Enter it to continue.";

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && resolveReauth(false)}>
      <form className="modal" onSubmit={(e) => void onSubmit(e)} role="dialog" aria-modal="true" aria-label="Confirm it's you">
        <div className="modal-h">
          <h2>Confirm it's you</h2>
          <p>{options === null ? "One moment…" : prompt}</p>
        </div>
        <div className="modal-b">
          {options !== null && options.methods.length > 0 && (
            <label className="login-field">
              <span>{method === "recovery_code" ? "Recovery code" : "Code"}</span>
              <input
                name="reauth-code"
                inputMode={method === "recovery_code" ? "text" : "numeric"}
                autoComplete="one-time-code"
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
          )}
          {canRecover && (
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                setMethod(method === "totp" ? "recovery_code" : "totp");
                setCode("");
                setError(null);
              }}
            >
              {method === "totp" ? "Use a recovery code" : "Use my authenticator app"}
            </button>
          )}
          {error && (
            <div className="banner banner-danger" role="alert">
              <AlertIcon size={15} />
              <span className="grow">{error}</span>
            </div>
          )}
        </div>
        <div className="modal-f">
          <button type="button" className="btn ghost" onClick={() => resolveReauth(false)} disabled={busy}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn primary"
            disabled={busy || options === null || options.methods.length === 0}
          >
            {busy ? "Checking…" : "Confirm"}
          </button>
        </div>
      </form>
    </div>
  );
}
