import { describe, expect, it } from "vitest";
import { meterText, price, yearlySaving } from "../src/pages/settings/BillingSettingsPage";
import type { BillingPlan } from "../src/api/types";

const plan = (over: Partial<BillingPlan>): BillingPlan => ({
  code: "pro",
  name: "Pro",
  summary: "",
  price_cents: 1800,
  currency: "EUR",
  yearly_price_cents: 18000,
  limits: {},
  features: [],
  self_serve: true,
  ...over,
});

describe("billing copy", () => {
  it("names free and contact-us plans in words", () => {
    expect(price(plan({ price_cents: 0 }))).toBe("Free");
    expect(price(plan({ price_cents: null }))).toBe("Talk to us");
    expect(price(plan({}))).toMatch(/18.*per member \/ month/);
  });

  it("shows the AI allowance as a share, never as our cost", () => {
    expect(meterText({ key: "ai", used: 150, limit: 2000 })).toBe("8% used");
    expect(meterText({ key: "ai", used: 5000, limit: 2000 })).toBe("100% used");
  });

  it("counts against the limit, or says there is none", () => {
    expect(meterText({ key: "notes", used: 4, limit: 50 })).toBe("4 of 50");
    expect(meterText({ key: "members", used: 7, limit: null })).toBe("7 · no limit");
  });

  it("prices a yearly plan per month with the yearly total, and names the saving", () => {
    expect(price(plan({}), "yearly")).toMatch(/15.*per member \/ month, billed yearly \(.*180/);
    // A plan with no yearly price keeps its monthly one.
    expect(price(plan({ yearly_price_cents: null }), "yearly")).toMatch(/18.*per member \/ month$/);
    expect(yearlySaving([plan({})])).toBe(17);
  });
});
