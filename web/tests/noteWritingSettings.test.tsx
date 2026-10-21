import "@testing-library/jest-dom/vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessToken, setSessionListener } from "../src/api/http";
import { GenerationStatus } from "../src/components/GenerationStatus";
import { ToasterProvider } from "../src/components/Toaster";
import { NoteWritingSettingsPage } from "../src/pages/settings/NoteWritingSettingsPage";
import { SettingsLayout } from "../src/pages/settings/SettingsLayout";

const auth = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
vi.mock("../src/auth/AuthContext", () => ({
  useAuth: () => auth.value,
  useAuthOptional: () => auth.value,
}));

const PARAMS = {
  temperature: 0.4,
  max_output_tokens: 4096,
  max_concurrency: 2,
  ask_temperature: 0.2,
  ask_max_tokens: 700,
};
const LIMITS = {
  temperature: { min: 0, max: 0.7, step: 0.1, default: 0 },
  max_output_tokens: { min: 512, max: 8192, default: 4096 },
  max_concurrency: { min: 1, max: 8, default: 4, cap: 2, cap_source: "backend" },
  ask_temperature: { min: 0, max: 1, step: 0.1, default: 0.2 },
  ask_max_tokens: { min: 200, max: 2000, default: 700 },
};
const SETTINGS = {
  provider: "platform", tier: "standard", generation_enabled: true,
  effective_provider: "platform", effective_tier: "standard", processors: [],
  needs_acknowledgement: [], month_to_date_cents: 0, budget_cents: 2000,
  may_choose_premium: true, can_edit: true,
  model_params: PARAMS, model_params_effective: PARAMS, model_params_version: 2,
  model_params_valid: true, model_params_limits: LIMITS,
  model_params_measured: { temperature: { "0.2": null, "0.4": null, "0.7": null } },
}; // prettier-ignore
const INSTRUCTIONS = {
  scope: "workspace", version: 1, text: "Length: short. Four summary sentences at most.",
  profile: {}, profile_hash: "", compile_status: "compiled", compile_error_kind: null,
  understood: [], guidance: [], not_applied: [], can_edit: true, max_chars: 4000,
  updated_at: null, updated_by: null,
}; // prettier-ignore
const TEMPLATES = [
  { name: "meeting", language: "en", source: "workspace", markdown: "## Decisions\n- one per line",
    can_edit: true, updated_at: "2026-10-21T10:00:00Z", updated_by: "u1" },
  { name: "memo", language: "en", source: "builtin", markdown: "## Summary\n- the point",
    can_edit: true, updated_at: null, updated_by: null },
]; // prettier-ignore

function server(canEdit: boolean) {
  const gets: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown, init?: RequestInit) => {
      const path = new URL(String(url), "http://x").pathname;
      if ((init?.method ?? "GET") === "GET") gets.push(path);
      const body = path.endsWith("/v1/ai/instructions")
        ? { ...INSTRUCTIONS, can_edit: canEdit }
        : path.endsWith("/v1/ai/templates")
          ? TEMPLATES.map((t) => ({ ...t, can_edit: canEdit }))
          : { ...SETTINGS, can_edit: canEdit };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return gets;
}

function signedIn(role: string) {
  auth.value = { status: "authenticated", activeRole: role, memberships: [], logout: vi.fn() };
}

const writing = (url = "/settings/writing") =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <ToasterProvider>
        <Routes>
          <Route path="/settings" element={<SettingsLayout />}>
            <Route path="writing" element={<NoteWritingSettingsPage />} />
            <Route path="account" element={<p>account</p>} />
          </Route>
        </Routes>
      </ToasterProvider>
    </MemoryRouter>,
  );

beforeEach(() => {
  setSessionListener({});
  setAccessToken("x");
});
afterEach(() => vi.unstubAllGlobals());

