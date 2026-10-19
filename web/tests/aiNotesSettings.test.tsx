import "@testing-library/jest-dom/vitest";
import { MemoryRouter } from "react-router-dom";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessToken, setSessionListener } from "../src/api/http";
import { ToasterProvider } from "../src/components/Toaster";
import { AINotesSettingsPage } from "../src/pages/settings/AINotesSettingsPage";

const NOW = "2026-10-18T12:00:00Z";
const V1 = "11111111-0000-0000-0000-000000000001";
const V2 = "11111111-0000-0000-0000-000000000002";
const PROFILE = "22222222-0000-0000-0000-000000000001";
const EXP = "33333333-0000-0000-0000-000000000001";

const version = (id: string, n: number) => ({
  id,
  version_number: n,
  content_hash: `h${n}`,
  created_by: "u",
  created_at: NOW,
  compatible: true,
  incompatible_reason: null,
});

const PROFILES = {
  active: { profile_version_id: V1, revision: 1, activated_by: "u", activated_at: NOW },
  profiles: [{ id: PROFILE, name: "Broadcasts", description: "", created_at: NOW, versions: [version(V1, 1), version(V2, 2)] }],
  can_edit: true,
  contract_version: "2026-10-18.2",
  algorithm_version: "2026-10-18.fidelity",
  stages: ["extraction", "composition", "verification"],
  max_stage_chars: 20000,
  variables: ["output_language"],
};

const MISTRAL = {
  backend: "mistral_eu",
  model_id: "mistral-large-2512",
  processor: "Mistral AI",
  region: "EU",
  acknowledged: true,
  small_model: false,
  context_window: 131072,
  stages: ["extraction", "composition", "verification"],
  supported: { temperature: { min: 0, max: 1 }, max_output_tokens: { min: 256, max: 8192 }, timeout_s: { min: 10, max: 120 } },
  unsupported: { seed: "this backend's adapter sends no seed", reasoning: "this backend's adapter sends no reasoning setting" },
};
const NO_TEMPERATURE = { ...MISTRAL, backend: "plain", model_id: "plain-1", supported: { timeout_s: { min: 10, max: 60 } } };

const config = (over: Record<string, unknown> = {}) => ({
  stages: {},
  models: {},
  params: {},
  output_language: "auto",
  length: "standard",
  ...over,
});

const VERSIONS: Record<string, unknown> = {
  [V1]: { ...version(V1, 1), profile_id: PROFILE, config: config(), effective: {}, language: "en", contract_version: "x", schema_version: "x", algorithm_version: "x" },
  [V2]: {
    ...version(V2, 2),
    profile_id: PROFILE,
    config: config({ stages: { extraction: "List every claim." }, models: { composition: "mistral_eu" } }),
    effective: {},
    language: "en",
    contract_version: "x",
    schema_version: "x",
    algorithm_version: "x",
  },
};

const RUN = (id: string, candidate: number) => ({
  id,
  candidate_index: candidate,
  source_index: 0,
  repetition: 1,
  state: "done",
  metrics: { calls: [{ stage: "extraction", backend: "mistral_eu", model_id: "mistral-large-2512", calls: 4, failed: 0, input_tokens: 10, output_tokens: 5, latency_ms: 9 }], tokens: 15 },
  error_kind: null,
  cost_cents: null,
  latency_ms: 30000,
  artifact_available: true,
  config: {},
});

const EXPERIMENT = {
  id: EXP,
  state: "completed",
  sources: [{ note_id: "n1", transcript_rev: 3, readable: true }],
  candidates: [V1, V2],
  repetitions: 1,
  length: "standard",
  output_language: "de",
  budget_cap_cents: 300,
  reserved_cents: 0,
  spent_cents: 0,
  cost_known: false,
  token_cap: 1000,
  tokens_used: 0,
  error_kind: null,
  runs: [RUN("r-a", 0), RUN("r-b", 1)],
  stale: false,
};

const ARTIFACT = {
  language: "de",
  sections: [
    {
      section_key: "gen:x",
      title: "Wahlversprechen",
      lines: [{ kind: "bullet", text: "- Calder verspricht 5.000 Dollar, falls beide Kammern gewonnen werden.", fact_ids: ["f1"] }],
    },
  ],
  facts: [
    {
      item_key: "f1",
      kind: "key_point",
      text: "Calder verspricht 5.000 Dollar.",
      quote: "I will issue a dividend to every adult citizen",
      source_language: "en",
      start_ms: 38000,
      end_ms: 58000,
      speaker_label: "SPEAKER_2",
      attributed_to: null,
      flags: [],
    },
  ],
};

