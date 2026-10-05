import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { UpcomingEvent } from "../src/api/types";
import { ComingUp } from "../src/components/ComingUp";
import { ToasterProvider } from "../src/components/Toaster";
import { contextFields, nameCandidates, readCaptureContext } from "../src/lib/captureContext";
import type { RecordedAudio } from "../src/lib/useRecorder";
import { MeetingPage } from "../src/pages/MeetingPage";

const asr = vi.hoisted(() => ({
  submitJob: vi.fn(),
  listJobs: vi.fn(),
}));
vi.mock("../src/api/asr", async (orig) => ({ ...(await orig<typeof import("../src/api/asr")>()), ...asr }));
vi.mock("../src/api/notes", async (orig) => ({
  ...(await orig<typeof import("../src/api/notes")>()),
  notesBySourceJob: vi.fn().mockResolvedValue([]),
}));

const cal = vi.hoisted(() => ({
  listCalendarConnections: vi.fn(),
  upcomingEvents: vi.fn(),
}));
vi.mock("../src/api/calendar", async (orig) => ({ ...(await orig<typeof import("../src/api/calendar")>()), ...cal }));

// The microphone is not the subject: hand the page's own "done" callback
// to the test so a recording can "finish" on demand.
const recorder = vi.hoisted(() => ({ onDone: null as null | ((a: RecordedAudio) => void) }));
vi.mock("../src/lib/useRecorder", async (orig) => ({
  ...(await orig<typeof import("../src/lib/useRecorder")>()),
  useRecorder: (onDone: (a: RecordedAudio) => void) => {
    recorder.onDone = onDone;
    return { recording: false, elapsedMs: 0, levels: [], start: vi.fn(), stop: vi.fn() };
  },
}));

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

type Submitted = {
  speakersExpected?: number;
  speakersMax?: number;
  nameCandidates?: string[];
  captureSource?: string;
};

function renderMeeting(url: string) {
  const { container } = render(
    <MemoryRouter initialEntries={[url]}>
      <ToasterProvider>
        <MeetingPage />
      </ToasterProvider>
    </MemoryRouter>,
  );
  return container;
}

async function upload(container: HTMLElement): Promise<Submitted> {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
  fireEvent.change(input, { target: { files: [new File(["x"], "m.webm", { type: "audio/webm" })] } });
  await waitFor(() => expect(asr.submitJob).toHaveBeenCalled());
  return asr.submitJob.mock.calls[0]![0] as Submitted;
}

async function record(): Promise<Submitted> {
  await act(async () => recorder.onDone?.({ blob: new Blob(["x"]), filename: "meeting.webm" }));
  await waitFor(() => expect(asr.submitJob).toHaveBeenCalled());
  return asr.submitJob.mock.calls[0]![0] as Submitted;
}

function keep(eventId: string, ctx: unknown) {
  sessionStorage.setItem(`capture.ctx.${eventId}`, JSON.stringify(ctx));
}

beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal("localStorage", memoryStorage());
  asr.listJobs.mockReset().mockResolvedValue([]);
  asr.submitJob.mockReset().mockResolvedValue({ id: "job-9", status: "queued" });
  recorder.onDone = null;
});
afterEach(() => vi.unstubAllGlobals());

describe("capture from a calendar event", () => {
  it("bounds the speakers and offers the invitees' names", async () => {
    keep("ev-1", { attendee_count: 3, attendees: ["Anna Keller", "Tom Berg"] });
    renderMeeting("/meeting/new?title=Weekly&event=ev-1");
    expect(screen.getByText("3 invited · names will be offered for speakers")).toBeInTheDocument();
    const sent = await record();
    expect(sent.speakersMax).toBe(3);
    expect(sent.speakersExpected).toBeUndefined();
    expect(sent.nameCandidates).toEqual(["Anna Keller", "Tom Berg"]);
    expect(sent.captureSource).toBe("calendar_event");
  });

  it("caps the bound at 8", async () => {
    keep("ev-1", { attendee_count: 20, attendees: [] });
    renderMeeting("/meeting/new?event=ev-1");
    expect(screen.getByText("20 invited")).toBeInTheDocument();
    const sent = await record();
    expect(sent.speakersMax).toBe(8);
    expect(sent.nameCandidates).toBeUndefined();
  });

  it("sends no bound for a one-person event", async () => {
    keep("ev-1", { attendee_count: 1, attendees: ["Anna Keller"] });
    renderMeeting("/meeting/new?event=ev-1");
    const sent = await record();
    expect(sent.speakersMax).toBeUndefined();
    expect(sent.nameCandidates).toEqual(["Anna Keller"]);
  });

  it("still sends an exact People number alongside (the server lets it win)", async () => {
    keep("ev-1", { attendee_count: 4, attendees: [] });
    renderMeeting("/meeting/new?event=ev-1");
    fireEvent.click(screen.getByRole("button", { name: "Options" }));
    fireEvent.click(screen.getByRole("button", { name: "2" }));
    const sent = await record();
    expect(sent.speakersExpected).toBe(2);
    expect(sent.speakersMax).toBe(4);
  });

  it("marks a file dropped on an event's page as an upload", async () => {
    keep("ev-1", { attendee_count: 3, attendees: ["Tom Berg"] });
    const container = renderMeeting("/meeting/new?event=ev-1");
    const sent = await upload(container);
    expect(sent.captureSource).toBe("upload");
    expect(sent.speakersMax).toBe(3);
  });
});

