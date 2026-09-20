import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/http";
import { SpeakerRoster } from "../src/components/SpeakerRoster";
import type { AsrJob, SpeakerStat } from "../src/api/types";
import { turnsToNoteText } from "../src/pages/NoteEditorPage";

const asr = vi.hoisted(() => ({
  getJob: vi.fn(),
  rediarize: vi.fn(),
  undoRediarize: vi.fn(),
  resetSpeakerEdits: vi.fn(),
  setSpeakerNames: vi.fn(),
}));
vi.mock("../src/api/asr", async (orig) => ({ ...(await orig<typeof import("../src/api/asr")>()), ...asr }));

function job(over: Partial<AsrJob> = {}): AsrJob {
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
    can_undo_rediarize: false,
    ...over,
  };
}

/** Node 25's own (file-less) `localStorage` shadows jsdom's here; give the page a working one. */
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

/** Let pending promises (and effects they trigger) settle. */
async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

const STATS: SpeakerStat[] = [
  { label: "SPEAKER_1", speech_ms: 300_000, share: 0.62, turns: 20 },
  { label: "SPEAKER_2", speech_ms: 175_000, share: 0.36, turns: 18 },
  { label: "SPEAKER_3", speech_ms: 7_000, share: 0.02, turns: 2 },
];
const SPEAKERS = ["SPEAKER_1", "SPEAKER_2", "SPEAKER_3"];

function renderRoster(overrides: Partial<Parameters<typeof SpeakerRoster>[0]> = {}) {
  const props = {
    jobId: "job-1",
    speakers: SPEAKERS,
    names: { SPEAKER_1: "Anna" },
    stats: STATS,
    busy: false,
    undo: null,
    onRename: vi.fn(),
    onMerge: vi.fn(),
    ...overrides,
  };
  render(<SpeakerRoster {...props} />);
  return props;
}