const RUNTIME_ON = {
  build_sha: "abc1234",
  multilingual_evidence: true,
  fidelity: true,
  prompt_version: "2026-10-18.3",
  algorithm_version: "2026-10-18.final-check",
  profile_instructions_apply: true,
};
const RUNTIME_OFF = {
  ...RUNTIME_ON,
  multilingual_evidence: false,
  fidelity: false,
  prompt_version: "2026-10-01.3",
  profile_instructions_apply: false,
};

type Reply = { status?: number; body: unknown };
type Handler = (method: string, path: string, body: Record<string, unknown> | null) => Reply | undefined;

function server(over: Handler = () => undefined) {
  const calls: { method: string; path: string; body: Record<string, unknown> | null }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: unknown, init?: RequestInit) => {
      const method = (init?.method ?? "GET").toUpperCase();
      const path = new URL(String(url), "http://x").pathname;
      const body = init?.body && typeof init.body === "string" ? JSON.parse(init.body) : null;
      calls.push({ method, path, body });
      const reply =
        over(method, path, body) ??
        ((): Reply => {
          if (path.endsWith("/prompt-profiles") && method === "GET") return { body: PROFILES };
          if (path.endsWith("/ai/runtime")) return { body: RUNTIME_ON };
          if (path.endsWith("/model-capabilities")) return { body: { models: [MISTRAL, NO_TEMPERATURE], stage_operations: {}, writer: { backend: "mistral_eu", model_id: "mistral-large-2512", primary: "mistral_eu", reason: null } } };
          if (path.endsWith("/experiments") && method === "GET") return { body: [{ id: EXP, state: "completed", candidates: [V1, V2], sources: 1, repetitions: 1, cost_known: false, spent_cents: 0, created_at: NOW }] };
          if (path.endsWith("/history")) return { body: [{ profile_version_id: V1, previous_version_id: null, revision: 1, actor: "u", evaluation_ref: null, created_at: NOW }] };
          const v = path.match(/versions\/([0-9a-f-]+)$/);
          if (v && method === "GET") return { body: VERSIONS[v[1]!] };
          if (path.endsWith("/preview")) return { body: { problems: [], effective: { extraction: "EFFECTIVE TEXT", composition: "c", verification: "v" }, language: "en", bundled: { extraction: "BUNDLED EXTRACTION", composition: "BUNDLED COMPOSITION", verification: "BUNDLED VERIFICATION" } } };
          if (path.endsWith(`/experiments/${EXP}`)) return { body: EXPERIMENT };
          if (path.includes("/artifact")) return { body: ARTIFACT };
          return { status: 404, body: { status: 404, detail: "not found" } };
        })();
      const status = reply.status ?? 200;
      return new Response(JSON.stringify(reply.body), {
        status,
        headers: { "Content-Type": status >= 400 ? "application/problem+json" : "application/json" },
      });
    }),
  );
  return calls;
}

const page = (view?: string) =>
  render(
    <MemoryRouter initialEntries={[view ? `/settings/ai-notes?view=${view}` : "/settings/ai-notes"]}>
      <ToasterProvider>
        <AINotesSettingsPage />
      </ToasterProvider>
    </MemoryRouter>,
  );

/** Node's own (file-less) `localStorage` shadows jsdom's here; give the page a working one. */
function memoryStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() {
      return m.size;
    },
    clear: () => m.clear(),
    getItem: (k) => m.get(k) ?? null,
    key: (i) => [...m.keys()][i] ?? null,
    removeItem: (k) => void m.delete(k),
    setItem: (k, v) => void m.set(k, String(v)),
  };
}

beforeEach(() => {
  setSessionListener({});
  setAccessToken("x");
  vi.stubGlobal("localStorage", memoryStorage());
});
afterEach(() => vi.unstubAllGlobals());

