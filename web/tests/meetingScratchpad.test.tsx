import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToasterProvider } from "../src/components/Toaster";
import { LineTimeQueue, lineKey, mergeScratch } from "../src/lib/myNotes";
import { MeetingPage } from "../src/pages/MeetingPage";

const asr = vi.hoisted(() => ({ submitJob: vi.fn(), listJobs: vi.fn() }));
vi.mock("../src/api/asr", async (orig) => ({
  ...(await orig<typeof import("../src/api/asr")>()),
  ...asr,
}));

const notes = vi.hoisted(() => ({
  startMeeting: vi.fn(),
  getNote: vi.fn(),
  updateDraft: vi.fn(),
  putLineTimes: vi.fn(),
  attachJob: vi.fn(),
  attachTranscript: vi.fn(),
  notesBySourceJob: vi.fn(),
}));
vi.mock("../src/api/notes", async (orig) => ({
  ...(await orig<typeof import("../src/api/notes")>()),
  ...notes,
}));

const recorder = vi.hoisted(() => ({
  onDone: null as null | ((audio: { blob: Blob; filename: string }) => void),
  recording: false,
}));
vi.mock("../src/lib/useRecorder", () => ({
  useRecorder: (onDone: (a: { blob: Blob; filename: string }) => void) => {
    recorder.onDone = onDone;
    return {
      recording: recorder.recording,
      levels: [0, 0, 0],
      elapsedMs: 0,
      start: vi.fn(async () => {
        recorder.recording = true;
      }),
      stop: vi.fn(() => {
        recorder.recording = false;
      }),
    };
  },
}));

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

const CONTENT = {
  template_id: "tpl-1",
  template_schema_version: 1,
  title: "Untitled meeting",
  sections: [
    { section_key: "user_notes", text: "" },
    { section_key: "discussion", text: "" },
  ],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/meeting/new"]}>
      <ToasterProvider>
        <MeetingPage />
      </ToasterProvider>
    </MemoryRouter>,
  ).container;
}

async function pressRecord() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /Record/ }));
  });
}

beforeEach(() => {
  vi.stubGlobal("localStorage", memoryStorage());
  recorder.recording = false;
  recorder.onDone = null;
  asr.listJobs.mockReset().mockResolvedValue([]);
  asr.submitJob.mockReset().mockResolvedValue({ id: "job-9", status: "queued" });
  notes.startMeeting.mockReset().mockResolvedValue({
    id: "note-1",
    code: "N-1",
    version_number: 1,
    template_id: "tpl-1",
    state: "recording",
  });
  notes.getNote
    .mockReset()
    .mockResolvedValue({ id: "note-1", current_version_number: 1, content: CONTENT });
  notes.updateDraft.mockReset().mockResolvedValue({ version_number: 2 });
  notes.putLineTimes.mockReset().mockResolvedValue(undefined);
  notes.attachJob.mockReset().mockResolvedValue({ state: "transcribing" });
  notes.attachTranscript.mockReset().mockResolvedValue({ state: "ready" });
  notes.notesBySourceJob.mockReset().mockResolvedValue([]);
});
afterEach(() => vi.unstubAllGlobals());

