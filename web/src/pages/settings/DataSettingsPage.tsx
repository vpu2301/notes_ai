import { useCallback, useEffect, useState } from "react";
import { getAiSettings, putAiSettings } from "../../api/aiSettings";
import { errorMessage } from "../../api/http";
import type { AiProcessor, AiSettings, AiWriter } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { useToast } from "../../components/Toaster";

const money = (cents: number) => `$${(cents / 100).toFixed(2)}`;

/**
 * `/settings/data` — who processes this workspace's meetings.
 *
 * Every member can open it, and that is the point: which companies see
 * your employer's meetings is not admin-only information. The table is
 * built from the same registry object that routes the calls, so it
 * cannot drift from what actually happens to the data — a disclosure
 * page that can be wrong is worse than none, because people believe it.
 *
 * Changing the tier is an admin action, and one with a consequence the
 * admin has to see first: the dialog lists exactly which new companies
 * the change lets in, by name and region, and the API refuses the change
 * unless those exact names come back with it.
 */
export function DataSettingsPage() {
  const toast = useToast();
  const [settings, setSettings] = useState<AiSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pendingTier, setPendingTier] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setSettings(await getAiSettings());
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !settings) return <p className="help danger-text">{error}</p>;
  if (!settings) return <p className="help">Loading…</p>;

  const save = async (body: Parameters<typeof putAiSettings>[0], done: string) => {
    setBusy(true);
    try {
      setSettings(await putAiSettings(body));
      setPendingTier(null);
      toast.success(done);
    } catch (err) {
      toast.error(errorMessage(err));
      // Whatever was refused, the server's own view is the truth.
      await load();
    } finally {
      setBusy(false);
    }
  };

  // Which companies a tier change would newly involve. Computed from the
  // list the server sent, so the dialog and the check agree.
  const unacknowledged = (tier: string): AiProcessor[] =>
    settings.processors.filter((p) => !p.acknowledged && p.tiers.includes(tier));

  const overBudget = settings.month_to_date_cents >= settings.budget_cents;
  const downgraded = settings.effective_tier !== settings.tier;
  // Sprint L2 — who is writing right now, in one line: the processor when
  // it is a company, "the local model" when it is this machine.
  const writerName = (w: AiWriter | null | undefined): string =>
    !w ? "" : w.processor && w.region !== "local" ? `${w.processor} (${w.region})` : "the local model";
  const writer = settings.writer ?? null;
  const fallbackName = writer?.fallback
    ? writer.fallback === writer.backend
      ? null
      : writer.fallback === "dev_mac"
        ? "the local model"
        : writer.fallback
    : null;

  return (
    <div className="settings-stack">
      <section className="card pad settings-card" aria-label="Who processes your meetings">
        <h2 className="settings-h">Who processes your meetings</h2>
        <p className="help">
          Recordings and notes are processed by the companies below, and by nobody else. This
          list is read from the routing configuration itself, so it is what actually happens to
          your data — not a description of it.
        </p>

        {settings.processors.length === 0 ? (
          <p className="help">
            Nothing is routed anywhere in this environment: notes are not written automatically
            here.
          </p>
        ) : writer ? (
          <p className="help" data-testid="ai-writer">
            Notes are written by: <strong>{writerName(writer)}</strong>
            {writer.model_id ? ` · ${writer.model_id}` : ""}
            {fallbackName ? ` · fallback: ${fallbackName}` : ""}
            {writer.reason
              ? ` — the fallback is in use (${writer.reason.replace("_", " ")})`
              : ""}
            {settings.small_writer && settings.small_writer.backend !== writer.backend
              ? `. Titles and names: ${writerName(settings.small_writer)}.`
              : ""}
          </p>
        ) : null}
        {settings.processors.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Company</th>
                <th scope="col">Region</th>
                <th scope="col">What it does</th>
                <th scope="col">Tier</th>
              </tr>
            </thead>
            <tbody>
              {settings.processors.map((p) => (
                <tr key={`${p.name}/${p.region}`}>
                  <th scope="row">{p.name}</th>
                  <td>{p.region.toUpperCase()}</td>
                  <td>{p.purpose}</td>
                  <td>{p.tiers.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {downgraded && (
          <p className="banner banner-warn" role="status">
            Note writing is running on the <strong>{settings.effective_tier}</strong> tier, not{" "}
            <strong>{settings.tier}</strong>:{" "}
            {settings.needs_acknowledgement.map((p) => `${p.name} (${p.region})`).join(", ")}{" "}
            {settings.needs_acknowledgement.length === 1 ? "has" : "have"} not been agreed to for
            this workspace.{" "}
            {settings.can_edit
              ? "Choose the tier again below to review and agree."
              : "A workspace admin can review this."}
          </p>
        )}
      </section>

      <section className="card pad settings-card" aria-label="Model tier">
        <h2 className="settings-h">Quality of written notes</h2>
        <p className="help">
          The standard tier writes every note. The premium tier uses a larger model — slower and
          more expensive, and available on the Pro and Enterprise plans.
        </p>
        <div className="seg" role="group" aria-label="Model tier">
          {["standard", "premium"].map((tier) => (
            <button
              key={tier}
              type="button"
              className="seg-opt"
              aria-pressed={settings.tier === tier}
              disabled={
                !settings.can_edit ||
                busy ||
                (tier === "premium" && !settings.may_choose_premium)
              }
              onClick={() => {
                if (settings.tier === tier) return;
                const needed = unacknowledged(tier);
                if (needed.length > 0) setPendingTier(tier);
                else void save({ tier }, `Notes will be written on the ${tier} tier.`);
              }}
            >
              {tier === "standard" ? "Standard" : "Premium"}
            </button>
          ))}
        </div>
        {!settings.may_choose_premium && (
          <p className="help">The premium tier is available on the Pro and Enterprise plans.</p>
        )}
        {!settings.can_edit && (
          <p className="help">Only a workspace admin can change this.</p>
        )}
      </section>

      <section className="card pad settings-card" aria-label="Automatic note writing">
        <h2 className="settings-h">Automatic note writing</h2>
        <p className="help">
          When this is off, recordings are still transcribed and your own typing is untouched —
          the note simply is not written for you. Notes already written keep every word they have.
        </p>
        <label className="chk-row">
          <input
            type="checkbox"
            checked={settings.generation_enabled}
            disabled={!settings.can_edit || busy}
            onChange={(e) =>
              void save(
                { generation_enabled: e.target.checked },
                e.target.checked ? "Notes will be written automatically." : "Automatic note writing is off.",
              )
            }
          />
          Write notes automatically after a recording
        </label>
      </section>

      <section className="card pad settings-card" aria-label="AI spend">
        <h2 className="settings-h">Spend this month</h2>
        <p className="budget-line">
          <strong>{money(settings.month_to_date_cents)}</strong> of {money(settings.budget_cents)}
        </p>
        <div
          className="meter"
          role="meter"
          aria-valuenow={settings.month_to_date_cents}
          aria-valuemin={0}
          aria-valuemax={settings.budget_cents}
          aria-label="AI spend this month"
        >
          <span
            className={`meter-fill${overBudget ? " over" : ""}`}
            style={{
              width: `${Math.min(100, (settings.month_to_date_cents / Math.max(1, settings.budget_cents)) * 100)}%`,
            }}
          />
        </div>
        {overBudget && (
          <p className="banner banner-warn" role="status">
            This workspace has used its AI budget for the month, so new recordings are
            transcribed but not written up.{" "}
            {settings.can_edit ? "Raise the budget below to continue." : "A workspace admin can raise it."}
          </p>
        )}
        {settings.can_edit && (
          <BudgetField
            cents={settings.budget_cents}
            busy={busy}
            onSave={(cents) => void save({ monthly_budget_cents: cents }, "Budget saved.")}
          />
        )}
      </section>

      {pendingTier && (
        <ConfirmDialog
          title={`Switch to the ${pendingTier} tier?`}
          subtitle="This lets new companies process your meetings. They are listed below by name and region."
          confirmLabel="Agree and switch"
          busy={busy}
          onCancel={() => setPendingTier(null)}
          onConfirm={() =>
            void save(
              {
                tier: pendingTier,
                acknowledge: unacknowledged(pendingTier).map((p) => ({
                  name: p.name,
                  region: p.region,
                })),
              },
              `Notes will be written on the ${pendingTier} tier.`,
            )
          }
        >
          <ul className="ack-list">
            {unacknowledged(pendingTier).map((p) => (
              <li key={`${p.name}/${p.region}`}>
                <strong>{p.name}</strong> — {p.region.toUpperCase()} — {p.purpose}
              </li>
            ))}
          </ul>
        </ConfirmDialog>
      )}
    </div>
  );
}

function BudgetField({
  cents,
  busy,
  onSave,
}: {
  cents: number;
  busy: boolean;
  onSave: (cents: number) => void;
}) {
  const [value, setValue] = useState((cents / 100).toFixed(2));
  useEffect(() => setValue((cents / 100).toFixed(2)), [cents]);
  const parsed = Math.round(Number(value) * 100);
  const valid = Number.isFinite(parsed) && parsed >= 0;

  return (
    <form
      className="budget-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (valid && parsed !== cents) onSave(parsed);
      }}
    >
      <label className="field">
        <span>Monthly budget (USD)</span>
        <input
          className="input"
          inputMode="decimal"
          value={value}
          disabled={busy}
          onChange={(e) => setValue(e.target.value)}
        />
      </label>
      <button className="btn" type="submit" disabled={busy || !valid || parsed === cents}>
        Save
      </button>
    </form>
  );
}
