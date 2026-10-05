// Calendar connections (note-service): Google account or iCal link, calendar picks, upcoming events.

import { api } from "./http";
import type {
  CalendarConnection,
  CalendarConnectionsResponse,
  CalendarListResponse,
  UpcomingEventsResponse,
} from "./types";

export function listCalendarConnections(): Promise<CalendarConnectionsResponse> {
  return api<CalendarConnectionsResponse>("note", "/v1/calendar/connections");
}

/** Answers Google's consent URL; the browser comes back to `returnTo` with `?calendar=connected|error`. */
export function startGoogleConnect(returnTo: string, loginHint?: string): Promise<{ authorize_url: string }> {
  return api<{ authorize_url: string }>("note", "/v1/calendar/google/connect", {
    method: "POST",
    json: { return_to: returnTo, login_hint: loginHint ?? null },
  });
}

/** Add a calendar by its private iCal address; the feed is fetched once now, so a bad link fails here. */
export function connectCalendarLink(url: string, label?: string): Promise<CalendarConnection> {
  return api<CalendarConnection>("note", "/v1/calendar/ics/connect", {
    method: "POST",
    json: { url, label: label ?? null },
  });
}

export function disconnectCalendar(connectionId: string): Promise<void> {
  return api<void>("note", `/v1/calendar/connections/${connectionId}`, { method: "DELETE" });
}

export function listCalendars(connectionId: string): Promise<CalendarListResponse> {
  return api<CalendarListResponse>("note", `/v1/calendar/connections/${connectionId}/calendars`);
}

export function setHiddenCalendars(connectionId: string, hiddenIds: string[]): Promise<CalendarConnection> {
  return api<CalendarConnection>("note", `/v1/calendar/connections/${connectionId}/calendars`, {
    method: "PUT",
    json: { hidden_calendar_ids: hiddenIds },
  });
}

export function upcomingEvents(days = 7, signal?: AbortSignal): Promise<UpcomingEventsResponse> {
  return api<UpcomingEventsResponse>("note", "/v1/calendar/events", { query: { days }, signal });
}
