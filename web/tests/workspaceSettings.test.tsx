import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessToken, setSessionListener } from "../src/api/http";
import { ToasterProvider } from "../src/components/Toaster";
import { WorkspaceSettingsForm } from "../src/pages/settings/WorkspaceSettingsPage";

const TENANT = { id: "t1", name: "acme", display_name: "Acme", legal_name: "Acme GmbH", locale: "en", timezone: "UTC", logo_url: "", has_logo: false, contact_email: "hello@acme.com", plan: "free" };
const POLICY = { external_links_enabled: true, public_links_enabled: true, max_link_days: 180, verified_recipients_required: false, product_email_enabled: true, cta_enabled: true, auto_disabled_reason: null };

function server() {
  const calls: { method: string; path: string; body: Record<string, unknown> | null }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: unknown, init?: RequestInit) => {
    const path = new URL(String(url)).pathname;
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body && typeof init.body === "string" ? JSON.parse(init.body) : null;
    calls.push({ method, path, body });
    const reply = path.startsWith("/tenants/") ? (method === "PATCH" ? { ...TENANT, ...body } : TENANT) : method === "PUT" ? body : POLICY;
    return new Response(JSON.stringify(reply), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
  return calls;
}

beforeEach(() => {
  setSessionListener({});
  setAccessToken("x");
});
afterEach(() => vi.unstubAllGlobals());

describe("workspace settings", () => {
  it("round-trips the policy and locks the CTA row on a free plan", async () => {
    const calls = server();
    render(<ToasterProvider><WorkspaceSettingsForm tenantId="t1" /></ToasterProvider>);
    const publicLinks = await screen.findByLabelText(/anyone with the link/i);
    expect(publicLinks).toBeChecked();
    expect(screen.queryByLabelText(/only finalized notes/i)).toBeNull();
    expect(screen.getByLabelText(/show the product line/i)).toBeDisabled();
    await userEvent.click(publicLinks);
    await userEvent.click(screen.getByRole("button", { name: /save policy/i }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "PUT" && c.path.endsWith("/policy"))?.body).toMatchObject({ public_links_enabled: false, max_link_days: 180 }),
    );
  });

  it("saves branding through the tenant profile", async () => {
    const calls = server();
    render(<ToasterProvider><WorkspaceSettingsForm tenantId="t1" /></ToasterProvider>);
    const email = await screen.findByLabelText(/contact e-mail/i);
    await userEvent.clear(email);
    await userEvent.type(email, "team@acme.com");
    await userEvent.click(screen.getByRole("button", { name: /save branding/i }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toMatchObject({ contact_email: "team@acme.com" }));
  });
});
