// The workspace's plan, usage and plan changes. Admin only (403 otherwise).
import { api } from "./http";
import type { Billing, BillingInterval, ChangePlanResult } from "./types";

export function getBilling(): Promise<Billing> {
  return api<Billing>("note", "/v1/billing");
}

/** `applied`: already changed. `redirect`: pay at `redirect_url` first. */
export function changePlan(plan: string, interval: BillingInterval = "monthly"): Promise<ChangePlanResult> {
  return api<ChangePlanResult>("note", "/v1/billing/plan", { method: "POST", json: { plan, interval } });
}

/** Spend a redeem code on this workspace. Works without payments. */
export function redeemCode(code: string): Promise<ChangePlanResult> {
  return api<ChangePlanResult>("note", "/v1/billing/redeem", { method: "POST", json: { code } });
}
