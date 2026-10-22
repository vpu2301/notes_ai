import { render } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sent: Array<{ sent_at: string; events: Array<Record<string, unknown>> }> = [];
let failNext = 0;

vi.mock("../src/api/http", () => ({
  api: vi.fn(async (_base: string, _path: string, opts: { json: never }) => {
    if (failNext > 0) {
      failNext -= 1;
      throw new Error("offline");
    }
    sent.push(opts.json);
    return { accepted: 1, duplicates: 0, unresolved: 0 };
  }),
}));

import {
  attachRecording,
  discardBeforeRecording,
  flush,
  report,
  reportBeforeRecording,
  resetTelemetryForTests,
  useReportDisplayed,
} from "../src/lib/telemetry";

function Shown({ id, ready }: { id: string; ready: boolean }) {
  useReportDisplayed(id, "transcript_displayed", ready);
  return <p>{ready ? "transcript" : "loading"}</p>;
}

const events = () => sent.flatMap((b) => b.events);

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

describe("client telemetry", () => {
  beforeEach(() => {
    sent.length = 0;
    failNext = 0;
    vi.stubGlobal("localStorage", memoryStorage());
    resetTelemetryForTests();
  });
  afterEach(() => resetTelemetryForTests());

  it("reports a display once per recording, even under StrictMode and re-renders", async () => {
    const view = render(
      <StrictMode>
        <Shown id="job-1" ready={false} />
      </StrictMode>,
    );
    await flush();
    expect(events()).toHaveLength(0); // not yet shown
    view.rerender(
      <StrictMode>
        <Shown id="job-1" ready />
      </StrictMode>,
    );
    view.rerender(
      <StrictMode>
        <Shown id="job-1" ready />
      </StrictMode>,
    );
    await flush();
    expect(events().map((e) => [e.recording_id, e.event])).toEqual([["job-1", "transcript_displayed"]]);
    expect(events()[0]?.client).toBe("web");
  });

  it("tags events from before the upload with the recording the server returns", async () => {
    reportBeforeRecording("recording_stopped");
    reportBeforeRecording("upload_started", { bytes: 1024 });
    reportBeforeRecording("upload_finished", { bytes: 1024, retries: 0 });
    attachRecording("job-2");
    await flush();
    expect(events().map((e) => [e.recording_id, e.event])).toEqual([
      ["job-2", "recording_stopped"],
      ["job-2", "upload_started"],
      ["job-2", "upload_finished"],
    ]);
    expect(events()[1]?.attributes).toEqual({ bytes: 1024 });
    expect(sent[0]?.sent_at).toBeTruthy(); // the server measures the clock offset against it
  });

  it("drops the waiting events when the upload failed", async () => {
    reportBeforeRecording("recording_stopped");
    discardBeforeRecording();
    attachRecording("job-3");
    await flush();
    expect(events()).toHaveLength(0);
  });

  it("keeps events when the send fails and delivers them on the next try", async () => {
    failNext = 1;
    report("job-4", "notes_displayed");
    await flush(); // fails: kept
    expect(events()).toHaveLength(0);
    await flush();
    expect(events().map((e) => e.event)).toEqual(["notes_displayed"]);
  });

  it("drops events older than 24 hours", async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-10-20T10:00:00Z"));
      failNext = 1;
      report("job-5", "notes_displayed");
      await flush();
      vi.setSystemTime(new Date("2026-10-21T10:00:01Z"));
      await flush();
      expect(events()).toHaveLength(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