async function openEditor(versionRow = "v1") {
  const row = await screen.findByRole("row", { name: new RegExp(`^${versionRow}\\b`) });
  await userEvent.click(within(row).getByRole("button", { name: "Edit" }));
  return screen.findByRole("textbox", { name: /extract facts instructions/i });
}

describe("Settings › AI notes", () => {
  it("shows what writes notes now, configured and actually used", async () => {
    server();
    page();
    expect(await screen.findByTestId("ai-active")).toHaveTextContent("Broadcasts · v1");
    expect(screen.getAllByText(/actually used/).length).toBeGreaterThan(0);
    expect(await screen.findByText(/every spoken language is used as evidence/)).toBeInTheDocument();
    expect(screen.getByTestId("ai-runtime")).toHaveTextContent(/every written line is checked/i);
    expect(screen.getByTestId("ai-runtime")).toHaveTextContent("build abc1234");
    expect(screen.queryByTestId("ai-instructions-unused")).toBeNull();
  });

  it("never claims the new engine where its flags are off", async () => {
    server((_m, p) => (p.endsWith("/ai/runtime") ? { body: RUNTIME_OFF } : undefined));
    page("test");
    expect(await screen.findByTestId("ai-runtime")).toHaveTextContent(/previous engine/i);
    expect(screen.queryByText(/every spoken language is used as evidence/)).toBeNull();
    expect(screen.getByTestId("ai-instructions-unused")).toBeInTheDocument();
    // A test run takes the new path regardless: the page says so before it is started.
    expect(screen.getByTestId("ai-test-path")).toHaveTextContent(/can differ from a regenerated note/);
  });

  it("says nothing about the engine when the server does not report it", async () => {
    server((_m, p) => (p.endsWith("/ai/runtime") ? { status: 404, body: { status: 404 } } : undefined));
    page();
    expect(await screen.findByTestId("ai-active")).toBeInTheDocument();
    expect(screen.queryByTestId("ai-runtime")).toBeNull();
    expect(screen.queryByText(/every spoken language is used as evidence/)).toBeNull();
  });

  it("is read-only for a member", async () => {
    server((m, p) => (p.endsWith("/prompt-profiles") && m === "GET" ? { body: { ...PROFILES, can_edit: false } } : undefined));
    page();
    expect(await screen.findByText(/only a workspace admin can change/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("button", { name: /activate/i })).toBeNull();
  });

  it("saves new extraction wording as version 3 and leaves version 1 active", async () => {
    const calls = server((m, p) =>
      m === "POST" && p.endsWith(`/prompt-profiles/${PROFILE}/versions`) ? { status: 201, body: version("v3", 3) } : undefined,
    );
    page();
    const box = await openEditor();
    expect(box).toHaveValue("BUNDLED EXTRACTION");
    await userEvent.clear(box);
    await userEvent.type(box, "List what was said, in {{{{output_language}}.");
    await userEvent.click(screen.getByRole("button", { name: /save as new version/i }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path.endsWith("/versions"))?.body).toMatchObject({
        config: { stages: { extraction: "List what was said, in {{output_language}}." } },
      }),
    );
    expect(await screen.findByText(/saved as version 3\. it is not active/i)).toBeInTheDocument();
    // Saving never activates: nothing was posted to activate.
    expect(calls.some((c) => c.path.endsWith("/activate"))).toBe(false);
  });

  it("shows an unknown placeholder beside its stage and does not save", async () => {
    server((m, p) =>
      m === "POST" && p.endsWith("/versions")
        ? {
            status: 422,
            body: {
              status: 422,
              code: "invalid_profile",
              detail: "the configuration cannot be saved",
              problems: [{ field: "stages.extraction", code: "unknown_variable", detail: "{{secret}} is not one of ['output_language']" }],
            },
          }
        : undefined,
    );
    page();
    const box = await openEditor();
    await userEvent.type(box, " {{{{secret}}");
    await userEvent.click(screen.getByRole("button", { name: /save as new version/i }));
    expect(await screen.findByText(/\{\{secret\}\} is not one of/)).toBeInTheDocument();
    expect(box).toHaveAttribute("aria-invalid", "true");
  });

  it("keeps an unsaved draft across a reload", async () => {
    server();
    const first = page();
    const box = await openEditor();
    await userEvent.type(box, " Keep every condition.");
    first.unmount();
    page();
    const again = await openEditor();
    expect(again).toHaveValue("BUNDLED EXTRACTION Keep every condition.");
  });

  it("offers only the settings a model supports, and says why not", async () => {
    server();
    page();
    await openEditor();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /model for extract facts/i }), "plain");
    expect(screen.getByRole("spinbutton", { name: "Temperature" })).toBeDisabled();
    expect(screen.getByRole("spinbutton", { name: "Timeout (s)" })).toBeEnabled();
    expect(screen.getByText(/not available for this model: seed/i)).toBeInTheDocument();
  });

  it("will not activate an untested version without choosing its evaluation", async () => {
    server();
    page();
    const row = await screen.findByRole("row", { name: /^v2\b/ });
    await userEvent.click(within(row).getByRole("button", { name: "Activate" }));
    expect(await screen.findByText(/only notes written from now on use it/i)).toBeInTheDocument();
    expect(screen.getByText(/Compared with what is active now: Instructions: Extract facts · Model: Write notes/)).toBeInTheDocument();
    const dialogConfirm = screen.getAllByRole("button", { name: "Activate" }).at(-1)!;
    expect(dialogConfirm).toBeDisabled();
  });

  it("explains a stale activation instead of overwriting", async () => {
    server((m, p) =>
      m === "POST" && p.endsWith("/activate")
        ? { status: 409, body: { status: 409, code: "active_revision_conflict", detail: "x", current_revision: 2 } }
        : undefined,
    );
    page();
    const row = await screen.findByRole("row", { name: /^v2\b/ });
    await userEvent.click(within(row).getByRole("button", { name: "Activate" }));
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: /evaluation this rests on/i }), EXP);
    await userEvent.click(screen.getAllByRole("button", { name: "Activate" }).at(-1)!);
    expect(await screen.findByText(/another admin changed which version is active/i)).toBeInTheDocument();
  });

  it("says the cost is unknown when a model has no price, and flags several changed variables", async () => {
    server((_m, p) => {
      if (p.endsWith("/notes/search")) return { body: { hits: [{ note_id: "n1", code: "N-1", title: "Midterms", status: "draft" }], next_cursor: null, total_estimated: 1 } };
      if (p.endsWith("/n1/generation")) return { body: { transcript_rev: 3, source_languages: ["de", "en"] } };
      if (p.endsWith("/experiments/estimate")) return { body: { runs: 6, estimate_cents: null, token_cap: 720000, cost_known: false, sources: [{ note_id: "n1", transcript_rev: 3, languages: ["de", "en"] }] } };
      return undefined;
    });
    page("test");
    await userEvent.type(await screen.findByRole("textbox", { name: /find a note/i }), "Midterms");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));
    expect(await screen.findByRole("row", { name: /Midterms/ })).toHaveTextContent("DE, EN");
    expect(await screen.findByText(/multiple variables changed/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Estimate" }));
    expect(await screen.findByTestId("ai-jobs")).toHaveTextContent(/Estimated cost: unknown/);
  });

  it("an emptied stage is saved as the bundled instructions, never as an empty override", async () => {
    const calls = server((m, p) =>
      m === "POST" && p.endsWith(`/prompt-profiles/${PROFILE}/versions`) ? { status: 201, body: version("v3", 3) } : undefined,
    );
    page();
    const box = await openEditor();
    await userEvent.clear(box);
    expect(screen.getByText(/this stage is empty, so it will use the bundled instructions/i)).toBeInTheDocument();
    await userEvent.type(box, " ");
    await userEvent.click(screen.getByRole("button", { name: /save as new version/i }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path.endsWith("/versions"))?.body).toMatchObject({
        config: { stages: { extraction: null } },
      }),
    );
  });

  it("previews every call exactly, with where its text comes from, and the flags it runs with", async () => {
    server((_m, p) =>
      p.endsWith("/preview")
        ? {
            body: {
              problems: [], effective: { extraction: "E" }, language: "en",
              bundled: { extraction: "BUNDLED EXTRACTION", composition: "C", verification: "V" },
              calls: [
                { call: "extraction", stage: "extraction", source: "not_applied", sha: "abcdef1234567890", system: "EXTRACT SYSTEM" },
                { call: "context", stage: "context", source: "code", sha: "1234567890abcdef", system: "CONTEXT SYSTEM" },
              ],
              flags: { mode: "production", multilingual_evidence: false, fidelity: false, final_check: false, profile_instructions_apply: false },
              required_variables: { composition: ["output_language"] },
            },
          }
        : undefined,
    );
    page();
    await openEditor();
    expect(await screen.findByTestId("ai-preview-flags")).toHaveTextContent(/previous engine: this version's instructions are not sent/);
    expect(screen.getByLabelText("Extract facts instructions", { selector: "pre" })).toHaveTextContent("EXTRACT SYSTEM");
    expect(screen.getByText(/edited, but not sent here · sha abcdef123456/)).toBeInTheDocument();
    expect(screen.getByText(/code-owned, read-only · sha 1234567890ab/)).toBeInTheDocument();
  });

  it("runs the critical cases for the candidate and warns that one run is not enough", async () => {
    const calls = server((m, p) =>
      p.endsWith("/experiments") && m === "POST"
        ? { status: 202, body: { ...EXPERIMENT, state: "queued", sources: [{ case_id: "ml01_de_host_en_promise", transcript_rev: 1, readable: true }], runs: [] } }
        : undefined,
    );
    page("test");
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: /repetitions/i }), "1");
    expect(screen.getByTestId("ai-single-run")).toHaveTextContent(/not enough to decide on/);
    await userEvent.click(screen.getByRole("button", { name: /run critical cases for the candidate/i }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST" && c.path.endsWith("/experiments"))?.body).toMatchObject({
        suite: "critical",
        sources: [],
      }),
    );
  });

  it("explains that cancelling lets an in-flight run finish", async () => {
    server((m, p) => {
      if (p.endsWith("/notes/search")) return { body: { hits: [{ note_id: "n1", code: "N-1", title: "Midterms", status: "draft" }], next_cursor: null, total_estimated: 1 } };
      if (p.endsWith("/n1/generation")) return { body: { transcript_rev: 3, source_languages: ["de"] } };
      if (p.endsWith("/experiments/estimate")) return { body: { runs: 6, estimate_cents: 12, token_cap: 1000, cost_known: true, sources: [] } };
      if (p.endsWith("/experiments") && m === "POST") return { status: 202, body: { ...EXPERIMENT, state: "running", runs: [{ ...RUN("r-a", 0), state: "running" }] } };
      return undefined;
    });
    page("test");
    await userEvent.type(await screen.findByRole("textbox", { name: /find a note/i }), "Midterms");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));
    await userEvent.click(await screen.findByRole("button", { name: "Add" }));
    await userEvent.click(screen.getByRole("button", { name: "Estimate" }));
    await userEvent.click(await screen.findByRole("button", { name: "Start test" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel test" }));
    expect(await screen.findByText(/a run already in progress may finish, and its cost is still counted/i)).toBeInTheDocument();
  });

  it("reviews blind, then reveals; every line opens its original-language evidence", async () => {
    const calls = server((m, p) =>
      m === "POST" && p.endsWith("/reviews") ? { status: 201, body: { id: "rv" } } : undefined,
    );
    page("compare");
    const outputs = await screen.findAllByRole("heading", { name: /^Output [12]$/ });
    expect(outputs).toHaveLength(2); // no version names while blind
    expect(screen.getAllByText("hidden").length).toBeGreaterThan(0);
    await userEvent.click((await screen.findAllByRole("button", { name: /Calder verspricht 5\.000 Dollar/ }))[0]!);
    expect(await screen.findByText("I will issue a dividend to every adult citizen")).toBeInTheDocument();
    expect(screen.getByText(/Original · EN · 00:38–00:58/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "2 is better" }));
    await userEvent.click(within(screen.getByRole("group", { name: /factual errors in output 1/i })).getByRole("checkbox", { name: "Missing condition" }));
    await userEvent.click(screen.getByRole("button", { name: "Submit review" }));
    await waitFor(() =>
      expect(calls.find((c) => c.path.endsWith("/reviews"))?.body).toMatchObject({
        blind: true,
        revealed: false,
        preference: "b",
        findings: [{ run: "a", label: "missing_condition" }],
      }),
    );
    // After submitting, who wrote what is shown.
    expect(await screen.findByRole("heading", { name: /Output 1 — Broadcasts · v[12]/ })).toBeInTheDocument();
  });
});
