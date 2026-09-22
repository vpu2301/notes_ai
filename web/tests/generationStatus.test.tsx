import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setAccessToken, setSessionListener } from "../src/api/http";
import { GenerationStatus } from "../src/components/GenerationStatus";
import { ToasterProvider } from "../src/components/Toaster";

const BASE = {
  id: "g1",
  status: "running",
  step: "extract",
  windows_total: 8,
  windows_done: 3,
  windows_failed: 0,
  failed_ranges: [],
  prompt_version: "2026-10-1",
  model_id: "gemma-3",
  error_kind: null,
  created_at: "2026-09-20T10:00:00Z",
  finished_at: null,
  suggested_sections: [],
};

function server(view: Record<string, unknown> | number) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      typeof view === "number"
        ? new Response("{}", { status: view, headers: { "Content-Type": "application/json" } })
        : new Response(JSON.stringify(view), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
    ),
  );
}

const strip = (props: Record<string, unknown> = {}) =>
  render(
    <ToasterProvider>
      <GenerationStatus noteId="n1" {...props} />
    </ToasterProvider>,
  );

beforeEach(() => {
  setSessionListener({});
  setAccessToken("x");
});
afterEach(() => vi.unstubAllGlobals());

describe("generate summary", () => {
  it("offers the button when the note was never written up and the reader may edit it", async () => {
    server(404);
    strip({ canGenerate: true });
    expect(await screen.findByRole("button", { name: "Generate Summary" })).toBeInTheDocument();
    expect(screen.getByText(/structured summary from this conversation/i)).toBeInTheDocument();
  });

  it("shows nothing for a note nobody may write up here", async () => {
    server(404);
    strip({ canGenerate: false });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByRole("button", { name: "Generate Summary" })).not.toBeInTheDocument();
    expect(screen.queryByText(/structured summary/i)).not.toBeInTheDocument();
  });

  it("starts the run and follows it", async () => {
    const calls: string[] = [];
    let generated = false;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? "GET"} ${url}`);
        if (init?.method === "POST") {
          generated = true;
          return new Response(JSON.stringify({ id: "g1", status: "queued" }), {
            status: 202,
            headers: { "Content-Type": "application/json" },
          });
        }
        return generated
          ? new Response(JSON.stringify({ ...BASE, status: "queued", windows_total: null, windows_done: null }), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            })
          : new Response("{}", { status: 404, headers: { "Content-Type": "application/json" } });
      }),
    );
    strip({ canGenerate: true });
    (await screen.findByRole("button", { name: "Generate Summary" })).click();
    expect(await screen.findByText(/Writing this note/i)).toBeInTheDocument();
    expect(calls.some((c) => c.startsWith("POST ") && c.endsWith("/v1/notes/n1/generation"))).toBe(true);
    expect(screen.queryByRole("button", { name: "Generate Summary" })).not.toBeInTheDocument();
  });
});

describe("generation status", () => {
  it("says how much of the recording has been read", async () => {
    server(BASE);
    strip();
    expect(await screen.findByText(/3 of 8 minutes read/i)).toBeInTheDocument();
  });

  it("explains a spent budget instead of offering a retry that would fail", async () => {
    server({ ...BASE, status: "failed", error_kind: "budget_exceeded", finished_at: "x" });
    strip({ canRegenerate: true });
    expect(await screen.findByText(/used its AI budget for the month/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /try again/i })).toBeNull();
  });

  it("offers a retry for a failure that could go the other way", async () => {
    server({ ...BASE, status: "failed", error_kind: "model_unavailable", finished_at: "x" });
    strip({ canRegenerate: true });
    expect(await screen.findByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("names the minutes it could not read rather than apologising in general", async () => {
    server({ ...BASE, status: "partial", failed_ranges: [[120000, 180000]], finished_at: "x" });
    strip({ canRegenerate: true });
    expect(await screen.findByText(/around minute 2/i)).toBeInTheDocument();
  });

  it("says why when the workspace turned generation off, without polling", async () => {
    server(404);
    strip({ blocked: "generation_disabled" });
    expect(
      await screen.findByText(/automatic note writing is off for this workspace/i),
    ).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("stays out of the way for a note nobody generated", async () => {
    server(404);
    const { container } = strip();
    await new Promise((r) => setTimeout(r, 10));
    expect(container.querySelector(".gen-status")).toBeNull();
  });
});
