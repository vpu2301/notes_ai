import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { submitJob, type SubmitJobParams } from "../src/api/asr";
import { captureTiming, useRecorder, type RecordedAudio } from "../src/lib/useRecorder";
import { formatOffset } from "../src/lib/time";

/**
 * Sprint F1 T1 (web): when Record was clicked and how long until the
 * recorder wrote its first audio, measured in the browser and sent with
 * the upload.
 */

const http = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("../src/api/http", async (orig) => ({
  ...(await orig<typeof import("../src/api/http")>()),
  api: http.api,
}));

const base: SubmitJobParams = {
  audio: new Blob(["x"], { type: "audio/webm" }),
  filename: "m.webm",
  language: "auto",
  diarize: true,
};

const sentForm = (): FormData => (http.api.mock.calls[0]![2] as { form: FormData }).form;

describe("captureTiming", () => {
  it("is the click as ISO 8601 and the distance to the first frame", () => {
    const t = captureTiming(Date.UTC(2026, 8, 26, 10, 0, 0), 1_000, 3_400.4);
    expect(t).toEqual({ recordPressedAt: "2026-09-26T10:00:00.000Z", firstFrameOffsetMs: 2_400 });
  });

  it("clamps to 0..600000", () => {
    expect(captureTiming(0, 5_000, 4_000).firstFrameOffsetMs).toBe(0);
    expect(captureTiming(0, 0, 900_000).firstFrameOffsetMs).toBe(600_000);
  });

  it("omits the offset when no frame was ever written", () => {
    expect(captureTiming(0, 0, null)).toEqual({ recordPressedAt: "1970-01-01T00:00:00.000Z" });
  });

  it("formats the latency as m:ss", () => {
    expect(formatOffset(3_000)).toBe("0:03");
    expect(formatOffset(64_400)).toBe("1:04");
  });
});

describe("submitJob capture fields", () => {
  beforeEach(() => http.api.mockReset().mockResolvedValue({ id: "job-1", status: "queued" }));

  it("sends both when known", async () => {
    await submitJob({ ...base, recordPressedAt: "2026-09-26T10:00:00.000Z", firstFrameOffsetMs: 2_400 });
    expect(sentForm().get("record_pressed_at")).toBe("2026-09-26T10:00:00.000Z");
    expect(sentForm().get("first_frame_offset_ms")).toBe("2400");
  });

  it("sends neither for an uploaded file", async () => {
    await submitJob(base);
    expect(sentForm().has("record_pressed_at")).toBe(false);
    expect(sentForm().has("first_frame_offset_ms")).toBe(false);
  });

  it("keeps an offset inside the range the server accepts", async () => {
    await submitJob({ ...base, firstFrameOffsetMs: 10_000_000 });
    expect(sentForm().get("first_frame_offset_ms")).toBe("600000");
  });
});

// ── the hook, with a scripted browser ──────────────────────────────────

class FakeRecorder {
  static last: FakeRecorder | null = null;
  static isTypeSupported = () => true;
  mimeType = "audio/webm";
  onstart: (() => void) | null = null;
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor() {
    FakeRecorder.last = this;
  }
  start() {}
  stop() {
    this.onstop?.();
  }
}

class FakeAudioContext {
  createAnalyser = () => ({ fftSize: 0, connect: vi.fn(), getByteTimeDomainData: vi.fn() });
  createMediaStreamSource = () => ({ connect: vi.fn() });
  close = () => Promise.resolve();
}

let now = 0;

beforeEach(() => {
  now = 1_000;
  vi.spyOn(performance, "now").mockImplementation(() => now);
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("requestAnimationFrame", () => 0);
  vi.stubGlobal("cancelAnimationFrame", () => undefined);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async () => {
        now += 1_800; // the permission prompt
        return { getTracks: () => [] };
      }),
    },
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("useRecorder capture timing", () => {
  it("measures the click to the recorder's first frame and hands both to the upload", async () => {
    const done = vi.fn<(a: RecordedAudio) => void>();
    const { result } = renderHook(() => useRecorder(done, vi.fn()));
    await act(async () => {
      await result.current.start();
    });
    expect(result.current.firstFrameOffsetMs).toBeNull(); // still "Starting…"

    now += 700;
    act(() => FakeRecorder.last!.onstart!());
    expect(result.current.firstFrameOffsetMs).toBe(2_500);

    // Later chunks do not move the measure.
    now += 5_000;
    act(() => FakeRecorder.last!.ondataavailable!({ data: new Blob(["a"]) }));
    act(() => result.current.stop());

    const audio = done.mock.calls[0]![0];
    expect(audio.firstFrameOffsetMs).toBe(2_500);
    expect(audio.recordPressedAt).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/);
  });

  it("falls back to the first non-empty chunk when `start` never fired", async () => {
    const done = vi.fn<(a: RecordedAudio) => void>();
    const { result } = renderHook(() => useRecorder(done, vi.fn()));
    await act(async () => {
      await result.current.start();
    });
    now += 1_000;
    act(() => FakeRecorder.last!.ondataavailable!({ data: new Blob([]) })); // empty: not a frame
    expect(result.current.firstFrameOffsetMs).toBeNull();
    now += 200;
    act(() => FakeRecorder.last!.ondataavailable!({ data: new Blob(["a"]) }));
    act(() => result.current.stop());
    expect(done.mock.calls[0]![0].firstFrameOffsetMs).toBe(3_000);
  });
});
