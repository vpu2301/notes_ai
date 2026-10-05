import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ToasterProvider } from "../src/components/Toaster";
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

/** The "People" segment. Sprint 34 put a meeting-type "Auto" chip on the
 *  same page, so these queries are scoped to the group. */
function people() {
  return within(screen.getByRole("group", { name: "People in the meeting" }));
}

function renderPage() {
  const { container } = render(
    <MemoryRouter initialEntries={["/meeting/new"]}>
      <ToasterProvider>
        <MeetingPage />
      </ToasterProvider>
    </MemoryRouter>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Options" }));
  return container;
}

async function upload(container: HTMLElement) {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
  fireEvent.change(input, { target: { files: [new File(["x"], "m.webm", { type: "audio/webm" })] } });
  await waitFor(() => expect(asr.submitJob).toHaveBeenCalled());
  return asr.submitJob.mock.calls[0]![0] as { diarize: boolean; speakersExpected?: number };
}

describe("capture: how many people", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", memoryStorage());
    asr.listJobs.mockReset().mockResolvedValue([]);
    asr.submitJob.mockReset().mockResolvedValue({ id: "job-9", status: "queued" });
  });

  afterEach(() => vi.unstubAllGlobals());

  it("defaults to Auto and sends no hint", async () => {
    const container = renderPage();
    expect(people().getByRole("button", { name: "Auto" })).toHaveAttribute("aria-pressed", "true");
    expect((await upload(container)).speakersExpected).toBeUndefined();
  });

  it("sends an exact number", async () => {
    const container = renderPage();
    fireEvent.click(people().getByRole("button", { name: "3" }));
    const params = await upload(container);
    expect(params.speakersExpected).toBe(3);
  });

  it("sends no hint for 6+", async () => {
    const container = renderPage();
    fireEvent.click(people().getByRole("button", { name: "6+" }));
    expect((await upload(container)).speakersExpected).toBeUndefined();
  });

  it("is off, and sends nothing, when speakers are not told apart", async () => {
    const container = renderPage();
    fireEvent.click(people().getByRole("button", { name: "2" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Tell speakers apart" }));
    expect(people().getByRole("button", { name: "2" })).toBeDisabled();
    const params = await upload(container);
    expect(params.diarize).toBe(false);
    expect(params.speakersExpected).toBeUndefined();
  });
});
