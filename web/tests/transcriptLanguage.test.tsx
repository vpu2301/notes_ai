import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AsrJob, TranscriptResult } from "../src/api/types";
import { ToasterProvider } from "../src/components/Toaster";
import { TranscriptView } from "../src/pages/NoteEditorPage";

const asr = vi.hoisted(() => ({
  getResult: vi.fn(),
  getJob: vi.fn(),
}));
vi.mock("../src/api/asr", async (orig) => ({ ...(await orig<typeof import("../src/api/asr")>()), ...asr }));

function job(): AsrJob {
  return {
    id: "job-1",
    tenant_id: "t",
    audio_id: "a",
    requester_sub: "u",
    language: "auto",
    model: "m",
    status: "complete",
    queued_at: "2026-09-25T10:00:00Z",
    error_message: null,
    error_stage: null,
    error_retryable: null,
    diarization_status: null,
  };
}

/** An English recording with one Ukrainian turn in the middle. */
function result(over: Partial<TranscriptResult> = {}): TranscriptResult {
  return {
    job_id: "job-1",
    language: "en",
    segments: [],
    speakers: ["SPEAKER_1", "SPEAKER_2"],
    speaker_names: { SPEAKER_1: "Anna", SPEAKER_2: "Olena" },
    speaker_stats: [],
    result_rev: 1,
    edits: [],
    turns: [
      { speaker: "SPEAKER_1", name: "Anna", start_ms: 0, end_ms: 5000, paragraphs: ["Hello all."], segment_indices: [0] },
      {
        speaker: "SPEAKER_2",
        name: "Olena",
        start_ms: 5000,
        end_ms: 9000,
        paragraphs: ["Привіт усім."],
        segment_indices: [1],
        language: "uk",
      },
      { speaker: "SPEAKER_1", name: "Anna", start_ms: 9000, end_ms: 12000, paragraphs: ["Let's start."], segment_indices: [2] },
    ],
    ...over,
  };
}

async function renderView() {
  render(
    <ToasterProvider>
      <TranscriptView jobId="job-1" />
    </ToasterProvider>,
  );
  await screen.findByText("Hello all.");
  await waitFor(() => expect(asr.getJob).toHaveBeenCalled());
}

function stubClipboard() {
  const writeText = vi.fn(async () => undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return writeText;
}

beforeEach(() => {
  sessionStorage.clear();
  asr.getResult.mockReset().mockResolvedValue(result());
  asr.getJob.mockReset().mockResolvedValue(job());
});
afterEach(() => vi.unstubAllGlobals());

describe("a turn in another language than the recording (Sprint I2)", () => {
  it("wears a small language tag; the others wear none", async () => {
    await renderView();
    const tag = screen.getByText("uk");
    expect(tag).toHaveClass("lang-tag", "turn-lang");
    expect(tag.closest(".turn")).toContainElement(screen.getByText("Привіт усім."));
    expect(document.querySelectorAll(".turn-lang")).toHaveLength(1);
  });

  it("is left out of a copy by default", async () => {
    const writeText = stubClipboard();
    await renderView();
    fireEvent.click(screen.getByRole("button", { name: /copy/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(writeText).toHaveBeenCalledWith("Anna: Hello all.\n\nAnna: Let's start.");
  });

  it("is copied once 'Include other languages' is on", async () => {
    const writeText = stubClipboard();
    await renderView();
    fireEvent.click(screen.getByRole("checkbox", { name: "Include other languages" }));
    fireEvent.click(screen.getByRole("button", { name: /copy/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(writeText).toHaveBeenCalledWith("Anna: Hello all.\n\nOlena: Привіт усім.\n\nAnna: Let's start.");
  });

  it("offers no toggle when every turn is in the recording's language", async () => {
    asr.getResult.mockResolvedValue(
      result({
        turns: [{ speaker: "SPEAKER_1", name: "Anna", start_ms: 0, end_ms: 5000, paragraphs: ["Hello all."], segment_indices: [0] }],
      }),
    );
    await renderView();
    expect(screen.queryByRole("checkbox", { name: "Include other languages" })).toBeNull();
  });
});

describe("prompt echo the worker removed", () => {
  it("is said once, under the transcript header, with where it was", async () => {
    asr.getResult.mockResolvedValue(
      result({
        diagnostics: {
          prompt_echo: [
            { start_ms: 65_000, end_ms: 68_000, words: 4 },
            { start_ms: 2_000, end_ms: 4_000, words: 8 },
          ],
          prompt_echo_segments_dropped: 2,
          other_language_chunks: 1,
        },
      }),
    );
    await renderView();
    const line = screen.getByText("12 words removed as prompt echo at 00:02, 01:05");
    expect(line).toHaveClass("help", "transcript-diagnostic");
    expect(screen.queryByRole("button", { name: /undo/i })).toBeNull();
  });

  it("says nothing when there was none", async () => {
    await renderView();
    expect(screen.queryByText(/prompt echo/)).toBeNull();
  });
});