describe("the note exists from the first second", () => {
  it("opens the note as Record is pressed and gives the scratchpad the caret", async () => {
    renderPage();
    await pressRecord();
    await waitFor(() => expect(notes.startMeeting).toHaveBeenCalled());
    const body = notes.startMeeting.mock.calls[0]![0];
    expect(body.client_capture_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(body.meeting_type).toBe("auto");
    expect(screen.getByRole("textbox", { name: "My notes" })).toBeInTheDocument();
  });

  it("the meeting type chosen at the start goes with it", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Sales" }));
    await pressRecord();
    await waitFor(() => expect(notes.startMeeting).toHaveBeenCalled());
    expect(notes.startMeeting.mock.calls[0]![0].meeting_type).toBe("sales");
  });

  it("records even when the note cannot be opened", async () => {
    notes.startMeeting.mockRejectedValue(new Error("offline"));
    renderPage();
    await pressRecord();
    // Recording is live and the scratchpad is usable regardless.
    expect(screen.getByRole("textbox", { name: "My notes" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Stop/ })).toBeInTheDocument();
  });

  it("creates the note at stop when the start failed, then binds the job", async () => {
    notes.startMeeting.mockRejectedValueOnce(new Error("offline"));
    renderPage();
    await pressRecord();
    await act(async () => recorder.onDone?.({ blob: new Blob(["x"]), filename: "m.webm" }));
    await waitFor(() => expect(notes.attachJob).toHaveBeenCalledWith("note-1", "job-9"));
    expect(notes.startMeeting).toHaveBeenCalledTimes(2);
    // Same capture id on both attempts, so a note from the first is not duplicated.
    const [first, second] = notes.startMeeting.mock.calls.map((c) => c[0].client_capture_id);
    expect(first).toBe(second);
  });

  it("autosaves what is typed and reports each line's first keystroke", async () => {
    vi.useFakeTimers();
    try {
      renderPage();
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: /Record/ }));
      });
      await act(async () => {
        await Promise.resolve();
      });
      const pad = screen.getByRole("textbox", { name: "My notes" });
      fireEvent.change(pad, { target: { value: "budget 40k\nTom hesitated" } });
      await act(async () => {
        vi.advanceTimersByTime(1000);
        await Promise.resolve();
      });
      await vi.waitFor(() => expect(notes.updateDraft).toHaveBeenCalled());
      const [, content] = notes.updateDraft.mock.calls[0]!;
      const typed = content.sections.find(
        (s: { section_key: string }) => s.section_key === "user_notes",
      );
      expect(typed.text).toBe("budget 40k\nTom hesitated");
      await vi.waitFor(() => expect(notes.putLineTimes).toHaveBeenCalled());
      const [, lines] = notes.putLineTimes.mock.calls[0]!;
      expect(lines).toHaveLength(2);
      expect(lines[0]).toMatchObject({ line_key: expect.stringMatching(/^[0-9a-f]{16}$/) });
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("line keys and merging", () => {
  it("keys a line the way the server does — bullet, case and spacing aside", async () => {
    expect(await lineKey("- Ask about budget")).toBe(await lineKey("ask   about budget."));
    expect(await lineKey("   ")).toBe("");
    expect(await lineKey("budget")).toMatch(/^[0-9a-f]{16}$/);
  });

  it("reports a line once, at the moment it first appears", async () => {
    let now = 0;
    const q = new LineTimeQueue(() => now);
    await q.observe("first line");
    now = 90_000;
    await q.observe("first line\nsecond line");
    const out = q.drain();
    expect(out).toHaveLength(2);
    expect(out[0]!.offset_ms).toBe(0);
    expect(out[1]!.offset_ms).toBe(90_000);
    // Drained once; the same text again adds nothing.
    await q.observe("first line\nsecond line");
    expect(q.drain()).toEqual([]);
  });

  it("requeues a failed flush rather than losing it", async () => {
    const q = new LineTimeQueue(() => 0);
    await q.observe("a line");
    const sent = q.drain();
    q.requeue(sent);
    expect(q.drain()).toEqual(sent);
  });

  it("appends the other device's lines under a divider, never overwriting", () => {
    expect(mergeScratch("theirs", "")).toBe("theirs");
    expect(mergeScratch("", "mine")).toBe("mine");
    expect(mergeScratch("shared", "shared")).toBe("shared");
    expect(mergeScratch("theirs", "mine")).toBe("theirs\n\n---\nmine");
    // A line both devices have is not duplicated.
    expect(mergeScratch("shared\ntheirs", "shared\nmine")).toBe("shared\ntheirs\n\n---\nmine");
  });
});
