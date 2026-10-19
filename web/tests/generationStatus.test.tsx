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
  it("says so when a finished run wrote nothing, and offers another go", async () => {
    server({ ...BASE, status: "complete", finished_at: "x", sections_written: 0 });
    strip({ canRegenerate: true });
    expect(await screen.findByText(/Nothing could be written/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("is silent about a finished run that wrote the note", async () => {
    server({ ...BASE, status: "complete", finished_at: "x", sections_written: 4 });
    strip({ canRegenerate: true });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText(/Nothing could be written/i)).not.toBeInTheDocument();
  });

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

  it("calls an unverified note incomplete without blaming the recording", async () => {
    server({
      ...BASE,
      status: "partial",
      failed_ranges: [],
      incomplete_reasons: ["claims_unverified"],
      finished_at: "x",
    });
    strip({ canRegenerate: true });
    expect(await screen.findByText(/could not be fully verified/i)).toBeInTheDocument();
    expect(screen.queryByText(/could not be read/i)).toBeNull();
  });

  it("says which code, versions, flags and models produced the run, collapsed", async () => {
    server({
      ...BASE,
      status: "partial",
      incomplete_reasons: ["final_unverified"],
      finished_at: "x",
      provenance: {
        run_kind: "generation",
        build_sha: "def5678",
        pinned_build_sha: "abc1234",
        prompt_version: "2026-10-18.3",
        profile_version_id: null,
        flags_source: "snapshot",
        multilingual_evidence: true,
        fidelity: false,
        final_check: false,
        flags_differ: ["fidelity"],
        output_language: "de",
        output_language_source: "dominant",
        transcript_rev: 3,
        stages: [{ stage: "verification", backend: "mistral_eu", model_id: "mistral-large-2512", calls: 3, failed: 1 }],
        fallbacks: [{ kind: "summarize", backend: "mistral_eu_small", primary: "mistral_eu", reason: "probe_failed" }],
      },
    });
    strip({ canRegenerate: true });
    const details = await screen.findByTestId("run-details");
    expect(details).not.toHaveAttribute("open");
    expect(details).toHaveTextContent("def5678 (queued by abc1234)");
    expect(details).toHaveTextContent(/meaning checks off · final check off — pinned when the run was queued/);
    expect(details).toHaveTextContent(/set differently for fidelity; this run used what was pinned/);
    expect(details).toHaveTextContent("de (dominant) · transcript revision 3");
    expect(details).toHaveTextContent("verification: mistral-large-2512 (3 calls, 1 failed)");
    expect(details).toHaveTextContent("mistral_eu_small instead of mistral_eu (probe failed)");
    // The final check's reason reads like any unverified point: neutral, not "unreadable".
    expect(screen.getByText(/could not be fully verified/i)).toBeInTheDocument();
  });

  it("shows no run details for a run from an older server", async () => {
    server({ ...BASE, status: "complete", finished_at: "x", sections_written: 4 });
    strip();
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByTestId("run-details")).toBeNull();
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

// ── exclusions are a line, not a paragraph ──

describe("not included", () => {
  const DONE = {
    ...BASE,
    status: "complete",
    step: null,
    windows_done: 8,
    finished_at: "2026-09-22T10:05:00Z",
    sections_written: 3,
    language: "de",
  };

  it("names each left-out range in the note's language and opens the transcript there", async () => {
    server({
      ...DONE,
      excluded_ranges: [
        { start_ms: 250_000, end_ms: 254_000, reason: "other_language" },
        { start_ms: 45_000, end_ms: 52_000, reason: "background" },
      ],
    });
    const seeks: number[] = [];
    strip({ onSeek: (ms: number) => seeks.push(ms) });
    const first = await screen.findByRole("button", { name: "00:45–00:52 (Hintergrundgespräch)" });
    expect(
      screen.getByRole("button", { name: "04:10–04:14 (eine Passage in einer anderen Sprache)" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Not included:/)).toBeInTheDocument();
    first.click();
    expect(seeks).toEqual([45_000]);
  });

  it("shows four ranges and counts the rest", async () => {
    server({
      ...DONE,
      language: "en",
      excluded_ranges: [0, 1, 2, 3, 4, 5].map((n) => ({
        start_ms: n * 60_000,
        end_ms: n * 60_000 + 3_000,
        reason: "artifact",
      })),
    });
    strip({ onSeek: () => {} });
    expect(await screen.findByText(/\+2 more/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /a transcription artifact/ })).toHaveLength(4);
  });

  it("says nothing when nothing was left out", async () => {
    server({ ...DONE, excluded_ranges: [] });
    strip({ onSeek: () => {} });
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText(/Not included/)).not.toBeInTheDocument();
  });

  it("hands the run to the page", async () => {
    server({ ...DONE, recording_type: "podcast_broadcast" });
    const seen: unknown[] = [];
    strip({ onView: (v: unknown) => seen.push(v) });
    await new Promise((r) => setTimeout(r, 20));
    expect(seen).toEqual([expect.objectContaining({ recording_type: "podcast_broadcast" })]);
  });
});
