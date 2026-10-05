// The workspace's plan, this month's usage, and changing the plan (0068).
// An admin's page: the API answers 403 to everyone else.
import { api } from "./http";
import type { Billing, BillingInterval, ChangePlanResult } from "./types";

export function getBilling(): Promise<Billing> {
  return api<Billing>("note", "/v1/billing");
}

/** `applied`: the plan already changed. `redirect`: pay at `redirect_url`
 *  first (Stripe Checkout) — the plan changes when the payment lands. */
export function changePlan(plan: string, interval: BillingInterval = "monthly"): Promise<ChangePlanResult> {
  return api<ChangePlanResult>("note", "/v1/billing/plan", { method: "POST", json: { plan, interval } });
}

/** Spend a redeem code on this workspace (0069). Works without payments. */
export function redeemCode(code: string): Promise<ChangePlanResult> {
  return api<ChangePlanResult>("note", "/v1/billing/redeem", { method: "POST", json: { code } });
}
