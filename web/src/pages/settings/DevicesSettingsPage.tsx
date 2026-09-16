import { useCallback, useEffect, useState, type FormEvent } from "react";
import * as account from "../../api/account";
import { isUnavailableHere } from "../../api/auth";
import { BASES } from "../../api/http";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { SecretOnce } from "../../components/SecretOnce";
import { Skeleton } from "../../components/Skeleton";
import { useToast } from "../../components/Toaster";
import { relativeTime } from "../../lib/time";
import { messageFor } from "../../lib/errorCopy";
import type { Credential } from "../../api/types";
import { Problem } from "./AccountSettingsPage";

/**
 * `/settings/devices` — the meeting-room capture boxes (IDX-B1b).
 *
 * These are non-human principals: each holds a client id and secret and
 * exchanges them at `POST /auth/oauth/token` for a short-lived token with
 * the `device` role. The secret is returned exactly once, on create and on
 * rotate, and the server keeps only its hash — so there is no "show it
 * again", and this page never offers one.
 */
export function DevicesSettingsPage() {
  const { activeTenantId, memberships } = useAuth();
  const toast = useToast();
  const [devices, setDevices] = useState<Credential[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  /** The secret currently on screen. Never persisted, cleared on dismiss. */
  const [reveal, setReveal] = useState<{ title: string; lines: string[]; note?: string } | null>(
    null,
  );
  const [revoking, setRevoking] = useState<Credential | null>(null);

  const active = memberships.find((m) => m.tenant_id === activeTenantId);
  const personal = active?.kind === "personal";

  const load = useCallback(async () => {
    if (!activeTenantId) return;
    try {
      setDevices(await account.listDevices(activeTenantId));
      setError(null);
    } catch (err) {
      setDevices([]);
      setError(
        isUnavailableHere(err)
          ? "Room devices aren't available in this deployment."
          : messageFor(err),
      );
    }
  }, [activeTenantId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!activeTenantId) return null;

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const created = await account.createDevice(activeTenantId, name.trim());
      setCreating(false);
      setName("");
      setReveal({
        title: `Credentials for ${created.credential.name}`,
        lines: [
          `client_id=${created.credential.id}`,
          `client_secret=${created.secret}`,
          `token_url=${BASES.auth}/auth/oauth/token`,
        ],
      });
      await load();
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const rotate = async (device: Credential) => {
    setBusy(true);
    try {
      const rotated = await account.rotateDevice(activeTenantId, device.id);
      setReveal({
        title: `New secret for ${device.name}`,
        lines: [`client_id=${device.id}`, `client_secret=${rotated.secret}`],
        note: `The previous secret keeps working until ${new Date(
          rotated.old_expires_at,
        ).toLocaleString()} — deploy this one before then.`,
      });
      await load();
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (device: Credential) => {
    setBusy(true);
    try {
      await account.revokeDevice(activeTenantId, device.id);
      toast.success(`${device.name} can no longer sign in.`);
      setRevoking(null);
      await load();
    } catch (err) {
      toast.error(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  if (personal) {
    return (
      <div className="card pad settings-card">
        <h2 className="settings-h">Room devices</h2>
        <p className="help">
          A personal workspace has one member and no meeting room. Create a team workspace to
          register capture devices.
        </p>
      </div>
    );
  }

  return (
    <div className="settings-stack">
      <div className="card settings-card">
        <div className="settings-card-h">
          <div>
            <h2 className="settings-h">Room devices</h2>
            <span className="help">
              Capture boxes that record into this workspace without a person signing in.
            </span>
          </div>
          <button className="btn primary sm" onClick={() => setCreating(true)}>
            Add device
          </button>
        </div>

        {devices === null && (
          <div className="settings-pad settings-stack-sm">
            <Skeleton height={38} />
            <Skeleton height={38} />
          </div>
        )}

        {error && (
          <div className="settings-pad">
            <Problem>{error}</Problem>
          </div>
        )}

        {devices !== null && devices.length === 0 && !error && (
          <div className="settings-pad">
            <p className="help">No devices yet.</p>
          </div>
        )}

        {devices !== null && devices.length > 0 && (
          <div className="row-list">
            {devices.map((d) => (
              <div className="row" key={d.id}>
                <div className="grow">
                  <div className="row-name">
                    {d.name}
                    {d.status !== "active" && <span className="pill">{d.status}</span>}
                  </div>
                  <span className="help">
                    {d.last_used_at ? `last seen ${relativeTime(d.last_used_at)}` : "never used"}
                    {d.secrets.length > 1 && " · rotating"}
                  </span>
                </div>
                <div className="settings-actions">
                  <button className="btn ghost sm" disabled={busy} onClick={() => void rotate(d)}>
                    Rotate secret
                  </button>
                  <button className="btn ghost sm" disabled={busy} onClick={() => setRevoking(d)}>
                    Revoke
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {creating && (
        <ConfirmDialog
          title="Add a room device"
          subtitle="Name it after the room, so you know which box to re-flash later."
          confirmLabel="Create"
          busy={busy}
          onCancel={() => {
            setCreating(false);
            setName("");
          }}
          onConfirm={() => void create({ preventDefault: () => {} } as FormEvent)}
        >
          <label className="field">
            <span className="label">Name</span>
            <input
              type="text"
              autoFocus
              maxLength={120}
              placeholder="Boardroom"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </label>
        </ConfirmDialog>
      )}

      {reveal && (
        <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && setReveal(null)}>
          <div className="modal" role="dialog" aria-modal="true" aria-label={reveal.title}>
            <div className="modal-h">
              <h2>{reveal.title}</h2>
              <p>Copy these into the device now — the secret is not shown again.</p>
            </div>
            <div className="modal-b">
              <SecretOnce
                title="Device credentials"
                values={reveal.lines}
                filename="notes-ai-device.env"
                hint={reveal.note}
              />
            </div>
            <div className="modal-f">
              <button className="btn primary" onClick={() => setReveal(null)}>
                I've copied them
              </button>
            </div>
          </div>
        </div>
      )}

      {revoking && (
        <ConfirmDialog
          title={`Revoke ${revoking.name}?`}
          subtitle="The device stops being able to sign in immediately. This cannot be undone."
          confirmLabel="Revoke"
          confirmDanger
          busy={busy}
          onCancel={() => setRevoking(null)}
          onConfirm={() => void revoke(revoking)}
        />
      )}
    </div>
  );
}
