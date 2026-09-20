import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/http";
import type { AsrJob, TranscriptResult } from "../src/api/types";
import { ToasterProvider } from "../src/components/Toaster";
import { pickableNames } from "../src/lib/speakers";
import { TranscriptView } from "../src/pages/NoteEditorPage";

const asr = vi.hoisted(() => ({
  getResult: vi.fn(),
  getJob: vi.fn(),
  reassignTurns: vi.fn(),
  setSpeakerNames: vi.fn(),
  undoSpeakerEdit: vi.fn(),
  mergeSpeakers: vi.fn(),
  rediarize: vi.fn(),
  undoRediarize: vi.fn(),
  resetSpeakerEdits: vi.fn(),
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
    queued_at: "2026-09-19T10:00:00Z",
    error_message: null,
    error_stage: null,
    error_retryable: null,
    diarization_status: null,
  };
}

/** Anna, Speaker 2 (over-talked), Anna again, and an unattributed turn. */
function result(over: Partial<TranscriptResult> = {}): TranscriptResult {
  return {
    job_id: "job-1",
    language: "en",
    segments: [],
    speakers: ["SPEAKER_1", "SPEAKER_2"],
    speaker_names: { SPEAKER_1: "Anna", SPEAKER_2: "Speaker 2" },
    speaker_stats: [
      { label: "SPEAKER_1", speech_ms: 300_000, share: 0.6, turns: 2 },
      { label: "SPEAKER_2", speech_ms: 200_000, share: 0.4, turns: 1 },
    ],
    result_rev: 3,
    edits: [],
    name_candidates: ["Anna", "Tom Berg", "Olena Shevchenko"],
    turns: [
      { speaker: "SPEAKER_1", name: "Anna", start_ms: 0, end_ms: 5000, paragraphs: ["Hello all."], segment_indices: [40, 41] },
      {
        speaker: "SPEAKER_2",
        name: "Speaker 2",
        start_ms: 5000,
        end_ms: 9000,
        paragraphs: ["Hi Anna."],
        segment_indices: [42],
        uncertain: true,
      },
      { speaker: "SPEAKER_1", name: "Anna", start_ms: 9000, end_ms: 12000, paragraphs: ["Let's start."], segment_indices: [45, 46] },
      { speaker: null, name: null, start_ms: 12000, end_ms: 13000, paragraphs: ["(noise)"], segment_indices: [47] },
    ],
    ...over,
  };
}

function reassigned(over: Record<string, unknown> = {}) {
  return {
    job_id: "job-1",
    edit_id: "edit-9",
    speakers: ["SPEAKER_1", "SPEAKER_2"],
    speaker_names: { SPEAKER_1: "Anna", SPEAKER_2: "Speaker 2" },
    speaker_stats: [],
    created_label: null,
    ...over,
  };
}

async function renderView(props: Partial<Parameters<typeof TranscriptView>[0]> = {}) {
  render(
    <ToasterProvider>
      <TranscriptView jobId="job-1" {...props} />
    </ToasterProvider>,
  );
  await screen.findByText("Hello all.");
  // The roster's first job poll settles.
  await waitFor(() => expect(asr.getJob).toHaveBeenCalled());
}

/** The turn (role=group) that holds some text. */
function turnOf(text: string): HTMLElement {
  return screen.getByText(text).closest(".turn") as HTMLElement;
}

function openAvatar(text: string) {
  fireEvent.click(within(turnOf(text)).getByRole("button", { name: /move this turn/ }));
}

beforeEach(() => {
  sessionStorage.clear();
  asr.getResult.mockReset().mockResolvedValue(result());
  asr.getJob.mockReset().mockResolvedValue(job());
  asr.reassignTurns.mockReset().mockResolvedValue(reassigned());
  asr.setSpeakerNames.mockReset();
  asr.undoSpeakerEdit.mockReset().mockResolvedValue(undefined);
});
afterEach(() => vi.unstubAllGlobals());

describe("moving a turn from its avatar", () => {
  it("offers the other speakers, New speaker and Unknown", async () => {
    await renderView();
    openAvatar("Hello all.");
    const menu = screen.getByRole("menu");
    expect(within(menu).queryByRole("menuitem", { name: "Anna" })).toBeNull();
    expect(within(menu).getByRole("menuitem", { name: "Speaker 2" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "New speaker" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "Unknown" })).toBeInTheDocument();
  });

  it("sends an existing speaker with the turn's own indices and the result revision", async () => {
    await renderView();
    openAvatar("Hello all.");
    fireEvent.click(screen.getByRole("menuitem", { name: "Speaker 2" }));
    await waitFor(() => expect(asr.reassignTurns).toHaveBeenCalledTimes(1));
    expect(asr.reassignTurns).toHaveBeenCalledWith("job-1", { resultRev: 3, segmentIndices: [40, 41], to: "SPEAKER_2" });
  });

  it("sends 'new' for a missed speaker and names the one created", async () => {
    asr.reassignTurns.mockResolvedValue(
      reassigned({
        speakers: ["SPEAKER_1", "SPEAKER_2", "SPEAKER_3"],
        speaker_names: { SPEAKER_1: "Anna", SPEAKER_2: "Speaker 2", SPEAKER_3: "Speaker 3" },
        created_label: "SPEAKER_3",
      }),
    );
    await renderView();
    openAvatar("Hi Anna.");
    fireEvent.click(screen.getByRole("menuitem", { name: "New speaker" }));
    await waitFor(() => expect(asr.reassignTurns).toHaveBeenCalled());
    expect(asr.reassignTurns.mock.calls[0]![1]).toEqual({ resultRev: 3, segmentIndices: [42], to: "new" });
    expect(await screen.findByText("Moved 1 turn to Speaker 3")).toBeInTheDocument();
  });

  it("sends null for Unknown, and an unattributed turn is not offered Unknown", async () => {
    await renderView();
    openAvatar("Let's start.");
    fireEvent.click(screen.getByRole("menuitem", { name: "Unknown" }));
    await waitFor(() => expect(asr.reassignTurns).toHaveBeenCalled());
    expect(asr.reassignTurns.mock.calls[0]![1]).toEqual({ resultRev: 3, segmentIndices: [45, 46], to: null });

    await screen.findByText("Moved 1 turn to Unknown speaker");
    openAvatar("(noise)");
    expect(screen.queryByRole("menuitem", { name: "Unknown" })).toBeNull();
    expect(screen.getByRole("menuitem", { name: "Anna" })).toBeInTheDocument();
  });

  it("undoes the move by deleting that edit", async () => {
    await renderView();
    openAvatar("Hello all.");
    fireEvent.click(screen.getByRole("menuitem", { name: "Speaker 2" }));
    await screen.findByText("Moved 1 turn to Speaker 2");
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(asr.undoSpeakerEdit).toHaveBeenCalledWith("job-1", "edit-9"));
  });

  it("shows the move before the server answers, and puts it back on a refusal", async () => {
    let refuse!: (e: unknown) => void;
    asr.reassignTurns.mockReturnValue(new Promise((_, reject) => (refuse = reject)));
    await renderView();
    openAvatar("Hello all.");
    fireEvent.click(screen.getByRole("menuitem", { name: "Speaker 2" }));
    await waitFor(() => expect(within(turnOf("Hello all.")).getByText("Speaker 2")).toBeInTheDocument());
    await act(async () => refuse(new ApiError(422, { code: "too_many_speakers", detail: "max 8" })));
    expect(within(turnOf("Hello all.")).getByText("Anna")).toBeInTheDocument();
    expect(await screen.findByText(/at most 8 speakers/)).toBeInTheDocument();
  });

  it("marks an over-talked turn", async () => {
    await renderView();
    const mark = screen.getByRole("img", { name: "People talked over each other here." });
    expect(mark).toHaveAttribute("title", "People talked over each other here.");
    expect(within(turnOf("Hi Anna.")).getByRole("img")).toBe(mark);
  });
});

