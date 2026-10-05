import { useCallback, useEffect, useState, type FormEvent } from "react";
import { changePlan, getBilling, redeemCode } from "../../api/billing";
import type { Billing, BillingInterval, BillingPlan, UsageMeter } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Segmented } from "../../components/Segmented";
import { useToast } from "../../components/Toaster";
import { messageFor } from "../../lib/errorCopy";
import { useSettingsView } from "../../lib/useSettingsView";

const VIEWS = [
  { value: "overview", label: "Overview" },
  { value: "plans", label: "Plans" },
] as const;

const METER_LABEL: Record<UsageMeter["key"], string> = {
  notes: "Notes",
  recording_minutes: "Recording minutes",
  members: "Members",
  ai: "AI allowance",
};

function money(cents: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits: cents % 100 === 0 ? 0 : 2,
  }).format(cents / 100);
}

/** "€18 per member / month", or paid yearly "€15 per member / month,
 *  billed yearly (€180)". A plan with no yearly price shows its monthly one. */
export function price(plan: BillingPlan, interval: BillingInterval = "monthly"): string {
  if (plan.price_cents === null) return "Talk to us";
  if (plan.price_cents === 0) return "Free";
  if (interval === "yearly" && plan.yearly_price_cents !== null) {
    const perMonth = Math.round(plan.yearly_price_cents / 12);
    return `${money(perMonth, plan.currency)} per member / month, billed yearly (${money(plan.yearly_price_cents, plan.currency)})`;
  }
  return `${money(plan.price_cents, plan.currency)} per member / month`;
}

/** The best yearly saving in the catalogue, in whole percent ("save 17%"). */
export function yearlySaving(plans: BillingPlan[]): number {
  let best = 0;
  for (const p of plans) {
    if (p.price_cents && p.yearly_price_cents !== null) {
      best = Math.max(best, 1 - p.yearly_price_cents / (12 * p.price_cents));
    }
  }
  return Math.round(best * 100);
}

/** "4 of 50", "50 min of 300", or "12% used" for the AI allowance —
 *  what the model calls cost us is not the customer's number. */
export function meterText(m: UsageMeter): string {
  if (m.key === "ai") {
    if (m.limit === null) return "No limit";
    return `${m.limit > 0 ? Math.min(100, Math.round((m.used / m.limit) * 100)) : 100}% used`;
  }
  const used = m.used.toLocaleString();
  return m.limit === null ? `${used} · no limit` : `${used} of ${m.limit.toLocaleString()}`;
}

function share(m: UsageMeter): number | null {
  if (m.limit === null) return null;
  return m.limit > 0 ? Math.min(1, m.used / m.limit) : 1;
}

/**
 * `/settings/billing` — the workspace's plan, this month's usage, and the
 * plans it can move to. An admin's page (the tab is hidden for everyone
 * else and the API answers 403).
 *
 * Payments are not connected yet: a change applies at once where the
 * server allows it (`manual`), and is refused with a reason where it does
 * not. When Stripe arrives the server answers `redirect` and the page
 * simply follows the URL.
 */
