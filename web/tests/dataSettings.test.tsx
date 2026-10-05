import "@testing-library/jest-dom/vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessToken, setSessionListener } from "../src/api/http";
import { ToasterProvider } from "../src/components/Toaster";
import { DataSettingsPage } from "../src/pages/settings/DataSettingsPage";

const HETZNER = {
  name: "Hetzner",
  region: "eu",
  purpose: "writing your meeting notes",
  tiers: ["standard"],
  acknowledged: true,
};
const ANTHROPIC = {
  name: "Anthropic",
  region: "us",
  purpose: "writing your meeting notes",
  tiers: ["premium"],
  acknowledged: false,
};

const SETTINGS = {
  provider: "platform",
  tier: "standard",
  generation_enabled: true,
  effective_provider: "platform",
  effective_tier: "standard",
  processors: [HETZNER, ANTHROPIC],
  needs_acknowledgement: [],
  month_to_date_cents: 314,
  budget_cents: 2000,
  may_choose_premium: true,
  can_edit: true,
};

function server(settings: Record<string, unknown> = SETTINGS) {
  const calls: { method: string; body: Record<string, unknown> | null }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: unknown, init?: RequestInit) => {
      const method = (init?.method ?? "GET").toUpperCase();
      const body = init?.body && typeof init.body === "string" ? JSON.parse(init.body) : null;
      calls.push({ method, body });
      const reply = method === "PUT" ? { ...settings, ...body } : settings;
      return new Response(JSON.stringify(reply), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return calls;
}

// Each section of the page is its own view (?view=); the default is Processing.
const page = (view?: "writing" | "spend") =>
  render(
    <MemoryRouter initialEntries={[view ? `/settings/data?view=${view}` : "/settings/data"]}>
      <ToasterProvider>
        <DataSettingsPage />
      </ToasterProvider>
    </MemoryRouter>,
  );

beforeEach(() => {
  setSessionListener({});
  setAccessToken("x");
});
afterEach(() => vi.unstubAllGlobals());

describe("Settings › Data & AI", () => {
  it("lists every company in the data path, with what it does", async () => {
    server();
    page();
    expect(await screen.findByRole("row", { name: /Hetzner/ })).toHaveTextContent("EU");
    expect(screen.getByRole("row", { name: /Anthropic/ })).toHaveTextContent(
      "writing your meeting notes",
    );
  });

  it("makes the admin agree to the new processor before switching tier", async () => {
    const calls = server();
    page("writing");
    await userEvent.click(await screen.findByRole("button", { name: "Premium" }));

    // The dialog names exactly what the change lets in.
    const dialog = await screen.findByText(/lets new companies process your meetings/i);
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole("listitem")).toHaveTextContent("Anthropic");

    await userEvent.click(screen.getByRole("button", { name: /agree and switch/i }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
        tier: "premium",
        acknowledge: [{ name: "Anthropic", region: "us" }],
      }),
    );
  });

  it("is read-only for a member", async () => {
    server({ ...SETTINGS, can_edit: false });
    page("writing");
    expect(await screen.findByRole("button", { name: "Premium" })).toBeDisabled();
    expect(screen.getByRole("checkbox")).toBeDisabled();
    expect(screen.getByText(/only a workspace admin/i)).toBeInTheDocument();
  });

  it("says plainly when the month's budget is spent", async () => {
    server({ ...SETTINGS, month_to_date_cents: 2100 });
    page("spend");
    // The toaster mounts its own empty role="status" region, so match the sentence.
    expect(await screen.findByText(/used its AI budget for the month/i)).toBeInTheDocument();
  });

  it("shows what a workspace is actually running on when routing gained a processor", async () => {
    server({
      ...SETTINGS,
      tier: "premium",
      effective_tier: "standard",
      needs_acknowledgement: [ANTHROPIC],
    });
    page();
    const notice = await screen.findByText(/note writing is running on the/i);
    expect(notice).toHaveTextContent("standard");
    expect(notice).toHaveTextContent("Anthropic");
  });
});
