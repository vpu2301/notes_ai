import { useEffect, useState, type FormEvent } from "react";
import { getSharingPolicy, putSharingPolicy, revokeAllExternal } from "../../api/admin";
import { errorMessage } from "../../api/http";
import { getTenant, patchTenant, uploadLogo } from "../../api/tenants";
import type { SharingPolicy, TenantProfile } from "../../api/types";
import { useAuth } from "../../auth/AuthContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { useToast } from "../../components/Toaster";

const PAID = new Set(["pro", "enterprise"]);

/**
 * `/settings/workspace` — the first admin surface (Sprint 23): how the
 * shared page looks (branding) and how notes may leave the workspace
 * (policy). The API refuses non-admins; the tab is only shown to them.
 */
export function WorkspaceSettingsPage() {
  const { activeTenantId } = useAuth();
  return activeTenantId ? <WorkspaceSettingsForm tenantId={activeTenantId} /> : <p className="help">No workspace selected.</p>;
}

export function WorkspaceSettingsForm({ tenantId }: { tenantId: string }) {
  const toast = useToast();
  const [tenant, setTenant] = useState<TenantProfile | null>(null);
  const [policy, setPolicy] = useState<SharingPolicy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [legalName, setLegalName] = useState("");
  const [contactEmail, setContactEmail] = useState("");

  useEffect(() => {
    let live = true;
    Promise.all([getTenant(tenantId), getSharingPolicy()])
      .then(([t, p]) => {
        if (!live) return;
        setTenant(t);
        setDisplayName(t.display_name);
        setLegalName(t.legal_name);
        setContactEmail(t.contact_email);
        setPolicy(p);
      })
      .catch((err) => live && setError(errorMessage(err)));
    return () => {
      live = false;
    };
  }, [tenantId]);

  const saveBranding = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setTenant(await patchTenant(tenantId, { display_name: displayName, legal_name: legalName, contact_email: contactEmail }));
      toast.success("Branding saved");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const onLogo = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      setError("The logo must be 2 MB or smaller.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setTenant(await uploadLogo(tenantId, file));
      toast.success("Logo updated — shared pages pick it up within a minute");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const savePolicy = async (e: FormEvent) => {
    e.preventDefault();
    if (!policy) return;
    setBusy(true);
    setError(null);
    try {
      setPolicy(await putSharingPolicy(policy));
      toast.success("Sharing policy saved");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const revokeAll = async () => {
    setBusy(true);
    try {
      const r = await revokeAllExternal();
      toast.success(r.notes ? `Links on ${r.notes} note${r.notes === 1 ? "" : "s"} turned off` : "No live links to turn off");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
      setConfirmRevoke(false);
    }
  };

  const paid = PAID.has(tenant?.plan ?? "");
  const set = (patch: Partial<SharingPolicy>) => setPolicy((p) => (p ? { ...p, ...patch } : p));

  return (
    <div className="settings-page" aria-label="Workspace settings">
      {error && (
        <div className="banner banner-danger" role="alert">
          {error}
        </div>
      )}

      {tenant && (
        <form className="settings-section" onSubmit={(e) => void saveBranding(e)} aria-label="Branding">
          <h2>Branding</h2>
          <p className="help">What recipients see at the top of a shared page and in the e-mail.</p>
          <div className="shared-bar shared-preview" aria-label="Preview">
            <span className="shared-logo shared-logo-initials">{tenant.has_logo ? "logo" : (displayName || "?").slice(0, 2).toUpperCase()}</span>
            <span className="shared-brand">{legalName || displayName || tenant.name}</span>
          </div>
          <label className="field">
            <span className="label">Workspace name</span>
            <input className="input" value={displayName} maxLength={200} disabled={busy} onChange={(e) => setDisplayName(e.target.value)} />
          </label>
          <label className="field">
            <span className="label">Legal name (shown on pages and PDFs when set)</span>
            <input className="input" value={legalName} maxLength={200} disabled={busy} onChange={(e) => setLegalName(e.target.value)} />
          </label>
          <label className="field">
            <span className="label">Contact e-mail (reply-to for recipient mail)</span>
            <input className="input" type="email" value={contactEmail} maxLength={320} disabled={busy} onChange={(e) => setContactEmail(e.target.value)} />
          </label>
          <label className="field">
            <span className="label">Logo (PNG, SVG or JPEG, up to 2 MB)</span>
            <input type="file" accept="image/png,image/svg+xml,image/jpeg" disabled={busy} onChange={(e) => void onLogo(e.target.files?.[0])} />
          </label>
          <div className="settings-actions">
            <button className="btn primary" type="submit" disabled={busy}>
              Save branding
            </button>
          </div>
        </form>
      )}

      {policy && (
        <form className="settings-section" onSubmit={(e) => void savePolicy(e)} aria-label="External sharing policy">
          <h2>External sharing</h2>
          <p className="help">How notes may leave this workspace. Applies to every member; links that already exist keep working until you turn them off below.</p>
          <label className="chk-row">
            <input type="checkbox" className="chk" checked={policy.external_links_enabled} disabled={busy} onChange={(e) => set({ external_links_enabled: e.target.checked })} />
            <span>Members may share notes with people outside the workspace (recipient links)</span>
          </label>
          <label className="chk-row">
            <input type="checkbox" className="chk" checked={policy.public_links_enabled} disabled={busy} onChange={(e) => set({ public_links_enabled: e.target.checked })} />
            <span>Members may create "anyone with the link" links</span>
          </label>
          <label className="field">
            <span className="label">Links expire after at most (days)</span>
            <input className="input" type="number" min={1} max={365} value={policy.max_link_days} disabled={busy} onChange={(e) => set({ max_link_days: Math.max(1, Math.min(365, Number(e.target.value) || 1)) })} />
            <span className="help">Longer requests are shortened to this, not refused.</span>
          </label>
          <label className="chk-row">
            <input type="checkbox" className="chk" checked={policy.verified_recipients_required} disabled={busy} onChange={(e) => set({ verified_recipients_required: e.target.checked })} />
            <span>Recipients must confirm an e-mailed code before they can respond</span>
          </label>
          <label className="chk-row">
            <input type="checkbox" className="chk" checked={policy.product_email_enabled} disabled={busy} onChange={(e) => set({ product_email_enabled: e.target.checked })} />
            <span>
              Members may send links by e-mail from the product
              {policy.auto_disabled_reason && <span className="help danger-text"> — switched off after abuse reports; tick to re-enable</span>}
            </span>
          </label>
          <label className="chk-row">
            <input type="checkbox" className="chk" checked={paid ? policy.cta_enabled : true} disabled={busy || !paid} onChange={(e) => set({ cta_enabled: e.target.checked })} />
            <span>
              Show the product line on shared pages
              {!paid && <span className="help"> — always on for free workspaces; a paid plan can turn it off</span>}
            </span>
          </label>
          <div className="settings-actions">
            <button className="btn primary" type="submit" disabled={busy}>
              Save policy
            </button>
            <button className="btn danger-text" type="button" disabled={busy} onClick={() => setConfirmRevoke(true)}>
              Turn off all external links now
            </button>
          </div>
        </form>
      )}

      {confirmRevoke && (
        <ConfirmDialog
          title="Turn off every external link?"
          confirmLabel="Turn off all links"
          busy={busy}
          onConfirm={() => void revokeAll()}
          onCancel={() => setConfirmRevoke(false)}
        >
          Every recipient and public link in this workspace stops working immediately. Recipients keep nothing; senders can create new links afterwards if the policy allows.
        </ConfirmDialog>
      )}
    </div>
  );
}
