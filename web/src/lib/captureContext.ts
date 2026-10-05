// A calendar event's people, handed from the home page's "Start" button to
// the capture screen (Sprint 30). Names never go in the URL — only the
// event id does — so they travel through sessionStorage, keyed by that id,
// and stay in this tab.

import type { MeetingCalendarContext, UpcomingEvent } from "../api/types";

/** The server takes at most this many names, each up to 80 characters. */
export const MAX_NAME_CANDIDATES = 12;
const MAX_NAME_LEN = 80;
/** The diarizer's ceiling; an invitee count above it is sent as this. */
export const MAX_SPEAKERS = 8;

/** The most agenda points a note starts with (the server's own cap). */
export const MAX_AGENDA_LINES = 20;
const MAX_AGENDA_LINE_LEN = 160;

export interface CaptureContext {
  attendee_count: number;
  attendees: string[];
  /** Sprint 34: the agenda the server derived from the invite, and the
   *  invite's own identity — both go on the note when the capture starts. */
  agenda: string[];
  title: string;
  ical_uid: string;
}

function key(eventId: string): string {
  return `capture.ctx.${eventId}`;
}

/** A name the server will accept: trimmed, 1–80 characters, no control characters. */
function cleanName(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const name = raw.trim();
  if (!name || name.length > MAX_NAME_LEN || /[\u0000-\u001f\u007f]/.test(name)) return null;
  return name;
}

/**
 * The names to offer for speakers: the invitees minus the person capturing
 * (whose calendar this is — `self` holds their address and name as far as
 * the page knows them), cleaned and de-duplicated, at most 12.
 */
export function nameCandidates(attendees: readonly unknown[], self: ReadonlyArray<string | null | undefined> = []): string[] {
  const mine = new Set(self.filter((s): s is string => Boolean(s)).map((s) => s.trim().toLocaleLowerCase()));
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of attendees) {
    const name = cleanName(raw);
    if (!name) continue;
    const k = name.toLocaleLowerCase();
    if (mine.has(k) || seen.has(k)) continue;
    seen.add(k);
    out.push(name);
    if (out.length === MAX_NAME_CANDIDATES) break;
  }
  return out;
}

/** Keep an event's people for the capture screen. Private mode: silently not kept. */
export function saveCaptureContext(event: UpcomingEvent): void {
  const ctx: CaptureContext = {
    attendee_count: event.attendee_count,
    attendees: nameCandidates(event.attendees, [event.account_email]),
    agenda: agendaLines(event.agenda_lines),
    title: event.title,
    ical_uid: event.ical_uid,
  };
  try {
    sessionStorage.setItem(key(event.id), JSON.stringify(ctx));
  } catch {
    /* private mode / storage full: the capture just has no invitees */
  }
}

/** The people for an event id, or null when nothing (usable) was kept. */
export function readCaptureContext(eventId: string | null | undefined): CaptureContext | null {
  if (!eventId) return null;
  let raw: string | null;
  try {
    raw = sessionStorage.getItem(key(eventId));
  } catch {
    return null;
  }
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<CaptureContext> | null;
    const count = parsed?.attendee_count;
    if (typeof count !== "number" || !Number.isFinite(count) || count < 0) return null;
    return {
      attendee_count: Math.floor(count),
      attendees: nameCandidates(Array.isArray(parsed?.attendees) ? parsed.attendees : []),
      agenda: agendaLines(parsed?.agenda),
      title: typeof parsed?.title === "string" ? parsed.title : "",
      ical_uid: typeof parsed?.ical_uid === "string" ? parsed.ical_uid : "",
    };
  } catch {
    return null;
  }
}

/**
 * What a capture from this context sends: an upper bound on the speakers
 * only when at least two people were invited (never as the exact count),
 * and the invitees' names to offer when renaming.
 */
export function contextFields(ctx: CaptureContext | null): { speakersMax?: number; nameCandidates?: string[] } {
  if (!ctx) return {};
  return {
    speakersMax: ctx.attendee_count >= 2 ? Math.min(ctx.attendee_count, MAX_SPEAKERS) : undefined,
    nameCandidates: ctx.attendees.length > 0 ? ctx.attendees : undefined,
  };
}

/** Agenda lines as the note will take them: trimmed, 1–160 chars, ≤ 20. */
function agendaLines(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((line): line is string => typeof line === "string")
    .map((line) => line.trim().slice(0, MAX_AGENDA_LINE_LEN))
    .filter(Boolean)
    .slice(0, MAX_AGENDA_LINES);
}

/**
 * What `POST /v1/notes/meeting` gets from the event the capture started
 * from (Sprint 34): who was invited and what the invite said to talk
 * about. `description` is never sent from the browser — the server already
 * derived `agenda_lines` from it when it served the event.
 */
export function meetingCalendar(ctx: CaptureContext | null): MeetingCalendarContext | undefined {
  if (!ctx) return undefined;
  if (ctx.attendees.length === 0 && ctx.agenda.length === 0 && !ctx.title) return undefined;
  return {
    source: "google",
    title: ctx.title || undefined,
    ical_uid: ctx.ical_uid || undefined,
    attendee_names: ctx.attendees.length > 0 ? ctx.attendees : undefined,
    agenda_lines: ctx.agenda.length > 0 ? ctx.agenda : undefined,
  };
}
