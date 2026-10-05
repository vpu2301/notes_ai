import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { setAccessToken, setSessionListener } from "../src/api/http";
import { ToasterProvider } from "../src/components/Toaster";
import { BillingSettingsPage } from "../src/pages/settings/BillingSettingsPage";

const plan = (code: string, name: string) => ({
  code, name, summary: "", price_cents: code === "free" ? 0 : 1800, currency: "EUR",
  limits: {}, features: [], self_serve: true,
});
const BILLING = {
  plan: plan("free", "Free"),
  plans: [plan("free", "Free"), plan("pro", "Pro")],
  usage: [],
  period_start: "2026-10-01T00:00:00Z",
  subscription: null,
  payments_connected: false,
  can_edit: true,
};

function stub(redeem: (code: string) => Response) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown, init?: RequestInit) => {
      const path = new URL(String(url)).pathname;
      if (path.endsWith("/v1/billing/redeem")) return redeem(JSON.parse(String(init?.body)).code);
      return new Response(JSON.stringify(BILLING), { status: 200, headers: { "Content-Type": "application/json" } });
    }),
  );
}

const page = () =>
  render(
    <MemoryRouter>
      <ToasterProvider>
        <BillingSettingsPage />
      </ToasterProvider>
    </MemoryRouter>,
  );

beforeEach(() => {
  setSessionListener({});
  setAccessToken("x");
});
afterEach(() => vi.unstubAllGlobals());

describe("Billing › redeem code", () => {
  it("says why a code was refused, then applies a good one", async () => {
    stub((code) =>
      code === "GOOD-CODE-1234"
        ? new Response(
            JSON.stringify({
              action: "applied",
              redirect_url: null,
              billing: {
                ...BILLING,
                plan: plan("pro", "Pro"),
                subscription: { provider: "code", status: "active", current_period_end: "2026-11-02T00:00:00Z", cancel_at_period_end: true },
              },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          )
        : new Response(JSON.stringify({ status: 404, title: "Not Found", code: "redeem_unknown" }), {
            status: 404,
            headers: { "Content-Type": "application/problem+json" },
          }),
    );
    page();
    await userEvent.click(await screen.findByRole("button", { name: "Have a code?" }));
    const field = screen.getByLabelText("Redeem code");
    await userEvent.type(field, "nope-nope");
    await userEvent.click(screen.getByRole("button", { name: "Redeem" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That code isn't valid");

    await userEvent.clear(field);
    await userEvent.type(field, "good-code-1234");
    await userEvent.click(screen.getByRole("button", { name: "Redeem" }));
    expect(await screen.findByText(/From a code · ends on/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pro" })).toBeInTheDocument();
  });
});
