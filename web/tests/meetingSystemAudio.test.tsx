import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/http";
import { ToasterProvider } from "../src/components/Toaster";
import type { RecordedAudio, RecorderOptions } from "../src/lib/useRecorder";
import { MeetingPage } from "../src/pages/MeetingPage";

/**
 * Sprint I3 T4: the "Me / Them" checkbox on the meeting page, what a
 * 2-channel recording is uploaded with, and the mono retry when the server
 * cannot read it as one.
 */

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

vi.mock("../src/auth/AuthContext", async (orig) => ({
  ...(await orig<typeof import("../src/auth/AuthContext")>()),
  useAuthOptional: () => ({ displayName: "Ada Lovelace" }),
}));

const recorder = vi.hoisted(() => ({
  onDone: null as null | ((audio: RecordedAudio) => void),
  options: null as null | RecorderOptions,
  recording: false,
  // Sprint F1: null = no frame written yet ("Starting…").
  firstFrameOffsetMs: 0 as number | null,
}));
vi.mock("../src/lib/useRecorder", async (orig) => ({
  ...(await orig<typeof import("../src/lib/useRecorder")>()),
  useRecorder: (onDone: (a: RecordedAudio) => void, _onError: unknown, options: RecorderOptions) => {
    recorder.onDone = onDone;
    recorder.options = options;
    return {
      recording: recorder.recording,
      levels: [0, 0, 0],
      elapsedMs: 0,
      firstFrameOffsetMs: recorder.firstFrameOffsetMs,
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

function renderPage() {
  const view = render(
    <MemoryRouter initialEntries={["/meeting/new"]}>
      <ToasterProvider>
        <MeetingPage />
      </ToasterProvider>
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Options" }));
  return view;
}

const checkbox = () =>
  screen.getByRole("checkbox", { name: "Also record this tab's audio (Me / Them)" });

async function finishRecording(audio: RecordedAudio) {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /Record/ }));
  });
  await act(async () => {
    recorder.onDone!(audio);
  });
}

const stereo = (): RecordedAudio => ({
  blob: new Blob(["lr"], { type: "audio/webm" }),
  filename: "meeting-1.webm",
  channelLayout: "mic_system",
});

let storage: Storage;

beforeEach(() => {
  storage = memoryStorage();
  vi.stubGlobal("localStorage", storage);
  recorder.recording = false;
  recorder.firstFrameOffsetMs = 0;
  recorder.onDone = null;
  recorder.options = null;
  asr.listJobs.mockReset().mockResolvedValue([]);
  asr.submitJob.mockReset().mockResolvedValue({ id: "job-9", status: "queued" });
  notes.startMeeting.mockReset().mockResolvedValue({
    id: "note-1",
    code: "N-1",
    version_number: 1,
    template_id: "tpl-1",
    state: "recording",
  });
  notes.getNote.mockReset().mockResolvedValue({
    id: "note-1",
    current_version_number: 1,
    content: { template_id: "tpl-1", template_schema_version: 1, title: "", sections: [] },
  });
  notes.updateDraft.mockReset().mockResolvedValue({ version_number: 2 });
  notes.putLineTimes.mockReset().mockResolvedValue(undefined);
  notes.attachJob.mockReset().mockResolvedValue({ state: "transcribing" });
  notes.attachTranscript.mockReset().mockResolvedValue({ state: "ready" });
  notes.notesBySourceJob.mockReset().mockResolvedValue([]);
});
afterEach(() => vi.unstubAllGlobals());

describe("the Me / Them option", () => {
  it("is off by default and hands the recorder the choice", () => {
    renderPage();
    expect(checkbox()).not.toBeChecked();
    expect(recorder.options?.systemAudio).toBe(false);
  });

  it("is remembered in this browser", () => {
    const first = renderPage();
    fireEvent.click(checkbox());
    expect(checkbox()).toBeChecked();
    expect(storage.getItem("notesai.capture.systemAudio")).toBe("1");
    expect(recorder.options?.systemAudio).toBe(true);
    first.unmount();

    renderPage();
    expect(checkbox()).toBeChecked();
  });

  it("tells the author when the browser offered no tab audio", () => {
    renderPage();
    act(() => recorder.options!.onSystemAudioUnavailable!());
    expect(
      screen.getByText("Recording the microphone only — the browser offered no tab audio."),
    ).toBeInTheDocument();
  });
});

describe("uploading a two-channel recording", () => {
  it("declares mic_system and names the author's channel", async () => {
    renderPage();
    await finishRecording(stereo());
    await waitFor(() => expect(asr.submitJob).toHaveBeenCalledTimes(1));
    const params = asr.submitJob.mock.calls[0]![0];
    expect(params.channelLayout).toBe("mic_system");
    expect(params.localSpeakerName).toBe("Ada Lovelace");
  });

  it("sends a mono recording without either field", async () => {
    renderPage();
    await finishRecording({ ...stereo(), channelLayout: "mono" });
    await waitFor(() => expect(asr.submitJob).toHaveBeenCalledTimes(1));
    const params = asr.submitJob.mock.calls[0]![0];
    expect(params.channelLayout).toBeUndefined();
    expect(params.localSpeakerName).toBeUndefined();
  });

  it("an uploaded file is never declared two-channel", async () => {
    const { container } = renderPage();
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "m.webm", { type: "audio/webm" })] },
    });
    await waitFor(() => expect(asr.submitJob).toHaveBeenCalledTimes(1));
    expect(asr.submitJob.mock.calls[0]![0].channelLayout).toBeUndefined();
  });

  it("retries once as mono on channel_layout_mismatch and says so", async () => {
    asr.submitJob
      .mockRejectedValueOnce(
        new ApiError(422, { code: "channel_layout_mismatch", detail: "not 2 channels" }),
      )
      .mockResolvedValueOnce({ id: "job-9", status: "queued" });
    renderPage();
    await finishRecording(stereo());
    await waitFor(() => expect(asr.submitJob).toHaveBeenCalledTimes(2));
    const retry = asr.submitJob.mock.calls[1]![0];
    expect(retry.channelLayout).toBeUndefined();
    expect(retry.localSpeakerName).toBeUndefined();
    expect(retry.filename).toBe("meeting-1.webm");
    expect(
      await screen.findByText("Recorded as a single channel — the tab audio could not be separated."),
    ).toBeInTheDocument();
    // The upload went through: the page moved on to processing.
    await waitFor(() => expect(notes.attachJob).toHaveBeenCalled());
  });
});

