import { useEffect } from "react";
import { api } from "../api/http";

/**
 * Client events for pipeline telemetry (telemetry sprint 3): what the user saw, and when.
 * Events, times and counts only — never transcript or note content. Fail-open: nothing here
 * blocks or breaks the UI; failed sends retry with backoff and are dropped after 24 h.
 */

export type ClientEventName =
  | "recording_stopped"
  | "import_submitted"
  | "upload_started"
  | "upload_finished"
  | "transcript_displayed"
  | "speaker_labels_displayed"
  | "notes_displayed"
  | "error_shown";

interface QueuedEvent {
  event_id: string;
  recording_id: string;
  client: "web";
  client_version: string;
  event: ClientEventName;
  client_wall_utc: string;
  client_monotonic_ns: number;
  attributes: Record<string, string | number | boolean>;
}

const STORAGE_KEY = "mdx.telemetry.queue";
const MAX_AGE_MS = 24 * 60 * 60 * 1000;
const MAX_QUEUE = 500;
const CLIENT_VERSION = (import.meta.env.VITE_APP_VERSION as string | undefined) ?? "web-dev";

let queue: QueuedEvent[] = load();
// Events that happen before the server has given the recording an id (stop, upload start).
let beforeRecording: Omit<QueuedEvent, "recording_id">[] = [];
// Once per (recording, event) in this page's life; the server keeps the first anyway.
const reported = new Set<string>();
let timer: ReturnType<typeof setTimeout> | null = null;
let backoffMs = 2_000;
// A send is awaiting the server; a timer firing meanwhile must not send the same batch twice.
let sending = false;

function load(): QueuedEvent[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as QueuedEvent[]) : [];
  } catch {
    return [];
  }
}

function save(): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(queue));
  } catch {
    /* private window / quota: the in-memory queue still sends */
  }
}

function make(event: ClientEventName, attributes: QueuedEvent["attributes"] = {}) {
  return {
    event_id: crypto.randomUUID(),
    client: "web" as const,
    client_version: CLIENT_VERSION,
    event,
    client_wall_utc: new Date().toISOString(),
    client_monotonic_ns: Math.round(performance.now() * 1e6),
    attributes,
  };
}

function schedule(delayMs = 1_000): void {
  if (timer !== null) return;
  timer = setTimeout(() => {
    timer = null;
    void flush();
  }, delayMs);
}

/** Send what is queued; on failure keep it and back off (2 s → 5 min). */
export async function flush(): Promise<void> {
  if (sending) return;
  const now = Date.now();
  queue = queue.filter((e) => now - Date.parse(e.client_wall_utc) < MAX_AGE_MS);
  if (queue.length === 0) return;
  const batch = queue.slice(0, 100);
  sending = true;
  try {
    await api("note", "/v1/telemetry/client-events", {
      method: "POST",
      json: { sent_at: new Date().toISOString(), events: batch },
    });
    const sent = new Set(batch.map((e) => e.event_id));
    queue = queue.filter((e) => !sent.has(e.event_id));
    backoffMs = 2_000;
    save();
    if (queue.length > 0) schedule(0);
  } catch {
    save();
    backoffMs = Math.min(backoffMs * 2, 5 * 60_000);
    schedule(backoffMs);
  } finally {
    sending = false;
  }
}

/** An event for a recording the server already knows. Once per recording and event. */
export function report(
  recordingId: string,
  event: ClientEventName,
  attributes: QueuedEvent["attributes"] = {},
): void {
  try {
    const key = `${recordingId}:${event}`;
    if (reported.has(key)) return;
    reported.add(key);
    queue.push({ ...make(event, attributes), recording_id: recordingId });
    if (queue.length > MAX_QUEUE) queue = queue.slice(-MAX_QUEUE);
    save();
    schedule();
  } catch {
    /* telemetry never breaks the page */
  }
}

/** An event before the recording has an id (Stop, an import, the upload's first byte). */
export function reportBeforeRecording(
  event: ClientEventName,
  attributes: QueuedEvent["attributes"] = {},
): void {
  try {
    beforeRecording.push(make(event, attributes));
  } catch {
    /* fail-open */
  }
}

/** The upload failed: the waiting events belong to no recording. */
export function discardBeforeRecording(): void {
  beforeRecording = [];
}

/** The server accepted the upload: tag the waiting events with the recording and send them. */
export function attachRecording(recordingId: string): void {
  const waiting = beforeRecording;
  beforeRecording = [];
  for (const e of waiting) {
    const key = `${recordingId}:${e.event}`;
    if (reported.has(key)) continue;
    reported.add(key);
    queue.push({ ...e, recording_id: recordingId });
  }
  save();
  schedule(0);
}

/**
 * Report `event` the first time `ready` is true for `recordingId` — after the render that
 * shows it (effects run after commit), once per recording even under StrictMode.
 */
export function useReportDisplayed(
  recordingId: string | null | undefined,
  event: ClientEventName,
  ready: boolean,
): void {
  useEffect(() => {
    if (recordingId && ready) report(recordingId, event);
  }, [recordingId, event, ready]);
}

/** Test hook: forget what this page reported and queued. */
export function resetTelemetryForTests(): void {
  queue = [];
  beforeRecording = [];
  reported.clear();
  if (timer !== null) clearTimeout(timer);
  timer = null;
  backoffMs = 2_000;
  sending = false;
}