describe("speaker roster", () => {
  beforeEach(() => {
    sessionStorage.clear();
    asr.getJob.mockResolvedValue(job());
  });

  it("shows each speaker with its talk share", () => {
    renderRoster();
    expect(screen.getByText("62 %")).toBeInTheDocument();
    expect(screen.getAllByText("Speaker 2").length).toBeGreaterThan(0);
  });

  it("asks about a speaker who barely spoke and merges in one click", () => {
    const props = renderRoster();
    expect(screen.getByText("Speaker 3 spoke for 7 s. Same person as someone else?")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Anna" }));
    expect(props.onMerge).toHaveBeenCalledWith("SPEAKER_3", "SPEAKER_1");
  });

  it("hides the prompt when nobody is small", () => {
    renderRoster({ speakers: SPEAKERS.slice(0, 2), stats: STATS.slice(0, 2) });
    expect(screen.queryByText(/Same person as someone else/)).toBeNull();
  });

  it("remembers Keep for the job", () => {
    renderRoster();
    fireEvent.click(screen.getByRole("button", { name: "Keep" }));
    expect(screen.queryByText(/Same person as someone else/)).toBeNull();
    expect(JSON.parse(sessionStorage.getItem("speaker-keep:job-1") ?? "[]")).toEqual(["SPEAKER_3"]);
  });

  it("merges from the chip menu", () => {
    const props = renderRoster();
    fireEvent.click(screen.getByRole("button", { name: "Speaker 2 — rename or merge" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Merge into Anna" }));
    expect(props.onMerge).toHaveBeenCalledWith("SPEAKER_2", "SPEAKER_1");
  });

  it("offers undo after a merge", () => {
    const onUndo = vi.fn();
    renderRoster({ undo: { into: "SPEAKER_1", onUndo } });
    expect(screen.getByText("Merged into Anna")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(onUndo).toHaveBeenCalled();
  });
});

describe("speaker sides and microphone names (Sprint 31)", () => {
  beforeEach(() => {
    sessionStorage.clear();
    asr.getJob.mockResolvedValue(job());
    asr.setSpeakerNames.mockReset();
  });

  it("marks each chip with the side it was heard on", () => {
    renderRoster({ sides: { SPEAKER_1: "local", SPEAKER_2: "remote", SPEAKER_3: "remote" } });
    expect(screen.getAllByRole("img", { name: "On your microphone" })).toHaveLength(1);
    expect(screen.getAllByRole("img", { name: "On the call audio" })).toHaveLength(2);
  });

  it("shows no side for a mono job", () => {
    renderRoster({ sides: {} });
    expect(screen.queryByRole("img", { name: "On your microphone" })).toBeNull();
    expect(screen.queryByRole("img", { name: "On the call audio" })).toBeNull();
  });

  it("marks only a channel-given name as from your microphone", () => {
    renderRoster({
      names: { SPEAKER_1: "Volodymyr", SPEAKER_2: "Olena" },
      nameSources: { SPEAKER_1: "channel", SPEAKER_2: "picklist" },
    });
    expect(screen.getAllByText("· from your microphone")).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: /^Remove the name / })).toHaveLength(1);
  });

  it("shows no marker for typed, picked, suggested or cleared names", () => {
    renderRoster({
      names: { SPEAKER_1: "Anna", SPEAKER_2: "Olena", SPEAKER_3: "Max" },
      nameSources: { SPEAKER_1: "typed", SPEAKER_2: "suggestion", SPEAKER_3: "cleared" },
    });
    expect(screen.queryByText("· from your microphone")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Remove the name / })).toBeNull();
  });

  it("✕ removes that name and keeps every other one", async () => {
    asr.setSpeakerNames.mockResolvedValue({ job_id: "job-1", speaker_names: { SPEAKER_2: "Olena" } });
    const onNameCleared = vi.fn();
    renderRoster({
      names: { SPEAKER_1: "Volodymyr", SPEAKER_2: "Olena", SPEAKER_3: "Speaker 3" },
      nameSources: { SPEAKER_1: "channel", SPEAKER_2: "typed" },
      onNameCleared,
    });
    fireEvent.click(screen.getByRole("button", { name: /^Remove the name / }));
    expect(asr.setSpeakerNames).toHaveBeenCalledWith("job-1", { SPEAKER_2: "Olena" });
    await waitFor(() => expect(onNameCleared).toHaveBeenCalledWith("SPEAKER_1", { SPEAKER_2: "Olena" }));
  });

  it("says so when the name couldn't be removed", async () => {
    asr.setSpeakerNames.mockRejectedValue(new Error("offline"));
    const onNameCleared = vi.fn();
    renderRoster({ names: { SPEAKER_1: "Volodymyr" }, nameSources: { SPEAKER_1: "channel" }, onNameCleared });
    fireEvent.click(screen.getByRole("button", { name: /^Remove the name / }));
    expect(await screen.findByText(/Couldn't remove Volodymyr/)).toBeInTheDocument();
    expect(onNameCleared).not.toHaveBeenCalled();
  });
});

describe("reset speaker edits", () => {
  beforeEach(() => {
    sessionStorage.clear();
    asr.getJob.mockReset().mockResolvedValue(job());
    asr.resetSpeakerEdits.mockReset().mockResolvedValue(undefined);
  });

  const openReset = () => {
    fireEvent.click(screen.getByRole("button", { name: "Speaker options" }));
    return screen.getByRole("menuitem", { name: "Reset speaker edits" });
  };

  it("asks first, then resets and reloads", async () => {
    const onReset = vi.fn();
    renderRoster({ mergeCount: 2, onReset });
    fireEvent.click(openReset());
    const dialog = screen.getByRole("alertdialog", { name: "Reset speaker edits?" });
    expect(dialog).toHaveTextContent("All merges and moved turns in this transcript will be undone.");
    expect(asr.resetSpeakerEdits).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    await waitFor(() => expect(onReset).toHaveBeenCalled());
    expect(asr.resetSpeakerEdits).toHaveBeenCalledWith("job-1");
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("does nothing on cancel", () => {
    renderRoster({ mergeCount: 1 });
    fireEvent.click(openReset());
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(asr.resetSpeakerEdits).not.toHaveBeenCalled();
  });

  it("is off with no edits to reset", () => {
    renderRoster({ mergeCount: 0 });
    expect(openReset()).toBeDisabled();
  });

  it("shows a moved-turn undo in its own words", () => {
    renderRoster({ undo: { message: "Moved 2 turns to Anna", onUndo: vi.fn() } });
    expect(screen.getByText("Moved 2 turns to Anna")).toBeInTheDocument();
  });
});

describe("speaker count re-run", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.stubGlobal("localStorage", memoryStorage());
    vi.useFakeTimers();
    asr.getJob.mockReset().mockResolvedValue(job());
    asr.rediarize.mockReset().mockResolvedValue({ job_id: "job-1", diarization_status: "queued", diarization_rev: 1 });
    asr.undoRediarize.mockReset().mockResolvedValue({ job_id: "job-1", diarization_status: "complete", diarization_rev: 3 });
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  const pick = (n: number) => {
    fireEvent.click(screen.getByRole("button", { name: "Wrong number of speakers?" }));
    fireEvent.click(screen.getByRole("button", { name: String(n) }));
  };

  it("re-labels with the number picked", async () => {
    renderRoster();
    await flush();
    pick(2);
    fireEvent.click(screen.getByRole("button", { name: "Re-label" }));
    await flush();
    expect(asr.rediarize).toHaveBeenCalledWith("job-1", 2);
  });

  it("warns that merges will be replaced", async () => {
    renderRoster({ mergeCount: 2 });
    await flush();
    pick(4);
    expect(screen.getByText(/Your 2 merges will be replaced by the new result\./)).toBeInTheDocument();
  });

  it("polls while queued and running, then reloads and offers undo", async () => {
    const onRelabelled = vi.fn();
    renderRoster({ onRelabelled });
    await flush();
    pick(2);
    fireEvent.click(screen.getByRole("button", { name: "Re-label" }));
    await flush();
    expect(screen.getByText("Re-labelling speakers… the transcript stays readable")).toBeInTheDocument();

    asr.getJob.mockResolvedValueOnce(job({ diarization_status: "running" }));
    await flush(3000);
    expect(screen.getByText("Re-labelling speakers… the transcript stays readable")).toBeInTheDocument();
    expect(onRelabelled).not.toHaveBeenCalled();

    asr.getJob.mockResolvedValue(job({ diarization_status: "complete", can_undo_rediarize: true }));
    await flush(3000);
    expect(onRelabelled).toHaveBeenCalledWith("rerun");
    expect(screen.queryByText(/Re-labelling speakers/)).toBeNull();
    expect(screen.getByText("Now 3 speakers")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    await flush();
    expect(asr.undoRediarize).toHaveBeenCalledWith("job-1");
    expect(onRelabelled).toHaveBeenCalledWith("undo");
    expect(screen.queryByText("Now 3 speakers")).toBeNull();
  });

  it("stops polling once the run is over", async () => {
    renderRoster();
    await flush();
    pick(2);
    fireEvent.click(screen.getByRole("button", { name: "Re-label" }));
    await flush();
    asr.getJob.mockResolvedValue(job({ diarization_status: "complete" }));
    await flush(3000);
    const calls = asr.getJob.mock.calls.length;
    await flush(9000);
    expect(asr.getJob.mock.calls.length).toBe(calls);
  });

  it("shows a failed run with a retry, keeping the old labels", async () => {
    const onRelabelled = vi.fn();
    renderRoster({ onRelabelled });
    await flush();
    pick(3);
    fireEvent.click(screen.getByRole("button", { name: "Re-label" }));
    await flush();
    asr.getJob.mockResolvedValue(job({ diarization_status: "failed", diarization_error: "stranded" }));
    await flush(3000);
    expect(screen.getByText("Couldn't re-label speakers")).toBeInTheDocument();
    expect(onRelabelled).not.toHaveBeenCalled();
    expect(screen.getByText("62 %")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await flush();
    expect(asr.rediarize).toHaveBeenCalledTimes(2);
    expect(asr.rediarize).toHaveBeenLastCalledWith("job-1", 3);
  });

  it("picks up a run already in flight when it opens", async () => {
    asr.getJob.mockResolvedValue(job({ diarization_status: "running" }));
    renderRoster();
    await flush();
    expect(screen.getByText("Re-labelling speakers… the transcript stays readable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wrong number of speakers?" })).toBeDisabled();
  });

  it("says a refusal in words", async () => {
    asr.rediarize.mockRejectedValue(new ApiError(429, { code: "rediarize_limit", detail: "limit reached" }));
    renderRoster();
    await flush();
    pick(2);
    fireEvent.click(screen.getByRole("button", { name: "Re-label" }));
    await flush();
    expect(screen.getByRole("alert")).toHaveTextContent("This transcript has been re-labelled as often as it can be.");
  });

  it("asks about the count before the small speaker, never both", async () => {
    renderRoster({ countConfidence: "low" });
    await flush();
    expect(screen.getByText("We're not sure how many people spoke.")).toBeInTheDocument();
    expect(screen.queryByText(/Same person as someone else/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Set number" }));
    expect(screen.getByRole("dialog", { name: "Number of speakers" })).toBeInTheDocument();
  });

  it("remembers Looks right for the job", async () => {
    renderRoster({ countConfidence: "low" });
    await flush();
    fireEvent.click(screen.getByRole("button", { name: "Looks right" }));
    expect(screen.queryByText("We're not sure how many people spoke.")).toBeNull();
    expect(localStorage.getItem("speaker-count-ok:job-1")).toBe("1");
    // With the count settled, the next question may be asked.
    expect(screen.getByText(/Same person as someone else/)).toBeInTheDocument();
  });

  it("says when fewer voices came back than were asked for", async () => {
    renderRoster({ speakersHint: 4 });
    await flush();
    expect(screen.getByText("Only 3 voices could be told apart.")).toBeInTheDocument();
  });
});

describe("note text from turns", () => {
  it("writes turns the way the note was written", () => {
    const text = turnsToNoteText(
      [
        { speaker: "SPEAKER_1", name: null, start_ms: 0, end_ms: 1, paragraphs: ["Hi.", "Second."] },
        { speaker: "SPEAKER_2", name: null, start_ms: 1, end_ms: 2, paragraphs: [" Hello. "] },
      ],
      { SPEAKER_1: "Anna" },
    );
    expect(text).toBe("Anna: Hi.\nSecond.\n\nSpeaker 2: Hello.");
  });
});