export function BillingSettingsPage() {
  const toast = useToast();
  const [billing, setBilling] = useState<Billing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<BillingPlan | null>(null);
  // The interval the plans are priced in; starts on what the workspace pays.
  const [chosenInterval, setChosenInterval] = useState<BillingInterval | null>(null);
  const [busy, setBusy] = useState(false);
  // In the URL, so a link can open the plans directly (?view=plans).
  const [view, setView] = useSettingsView(VIEWS);

  const load = useCallback(async () => {
    try {
      setBilling(await getBilling());
      setError(null);
    } catch (err) {
      setError(messageFor(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (error && !billing) return <p className="help danger-text">{error}</p>;
  if (!billing) return <p className="help">Loading…</p>;

  const current = billing.plan;
  const currentInterval: BillingInterval = billing.subscription?.interval ?? "monthly";
  const shownInterval: BillingInterval = chosenInterval ?? currentInterval;
  const saving = yearlySaving(billing.plans);
  // On this plan AND paying this way. A plan with no yearly price has one way.
  const isCurrentChoice = (p: BillingPlan) =>
    p.code === current.code && (p.yearly_price_cents === null || shownInterval === currentInterval);
  const month = new Date(billing.period_start).toLocaleDateString(undefined, {
    month: "long",
  });
  const sub = billing.subscription;

  const switchTo = async (plan: BillingPlan) => {
    setBusy(true);
    try {
      const result = await changePlan(plan.code, shownInterval);
      if (result.action === "redirect" && result.redirect_url) {
        window.location.assign(result.redirect_url);
        return;
      }
      setBilling(result.billing);
      setPending(null);
      toast.success(`This workspace is on ${result.billing.plan.name} now.`);
    } catch (err) {
      toast.error(messageFor(err));
      setPending(null);
      await load();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="settings-stack">
      <Segmented label="Billing" options={VIEWS} value={view} onChange={setView} />

      {view === "overview" && (
        <>
          <section className="card pad settings-card" aria-label="Plan">
            <div className="settings-row">
              <div>
                <h2 className="settings-h">{current.name}</h2>
                <p className="help">{current.summary}</p>
              </div>
              <div className="settings-value">{price(current, currentInterval)}</div>
            </div>
            {sub?.status === "past_due" && (
              <p className="banner banner-warn" role="status">
                The last payment did not go through. Update the payment method to keep {current.name}.
              </p>
            )}
            {sub?.current_period_end && (
              <p className="help">
                {sub.provider === "code" ? "From a code · ends" : sub.cancel_at_period_end ? "Ends" : "Renews"} on{" "}
                {new Date(sub.current_period_end).toLocaleDateString()}.
              </p>
            )}
            {billing.can_edit && <RedeemCode onRedeemed={setBilling} />}
        {!billing.payments_connected && (
              <p className="help">
                Payments aren't connected yet — invoices and the payment method will appear here.
              </p>
            )}
          </section>

          <section className="card pad settings-card" aria-label="Usage this month">
            <h2 className="settings-h">Usage in {month}</h2>
            <ul className="usage-meters">
              {billing.usage.map((m) => {
                const s = share(m);
                return (
                  <li key={m.key} className="usage-meter">
                    <div className="usage-meter-h">
                      <span>{METER_LABEL[m.key]}</span>
                      <span className="usage-meter-v">{meterText(m)}</span>
                    </div>
                    {s !== null && (
                      <div
                        className={`usage-bar ${s >= 1 ? "full" : s >= 0.8 ? "near" : ""}`}
                        role="meter"
                        aria-label={METER_LABEL[m.key]}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={Math.round(s * 100)}
                      >
                        <span
                          style={{
                            width: `${Math.round(s * 100)}%`,
                          }}
                        />
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        </>
      )}

      {view === "plans" && (
        <section className="settings-card" aria-label="Plans">
          <Segmented
            label="Billing interval"
            options={[
              { value: "monthly", label: "Monthly" },
              { value: "yearly", label: saving > 0 ? `Yearly · save ${saving}%` : "Yearly" },
            ]}
            value={shownInterval}
            onChange={setChosenInterval}
          />
          <div className="plan-grid">
            {billing.plans.map((p) => {
              const isCurrent = isCurrentChoice(p);
              const samePlan = p.code === current.code;
              return (
                <div key={p.code} className={`card pad plan-card ${isCurrent ? "current" : ""}`}>
                  <div className="plan-card-h">
                    <strong>{p.name}</strong>
                    {isCurrent && <span className="pill">Current</span>}
                  </div>
                  <div className="plan-price">{price(p, shownInterval)}</div>
                  <p className="help">{p.summary}</p>
                  {p.features.length > 0 && (
                    <ul className="plan-features">
                      {p.features.map((f) => (
                        <li key={f}>{f}</li>
                      ))}
                    </ul>
                  )}
                  {billing.can_edit && !isCurrent && (
                    <div className="plan-action">
                      {p.self_serve ? (
                        <button
                          className={`btn ${(p.price_cents ?? 0) > (current.price_cents ?? 0) ? "primary" : ""}`}
                          disabled={busy || !billing.payments_connected}
                          title={billing.payments_connected ? undefined : "Payments aren't connected yet"}
                          onClick={() => setPending(p)}
                        >
                          {samePlan ? `Switch to ${shownInterval}` : `Switch to ${p.name}`}
                        </button>
                      ) : (
                        <span className="help">Get in touch to set it up.</span>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {pending && (
        <ConfirmDialog
          title={
            pending.code === current.code ? `Pay for ${pending.name} ${shownInterval}?` : `Switch to ${pending.name}?`
          }
          subtitle={`${price(pending, shownInterval)}. The change applies to this workspace at once.`}
          confirmLabel={pending.code === current.code ? `Switch to ${shownInterval}` : `Switch to ${pending.name}`}
          busy={busy}
          onCancel={() => setPending(null)}
          onConfirm={() => void switchTo(pending)}
        />
      )}
    </div>
  );
}

/** "Have a code?" — a link that opens one field. A code puts the
 *  workspace on a plan, for a time or for good, with no payment. */
function RedeemCode({ onRedeemed }: { onRedeemed: (b: Billing) => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) {
    return (
      <button type="button" className="link-btn redeem-open" onClick={() => setOpen(true)}>
        Have a code?
      </button>
    );
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await redeemCode(code);
      onRedeemed(result.billing);
      const end = result.billing.subscription?.current_period_end;
      toast.success(
        `This workspace is on ${result.billing.plan.name}` +
          (end ? ` until ${new Date(end).toLocaleDateString()}.` : " now."),
      );
      setCode("");
      setOpen(false);
    } catch (err) {
      setError(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="redeem-form" onSubmit={(e) => void submit(e)}>
      <label className="field redeem-field">
        <span className="label">Redeem code</span>
        <input
          className="mono"
          autoFocus
          autoComplete="off"
          spellCheck={false}
          placeholder="XXXX-XXXX-XXXX-XXXX"
          maxLength={64}
          value={code}
          disabled={busy}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? "redeem-error" : undefined}
          onChange={(e) => {
            setCode(e.target.value.toUpperCase());
            setError(null);
          }}
        />
      </label>
      <div className="settings-actions">
        <button className="btn primary" type="submit" disabled={busy || !code.trim()}>
          Redeem
        </button>
        <button className="btn ghost" type="button" disabled={busy} onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {error && (
        <p id="redeem-error" className="help danger-text" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}