describe("Settings › Note writing", () => {
  it("is in the Workspace nav for a member and an admin, not for a guest", () => {
    for (const [role, shown] of [
      ["member", true],
      ["owner", true],
      ["guest", false],
    ] as const) {
      signedIn(role);
      server(role === "owner");
      const { unmount } = writing("/settings/account");
      const nav = screen.getByRole("navigation", { name: "Settings sections" });
      expect(!!within(nav).queryByRole("link", { name: "Note writing" })).toBe(shown);
      unmount();
    }
  });

  it("shows a member every section read-only, after exactly three GETs", async () => {
    signedIn("member");
    const gets = server(false);
    const { container } = writing();
    expect(
      (await screen.findAllByText("Only a workspace admin can change these.")).length,
    ).toBeGreaterThan(0);
    expect(await screen.findByText(/Four summary sentences at most/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Meeting" })).toBeInTheDocument();
    for (const label of ["Templates", "Note instructions", "Automatic note writing"]) {
      expect(container.querySelector(`[aria-label='${label}']`)).not.toBeNull();
    }
    expect(container.querySelector(".model-behaviour")).not.toBeNull();
    expect(container.querySelectorAll("input:not([disabled]), textarea, select").length).toBe(0);
    // Tabs and template names only open views; nothing edits.
    expect(
      [...container.querySelectorAll("button")].filter(
        (b) => !b.disabled && !b.closest("[role='tablist']") && !b.classList.contains("template-name"),
      ).length,
    ).toBe(0);
    await waitFor(() =>
      expect(gets.sort()).toEqual(["/v1/ai/instructions", "/v1/ai/settings", "/v1/ai/templates"]),
    );
  });

  it("orders the page templates, instructions, automatic writing, advanced", async () => {
    signedIn("owner");
    server(true);
    const { container } = writing();
    await screen.findByRole("button", { name: "Meeting" });
    const labels = [...container.querySelectorAll(".settings-stack > section, .settings-stack > details")].map(
      (el) => el.getAttribute("aria-label") ?? el.className,
    );
    expect(labels).toEqual([
      "Templates",
      "Note instructions",
      "Automatic note writing",
      "card pad settings-card model-behaviour",
    ]);
  });

  it("takes every range, step and cap of the Advanced table from the server's limits", async () => {
    signedIn("owner");
    server(true);
    const { container } = writing("/settings/writing?advanced=1");
    const temperature = await screen.findByRole("spinbutton", { name: "Temperature" });
    expect(temperature).toHaveAttribute("min", "0");
    expect(temperature).toHaveAttribute("max", "0.7");
    expect(temperature).toHaveAttribute("step", "0.1");
    const budget = screen.getByRole("spinbutton", { name: "Output budget per call" });
    expect(budget).toHaveAttribute("min", "512");
    expect(budget).toHaveAttribute("max", "8192");
    expect(container.querySelector(".param-table")?.textContent).toContain("2 (model)");
    expect(screen.queryByRole("spinbutton", { name: "Context window" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Second reading" })).toBeNull();
  });
});

describe("the note's status line", () => {
  it("names the instructions and the model settings, with one link", async () => {
    const view = {
      id: "g1", status: "complete", step: null, windows_total: 2, windows_done: 2,
      windows_failed: 0, failed_ranges: [], prompt_version: "p", model_id: "m", error_kind: null,
      created_at: "2026-10-19T10:00:00Z", finished_at: "2026-10-19T10:01:00Z",
      suggested_sections: [], sections_written: 3, template: "interview",
      instructions: { scope: "workspace", version: 1 }, model_settings_version: 2,
    }; // prettier-ignore
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify(view), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );
    const { container } = render(
      <MemoryRouter>
        <ToasterProvider>
          <GenerationStatus noteId="n1" />
        </ToasterProvider>
      </MemoryRouter>,
    );
    await waitFor(() => expect(container.querySelector(".gen-instructions")).not.toBeNull());
    const line = container.querySelector(".gen-instructions")!;
    expect(line.textContent).toBe("Written with workspace instructions v1 · model settings v2");
    const links = line.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "/settings/writing");
  });
});
