import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessToken, setSessionListener } from "../src/api/http";
import { ToasterProvider } from "../src/components/Toaster";
import { TelemetryDashboardPage } from "../src/pages/admin/TelemetryDashboardPage";
import { TelemetryRunPage } from "../src/pages/admin/TelemetryRunPage";
import { DEV_ADMIN_EMAIL } from "../src/pages/admin/telemetryShared";

const auth = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));
vi.mock("../src/auth/AuthContext", () => ({
  useAuth: () => auth.value,
  useAuthOptional: () => auth.value,
}));
const saved = vi.hoisted(() => ({ files: [] as string[] }));
vi.mock("../src/lib/exportNote", async (orig) => ({
  ...(await orig<typeof import("../src/lib/exportNote")>()),
  saveBlob: (_blob: Blob, name: string) => void saved.files.push(name),
}));

const RUN = {
  processing_run_id: "22222222-2222-2222-2222-222222222222",
  tenant_id: "t",
  recording_id: "11111111-1111-1111-1111-111111111111",
  kind: "initial",
  reprocess_scope: null,
  status: "succeeded",
  error_category: null,
  submitted_at: "2026-10-22T11:44:53Z",
  finished_at: "2026-10-22T11:48:26Z",
  audio_duration_seconds: 90,
  processing_wall_seconds: 212.82,
  rtf: 2.365,
  user_wait_seconds: null,
  telemetry_overhead_seconds: 0.3,
  asr_backend: "inproc_cpu_asr",
  llm_model: "mistral-large-2512",
};
const OVERVIEW = {
  from: "2026-10-15T00:00:00Z", to: "2026-10-22T00:00:00Z", capped: false, runs: 1,
  status_counts: { succeeded: 1, partial: 0, failed: 0, cancelled: 0, running: 0, queued: 0 },
  rtf: { p50: 2.365, p95: 2.365, n: 1 }, user_wait_seconds: { p50: null, p95: null, n: 0 },
  telemetry_overhead_seconds: { median: 0.3, n: 1 },
  stage_share: { asr_primary: 0.56, language_detection: 0.324 }, runs_with_wall: 1,
  backends: [{ kind: "asr", name: "inproc_cpu_asr", device: "cpu", observation: "observed", runs: 1 },
             { kind: "diarization", name: "legacy-ecapa-ahc", device: "cpu", observation: "configured", runs: 1 }],
}; // prettier-ignore
const REPORT =
  "# Diagnostics — recording x\n\n## 1. Run identity\n\n| Field | Value |\n|---|---|\n| status | succeeded |\n";

// jsdom's Blob has no `.text()` (every browser has); read it through FileReader here.
if (!("text" in Blob.prototype)) {
  Object.defineProperty(Blob.prototype, "text", {
    value(this: Blob) {
      return new Promise<string>((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.readAsText(this);
      });
    },
  });
}

let calls: string[] = [];

function server() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string | URL) => {
      const path = new URL(String(url)).pathname;
      calls.push(path);
      const json = (body: unknown) =>
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      if (path === "/v1/admin/telemetry/overview") return json(OVERVIEW);
      if (path === "/v1/telemetry/runs") return json({ runs: [RUN], next_cursor: null });
      if (path.endsWith("/report.md"))
        return new Response(REPORT, { status: 200, headers: { "Content-Type": "text/markdown" } });
      if (path === `/v1/telemetry/runs/${RUN.processing_run_id}`)
        return json({ processing_run: RUN, spans: [{ span_id: "s1", parent_span_id: null, stage: "other", name: "worker_job", attempt: 1, status: "ok", start_wall_utc: RUN.submitted_at, end_wall_utc: RUN.finished_at, attributes: { job_status: "complete" } }], missing_measurements: [] }); // prettier-ignore
      return new Response("{}", { status: 404 });
    }),
  );
}

function signedIn(roles: string[], email = "owner@example.com") {
  auth.value = {
    status: "authenticated",
    activeRole: "owner",
    memberships: [],
    me: { claims: { sub: "u", tid: "t", roles }, db_user: null },
    identity: {
      id: "u",
      email,
      display_name: "x",
      mfa_enabled: false,
      has_password: false,
      status: "active",
    },
    logout: vi.fn(),
  };
}

const at = (url: string) =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <ToasterProvider>
        <Routes>
          <Route path="/admin/dashboard" element={<TelemetryDashboardPage />} />
          <Route path="/admin/dashboard/runs/:processingRunId" element={<TelemetryRunPage />} />
        </Routes>
      </ToasterProvider>
    </MemoryRouter>,
  );

beforeEach(() => {
  calls = [];
  saved.files = [];
  setSessionListener({});
  setAccessToken("x");
  server();
});
afterEach(() => vi.unstubAllGlobals());

describe("telemetry dashboard", () => {
  it("is not available without the platform admin role, and asks the API nothing", async () => {
    signedIn(["tenant_admin", "member"]);
    at("/admin/dashboard");
    expect(await screen.findByText(/Not available/)).toBeInTheDocument();
    expect(calls).toEqual([]);
  });

  it("shows KPIs, stage shares, backends with their device source, and recent runs", async () => {
    signedIn(["tenant_admin", "member", "platform_admin"]);
    at("/admin/dashboard");
    expect(await screen.findByText("2.365 / 2.365")).toBeInTheDocument();
    expect(screen.getByText("56.0 %")).toBeInTheDocument();
    expect(screen.getByText("configured")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "22222222" })).toHaveAttribute(
      "href",
      `/admin/dashboard/runs/${RUN.processing_run_id}`,
    );
    expect(screen.queryByText("Development admin account in use.")).toBeNull();
  });

  it("downloads a run's report from the row", async () => {
    signedIn(["platform_admin"]);
    at("/admin/dashboard");
    fireEvent.click(await screen.findByRole("button", { name: /Export diagnostics/ }));
    await waitFor(() =>
      expect(saved.files).toEqual([`diagnostics-${RUN.recording_id}-${RUN.processing_run_id}.md`]),
    );
    expect(calls).toContain(`/v1/telemetry/runs/${RUN.processing_run_id}/report.md`);
  });

  it("says so when the dev bootstrap account is signed in", async () => {
    signedIn(["platform_admin"], DEV_ADMIN_EMAIL);
    at("/admin/dashboard");
    expect(await screen.findByText("Development admin account in use.")).toBeInTheDocument();
  });

  it("renders the run's Markdown report and its span tree", async () => {
    signedIn(["platform_admin"]);
    at(`/admin/dashboard/runs/${RUN.processing_run_id}`);
    expect(await screen.findByText(/Run identity/)).toBeInTheDocument();
    expect(screen.getByText(/Raw span tree \(1 spans\)/)).toBeInTheDocument();
  });

  it("never calls a transcript, note or audio endpoint", async () => {
    signedIn(["platform_admin"]);
    at("/admin/dashboard");
    await screen.findByRole("link", { name: "22222222" });
    at(`/admin/dashboard/runs/${RUN.processing_run_id}`);
    await screen.findAllByText(/Run identity/);
    expect(calls.length).toBeGreaterThan(0);
    for (const path of calls) {
      expect(path).toMatch(/^\/v1\/(telemetry|admin\/telemetry)\//);
    }
  });
});