describe("capture timing (Sprint F1)", () => {
  it("sends when Record was pressed and how long until audio flowed", async () => {
    renderPage();
    await finishRecording({
      ...stereo(),
      channelLayout: "mono",
      recordPressedAt: "2026-09-26T10:00:00.000Z",
      firstFrameOffsetMs: 2_400,
    });
    await waitFor(() => expect(asr.submitJob).toHaveBeenCalledTimes(1));
    const params = asr.submitJob.mock.calls[0]![0];
    expect(params.recordPressedAt).toBe("2026-09-26T10:00:00.000Z");
    expect(params.firstFrameOffsetMs).toBe(2_400);
  });

  it("sends neither for an uploaded file", async () => {
    const { container } = renderPage();
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "m.webm", { type: "audio/webm" })] },
    });
    await waitFor(() => expect(asr.submitJob).toHaveBeenCalledTimes(1));
    const params = asr.submitJob.mock.calls[0]![0];
    expect(params.recordPressedAt).toBeUndefined();
    expect(params.firstFrameOffsetMs).toBeUndefined();
  });

  const startRecording = async () => {
    const view = renderPage();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Record/ }));
    });
    // The mock reads `recording` at render: render again as the page would.
    view.rerender(
      <MemoryRouter initialEntries={["/meeting/new"]}>
        <ToasterProvider>
          <MeetingPage />
        </ToasterProvider>
      </MemoryRouter>,
    );
  };

  it("reads Starting… until the first frame", async () => {
    recorder.firstFrameOffsetMs = null;
    await startRecording();
    expect(screen.getByText("Starting…")).toBeInTheDocument();
    expect(screen.queryByText(/Recording from/)).toBeNull();
  });

  it("shows the latency beside the clock when audio started late", async () => {
    recorder.firstFrameOffsetMs = 3_200;
    await startRecording();
    expect(screen.getByText("Recording from 0:03")).toBeInTheDocument();
    expect(screen.getByText("00:00")).toBeInTheDocument();
  });

  it("says nothing for an ordinary start under a second", async () => {
    recorder.firstFrameOffsetMs = 400;
    await startRecording();
    expect(screen.queryByText(/Recording from/)).toBeNull();
  });
});
