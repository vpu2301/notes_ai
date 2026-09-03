import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import * as calApi from "../api/calendar";
import { errorMessage } from "../api/http";
import type { CalendarConnection, CalendarEntry, UpcomingEvent, UpcomingEventsResponse } from "../api/types";
import { AlertIcon, CalendarClockIcon, CalendarIcon, LinkOffIcon, MicIcon, PlusIcon, RefreshIcon, VideoIcon } from "./icons";
import { Menu, type MenuItem } from "./Menu";
import { useToast } from "./Toaster";

// Google events change rarely; a refresh every few minutes, on focus, and
// after any connect/disconnect keeps the list honest without hammering.
const REFRESH_MS = 5 * 60_000;

/** Where Google sends the browser back: this page, flagged. */
function returnTo(): string {
  return `${window.location.origin}/?calendar=connected`;
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** "Today", "Tomorrow", or "Fri 4 Sep" for an event's day. */
function dayLabel(d: Date): string {
  const now = new Date();
  if (sameDay(d, now)) return "Today";
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  if (sameDay(d, tomorrow)) return "Tomorrow";
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

function timeOf(d: Date): string {
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

/** The event is on now (or, for all-day, it is that day). */
function isLive(ev: UpcomingEvent): boolean {
  const now = Date.now();
  return new Date(ev.start).getTime() <= now && new Date(ev.end).getTime() > now;
}

function EventRow({ event, onStart }: { event: UpcomingEvent; onStart: () => void }) {
  const start = new Date(event.start);
  const end = new Date(event.end);
  const today = sameDay(start, new Date());
  const live = isLive(event);
  const when = event.all_day ? "All day" : `${timeOf(start)} – ${timeOf(end)}`;
  const meta = [
    event.calendar_name,
    event.attendee_count > 0 ? `${event.attendee_count} ${event.attendee_count === 1 ? "guest" : "guests"}` : null,
    event.location && !event.location.startsWith("http") ? event.location : null,
  ].filter(Boolean);

  return (
    <div className={`row cu-row ${live ? "live" : ""}`}>
      <span className="cu-when">
        {!today && <span className="cu-day">{dayLabel(start)}</span>}
        <span className="cu-time">{live ? "Now" : when}</span>
      </span>
      <span className="cu-bar" style={{ background: event.color ?? "var(--accent)" }} aria-hidden="true" />
      <div className="row-body">
        <div className="row-1">
          <span className="row-name">{event.title}</span>
          {event.response_status === "needsAction" && <span className="chip draft">Invited</span>}
        </div>
        {meta.length > 0 && <div className="row-2">{meta.join(" · ")}</div>}
      </div>
      <div className="row-side cu-actions">
        {event.meeting_url && (
          <a className="btn ghost sm" href={event.meeting_url} target="_blank" rel="noreferrer noopener" title="Open the video call">
            <VideoIcon size={14} /> Join
          </a>
        )}
        <button className="btn primary sm" onClick={onStart} title="Start a meeting note for this event">
          <MicIcon size={13} /> Start
        </button>
      </div>
    </div>
  );
}

function CalendarPicker({
  connections,
  onChanged,
  onClose,
}: {
  connections: CalendarConnection[];
  onChanged: () => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const [lists, setLists] = useState<Record<string, CalendarEntry[] | "loading" | "error">>({});
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    for (const c of connections) {
      setLists((l) => ({ ...l, [c.id]: "loading" }));
      calApi
        .listCalendars(c.id)
        .then((res) => !cancelled && setLists((l) => ({ ...l, [c.id]: res.calendars })))
        .catch((err) => {
          if (cancelled) return;
          setLists((l) => ({ ...l, [c.id]: "error" }));
          toast.error(errorMessage(err));
        });
    }
    return () => {
      cancelled = true;
    };
  }, [connections, toast]);

  const toggle = async (conn: CalendarConnection, cal: CalendarEntry) => {
    const list = lists[conn.id];
    if (!Array.isArray(list)) return;
    const next = list.map((c) => (c.id === cal.id ? { ...c, shown: !c.shown } : c));
    setLists((l) => ({ ...l, [conn.id]: next }));
    setBusy(cal.id);
    try {
      await calApi.setHiddenCalendars(
        conn.id,
        next.filter((c) => !c.shown).map((c) => c.id),
      );
      onChanged();
    } catch (err) {
      setLists((l) => ({ ...l, [conn.id]: list }));
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="Choose calendars">
        <div className="modal-h">
          <h2>Choose calendars</h2>
          <p>Which calendars feed the Coming up list.</p>
        </div>
        <div className="modal-b cu-picker">
          {connections.map((conn) => {
            const list = lists[conn.id];
            return (
              <section key={conn.id} className="cu-picker-account" aria-label={conn.account_email}>
                <h3>{conn.account_email}</h3>
                {list === "loading" && <p className="cu-picker-note">Loading calendars…</p>}
                {list === "error" && <p className="cu-picker-note">Couldn't load this account's calendars.</p>}
                {Array.isArray(list) &&
                  list.map((cal) => (
                    <label key={cal.id} className="chk-row cu-picker-row">
                      <input
                        type="checkbox"
                        className="chk"
                        checked={cal.shown}
                        disabled={busy === cal.id}
                        onChange={() => void toggle(conn, cal)}
                      />
                      <span className="cu-dot" style={{ background: cal.color ?? "var(--accent)" }} aria-hidden="true" />
                      <span className="grow">{cal.name}</span>
                      {cal.primary && <span className="chip draft">Primary</span>}
                    </label>
                  ))}
              </section>
            );
          })}
        </div>
        <div className="modal-f">
          <button className="btn primary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Paste a calendar's private iCal address: the way in that needs no
 * Google client on the server (and works for Outlook / iCloud too). The
 * server fetches the feed before answering, so a wrong link fails here.
 */
function CalendarLinkDialog({
  onAdded,
  onClose,
}: {
  onAdded: (connection: CalendarConnection) => void;
  onClose: () => void;
}) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const valid = /^(https?|webcal):\/\/\S+$/i.test(url.trim());

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      onAdded(await calApi.connectCalendarLink(url.trim()));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="modal" role="dialog" aria-modal="true" aria-label="Add a calendar link" onSubmit={(e) => void submit(e)}>
        <div className="modal-h">
          <h2>Add a calendar link</h2>
          <p>Paste the calendar's private iCal address. No Google sign-in needed.</p>
        </div>
        <div className="modal-b">
          <div className="field">
            <input
              ref={inputRef}
              className="input mono"
              type="text"
              inputMode="url"
              placeholder="https://calendar.google.com/calendar/ical/…/basic.ics"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={busy}
              spellCheck={false}
              autoComplete="off"
            />
            <span className="help">
              Google Calendar: Settings → your calendar → <b>Integrate calendar</b> → <b>Secret address in iCal format</b>.
              Published Outlook and iCloud calendar links work too.
            </span>
          </div>
          {error && (
            <div className="banner banner-danger" role="alert">
              <AlertIcon size={15} />
              <span className="grow">{error}</span>
            </div>
          )}
        </div>
        <div className="modal-f">
          <button type="button" className="btn ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={!valid || busy}>
            {busy ? "Checking…" : "Add calendar"}
          </button>
        </div>
      </form>
    </div>
  );
}

/**
 * The home page's "Coming up" card: today's date, then the next days'
 * events from the user's connected calendars — a Google account or a
 * calendar link — or a one-button invitation to connect one. Start a
 * meeting note from any event.
 */
export function ComingUp() {
  const navigate = useNavigate();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<UpcomingEventsResponse | null>(null);
  const [connections, setConnections] = useState<CalendarConnection[]>([]);
  const [available, setAvailable] = useState<boolean | null>(null);
  // 0020: the server takes calendar links (false until it says so).
  const [linkAvailable, setLinkAvailable] = useState(false);
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [picking, setPicking] = useState(false);
  const [linking, setLinking] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async (quiet = false) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    if (!quiet) setLoading(true);
    try {
      const [conns, events] = await Promise.all([
        calApi.listCalendarConnections(),
        calApi.upcomingEvents(7, controller.signal),
      ]);
      if (controller.signal.aborted) return;
      setConnections(conns.connections);
      setAvailable(conns.available);
      setLinkAvailable(conns.link_available === true);
      setData(events);
    } catch (err) {
      if (controller.signal.aborted) return;
      // A missing backend route or a down service hides the card rather
      // than filling the home page with an error the user cannot act on.
      if (available === null) setAvailable(false);
      if (!quiet) toast.error(errorMessage(err));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Back from Google: say how it went, tidy the URL, reload.
  useEffect(() => {
    const outcome = params.get("calendar");
    if (!outcome) return;
    if (outcome === "connected") toast.success("Google Calendar connected.");
    else {
      const reason = params.get("reason") ?? "";
      toast.error(
        reason === "access_denied"
          ? "Google sign-in was cancelled."
          : reason === "no_refresh_token"
            ? "Google did not grant offline access. Try again and approve every permission."
            : `Couldn't connect Google Calendar${reason ? ` (${reason})` : ""}.`,
      );
    }
    const next = new URLSearchParams(params);
    next.delete("calendar");
    next.delete("reason");
    next.delete("connection_id");
    setParams(next, { replace: true });
  }, [params, setParams, toast]);

  useEffect(() => {
    void refresh();
    const t = window.setInterval(() => void refresh(true), REFRESH_MS);
    const onFocus = () => document.visibilityState === "visible" && void refresh(true);
    document.addEventListener("visibilitychange", onFocus);
    return () => {
      window.clearInterval(t);
      document.removeEventListener("visibilitychange", onFocus);
      abortRef.current?.abort();
    };
  }, [refresh]);

  const connect = async (loginHint?: string) => {
    setConnecting(true);
    try {
      const { authorize_url } = await calApi.startGoogleConnect(returnTo(), loginHint);
      window.location.assign(authorize_url);
    } catch (err) {
      toast.error(errorMessage(err));
      setConnecting(false);
    }
  };

  const linkAdded = (conn: CalendarConnection) => {
    setLinking(false);
    toast.success(`Added ${conn.account_email}.`);
    void refresh(true);
  };

  const disconnect = async (conn: CalendarConnection) => {
    try {
      await calApi.disconnectCalendar(conn.id);
      toast.success(conn.provider === "ics" ? `Removed ${conn.account_email}.` : `Disconnected ${conn.account_email}.`);
      void refresh(true);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const start = (ev: UpcomingEvent) => navigate(`/meeting/new?title=${encodeURIComponent(ev.title)}`);

  const menu = useMemo<MenuItem[]>(() => {
    const items: MenuItem[] = [];
    if (connections.length > 0) {
      items.push({ label: "Choose calendars…", icon: <CalendarIcon size={14} />, onClick: () => setPicking(true) });
      items.push({ label: "Refresh", icon: <RefreshIcon size={14} />, onClick: () => void refresh() });
    }
    if (available) {
      items.push({
        label: connections.length > 0 ? "Connect another Google account" : "Connect Google Calendar",
        icon: <PlusIcon size={14} />,
        onClick: () => void connect(),
        sep: connections.length > 0,
      });
    }
    if (linkAvailable) {
      items.push({
        label: "Add calendar link…",
        icon: <PlusIcon size={14} />,
        onClick: () => setLinking(true),
        sep: !available && connections.length > 0,
      });
    }
    connections.forEach((c, i) => {
      items.push({
        label: c.provider === "ics" ? `Remove ${c.account_email}` : `Disconnect ${c.account_email}`,
        icon: <LinkOffIcon size={14} />,
        danger: true,
        sep: i === 0,
        onClick: () => void disconnect(c),
      });
    });
    return items;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connections, available, linkAvailable]);

  // No way to connect anything and nothing connected: nothing to show.
  if (available === false && !linkAvailable && connections.length === 0) return null;

  const now = new Date();
  const connected = connections.length > 0;
  const events = data?.events ?? [];
  const problems = data?.problems ?? [];

  return (
    <section className="home-group" aria-label="Coming up">
      <div className="cu-head">
        <h2 className="home-group-h">Coming up</h2>
        {menu.length > 0 && <Menu items={menu} label="Calendar options" />}
      </div>
      <div className="cu-card">
        <div className="cu-date" aria-label={now.toLocaleDateString(undefined, { dateStyle: "full" })}>
          <span className="cu-date-day">{now.getDate()}</span>
          <span className="cu-date-month">
            {now.toLocaleDateString(undefined, { month: "long" })} <span className="cu-date-dot" aria-hidden="true" />
          </span>
          <span className="cu-date-wd">{now.toLocaleDateString(undefined, { weekday: "short" })}</span>
        </div>
        <div className="cu-body">
          {problems.map((p) => (
            <div key={p.connection_id} className="cu-problem" role="status">
              <span className="grow">
                {p.needs_reauth ? `Google asked to sign in again for ${p.account_email}.` : `${p.account_email}: ${p.message}`}
              </span>
              {p.needs_reauth && (
                <button className="btn sm" onClick={() => void connect(p.account_email)} disabled={connecting}>
                  Sign in again
                </button>
              )}
            </div>
          ))}
          {loading && !data ? (
            <div className="cu-empty" aria-busy="true">
              <span className="cu-empty-text">Loading…</span>
            </div>
          ) : !connected ? (
            <div className="cu-empty">
              <CalendarClockIcon size={30} />
              <span className="cu-empty-text">See your next meetings here and start a note from one.</span>
              <div className="cu-empty-actions">
                {available !== false && (
                  <button className="btn primary" onClick={() => void connect()} disabled={connecting}>
                    {connecting ? "Opening Google…" : "Connect Google Calendar"}
                  </button>
                )}
                {linkAvailable && (
                  <button className={`btn ${available === false ? "primary" : ""}`} onClick={() => setLinking(true)}>
                    Add calendar link
                  </button>
                )}
              </div>
            </div>
          ) : events.length === 0 ? (
            <div className="cu-empty">
              <CalendarClockIcon size={30} />
              <span className="cu-empty-text">No upcoming events</span>
            </div>
          ) : (
            <div className="panel cu-list">
              {events.map((ev) => (
                <EventRow key={`${ev.connection_id}:${ev.calendar_id}:${ev.id}`} event={ev} onStart={() => start(ev)} />
              ))}
            </div>
          )}
        </div>
      </div>
      {picking && <CalendarPicker connections={connections} onChanged={() => void refresh(true)} onClose={() => setPicking(false)} />}
      {linking && <CalendarLinkDialog onAdded={linkAdded} onClose={() => setLinking(false)} />}
    </section>
  );
}