describe("moving several turns", () => {
  it("concatenates the selected turns' indices into one call", async () => {
    await renderView();
    fireEvent.click(screen.getByText("Let's start."), { shiftKey: true });
    fireEvent.click(within(turnOf("Hello all.")).getByRole("checkbox"));
    // Shift-click on an avatar selects rather than opening its menu.
    fireEvent.click(within(turnOf("Hi Anna.")).getByRole("button", { name: /move this turn/ }), { shiftKey: true });
    expect(screen.queryByRole("menu")).toBeNull();

    const bar = screen.getByRole("toolbar", { name: "Selected turns" });
    fireEvent.click(within(bar).getByRole("button", { name: "Move 3 turns to" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Unknown" }));
    await waitFor(() => expect(asr.reassignTurns).toHaveBeenCalledTimes(1));
    expect(asr.reassignTurns).toHaveBeenCalledWith("job-1", {
      resultRev: 3,
      segmentIndices: [40, 41, 42, 45, 46],
      to: null,
    });
    expect(await screen.findByText("Moved 3 turns to Unknown speaker")).toBeInTheDocument();
  });

  it("assigns the focused turn from the keyboard and moves focus with the arrows", async () => {
    await renderView();
    const first = turnOf("Hello all.");
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(turnOf("Hi Anna.")).toHaveFocus();
    fireEvent.keyDown(turnOf("Hi Anna."), { key: "1" });
    await waitFor(() => expect(asr.reassignTurns).toHaveBeenCalled());
    expect(asr.reassignTurns.mock.calls[0]![1]).toEqual({ resultRev: 3, segmentIndices: [42], to: "SPEAKER_1" });
  });

  it("reloads and says so when the speakers changed elsewhere", async () => {
    asr.reassignTurns.mockRejectedValue(new ApiError(409, { code: "stale_result_rev", detail: "stale", current_rev: 4 }));
    asr.getResult.mockResolvedValueOnce(result()).mockResolvedValue(result({ result_rev: 4 }));
    await renderView();
    openAvatar("Hello all.");
    fireEvent.click(screen.getByRole("menuitem", { name: "Speaker 2" }));
    expect(await screen.findByText("Speakers were updated elsewhere.")).toBeInTheDocument();
    expect(asr.getResult).toHaveBeenCalledTimes(2);

    // The next move carries the fresh revision.
    asr.reassignTurns.mockResolvedValue(reassigned());
    openAvatar("Hello all.");
    fireEvent.click(screen.getByRole("menuitem", { name: "Speaker 2" }));
    await waitFor(() => expect(asr.reassignTurns).toHaveBeenCalledTimes(2));
    expect(asr.reassignTurns.mock.calls[1]![1]).toMatchObject({ resultRev: 4 });
  });

  it("is off while offline", async () => {
    await renderView();
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });
    expect(within(turnOf("Hello all.")).getByRole("button", { name: /move this turn/ })).toBeDisabled();
    expect(within(turnOf("Hello all.")).getByRole("checkbox")).toBeDisabled();
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    expect(within(turnOf("Hello all.")).getByRole("button", { name: /move this turn/ })).toBeEnabled();
  });

  it("is off while speakers are being re-labelled", async () => {
    asr.getJob.mockResolvedValue({ ...job(), diarization_status: "running" });
    await renderView();
    await screen.findByText(/Re-labelling speakers/);
    expect(within(turnOf("Hello all.")).getByRole("button", { name: /move this turn/ })).toBeDisabled();
  });
});

describe("naming from the invitees", () => {
  it("leaves out names already on another speaker", () => {
    expect(pickableNames(["Anna", "Tom Berg", " tom berg ", "Olena"], { SPEAKER_1: "anna", SPEAKER_2: "Olena" }, "SPEAKER_2")).toEqual([
      "Tom Berg",
      "Olena",
    ]);
  });

  it("saves a picked name straight away, marked as picked", async () => {
    asr.setSpeakerNames.mockResolvedValue({ job_id: "job-1", speaker_names: { SPEAKER_1: "Anna", SPEAKER_2: "Tom Berg" } });
    await renderView();
    fireEvent.click(screen.getByRole("button", { name: "Speaker 2" }));
    const list = screen.getByRole("group", { name: "Invited people" });
    expect(within(list).queryByRole("button", { name: "Anna" })).toBeNull();
    fireEvent.click(within(list).getByRole("button", { name: "Tom Berg" }));
    await waitFor(() =>
      expect(asr.setSpeakerNames).toHaveBeenCalledWith(
        "job-1",
        { SPEAKER_1: "Anna", SPEAKER_2: "Tom Berg" },
        { SPEAKER_2: "picklist" },
      ),
    );
  });

  it("marks a typed name as typed", async () => {
    asr.setSpeakerNames.mockResolvedValue({ job_id: "job-1", speaker_names: { SPEAKER_1: "Anna", SPEAKER_2: "Olena" } });
    await renderView();
    fireEvent.click(screen.getByRole("button", { name: "Speaker 2" }));
    const input = screen.getByRole("textbox", { name: "Speaker name" });
    fireEvent.change(input, { target: { value: "Olena" } });
    // Typing narrows the list to what matches.
    expect(screen.getByRole("button", { name: "Olena Shevchenko" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tom Berg" })).toBeNull();
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(asr.setSpeakerNames).toHaveBeenCalledWith("job-1", { SPEAKER_1: "Anna", SPEAKER_2: "Olena" }, { SPEAKER_2: "typed" }),
    );
  });
});