describe("capture without an event", () => {
  it("sends no context and says nothing about invitees", async () => {
    renderMeeting("/meeting/new");
    expect(screen.queryByText(/invited/)).toBeNull();
    const sent = await record();
    expect(sent.captureSource).toBe("manual");
    expect(sent.speakersMax).toBeUndefined();
    expect(sent.nameCandidates).toBeUndefined();
  });

  it("marks a file as an upload", async () => {
    const sent = await upload(renderMeeting("/meeting/new"));
    expect(sent.captureSource).toBe("upload");
  });

  it("ignores an event whose context was not kept", async () => {
    renderMeeting("/meeting/new?event=gone");
    const sent = await record();
    expect(sent.captureSource).toBe("manual");
    expect(sent.speakersMax).toBeUndefined();
  });
});

describe("capture context helpers", () => {
  it("drops the person capturing, repeats, bad names, and keeps at most 12", () => {
    const many = Array.from({ length: 20 }, (_, i) => `Person ${i}`);
    expect(nameCandidates(["me@x.com", "Anna", "anna", "", "x".repeat(81), "Bad\u0007Name", ...many], ["ME@x.com"])).toEqual([
      "Anna",
      ...many.slice(0, 11),
    ]);
  });

  it("survives storage that throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(readCaptureContext("ev-1")).toBeNull();
    vi.restoreAllMocks();
  });

  it("never sends the count as a bound below two", () => {
    expect(
      contextFields({ attendee_count: 2, attendees: [], agenda: [], title: "", ical_uid: "" }),
    ).toEqual({ speakersMax: 2, nameCandidates: undefined });
    expect(contextFields(null)).toEqual({});
  });
});

describe("Start from the home page", () => {
  const event: UpcomingEvent = {
    id: "evt_42",
    connection_id: "c1",
    account_email: "me@example.com",
    calendar_id: "primary",
    calendar_name: "Work",
    color: null,
    title: "Design review",
    start: new Date(Date.now() + 3_600_000).toISOString(),
    end: new Date(Date.now() + 7_200_000).toISOString(),
    all_day: false,
    location: null,
    meeting_url: null,
    html_link: null,
    attendee_count: 3,
    attendees: ["me@example.com", "Anna Keller", "Tom Berg"],
    organizer: "me@example.com",
    response_status: "accepted",
    ical_uid: "evt_42@google.com",
    agenda_lines: ["Colour palette", "Typography"],
  };

  function Where() {
    const loc = useLocation();
    return <output aria-label="location">{loc.pathname + loc.search}</output>;
  }

  it("puts the event id in the URL and the names in session storage only", async () => {
    cal.listCalendarConnections.mockResolvedValue({
      available: true,
      connections: [
        {
          id: "c1",
          provider: "google",
          account_email: "me@example.com",
          connected_at: "2026-09-01T00:00:00Z",
          hidden_calendar_ids: [],
          needs_reauth: false,
          last_synced_at: null,
          last_error: null,
        },
      ],
    });
    cal.upcomingEvents.mockResolvedValue({
      available: true,
      connected: true,
      events: [event],
      problems: [],
      fetched_at: new Date().toISOString(),
    });
    render(
      <MemoryRouter initialEntries={["/"]}>
        <ToasterProvider>
          <Routes>
            <Route path="/" element={<ComingUp />} />
            <Route path="/meeting/new" element={<Where />} />
          </Routes>
        </ToasterProvider>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Start/ }));
    const url = screen.getByRole("status", { name: "location" }).textContent ?? "";
    const params = new URLSearchParams(url.split("?")[1]);
    expect(params.get("title")).toBe("Design review");
    expect(params.get("event")).toBe("evt_42");
    expect(url).not.toMatch(/Anna|Tom|Keller|Berg|example/);
    // Sprint 34: the agenda and the invite's identity ride along too —
    // they go on the note as the capture starts. Still never in the URL.
    expect(JSON.parse(sessionStorage.getItem("capture.ctx.evt_42") ?? "null")).toEqual({
      attendee_count: 3,
      attendees: ["Anna Keller", "Tom Berg"],
      agenda: ["Colour palette", "Typography"],
      title: "Design review",
      ical_uid: "evt_42@google.com",
    });
  });
});
