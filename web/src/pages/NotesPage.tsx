import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { errorMessage } from "../api/http";
import { searchNotes } from "../api/notes";
import type { SearchHit } from "../api/types";
import { AccessBadge, noteAccess } from "../components/AccessBadge";
import { ComingUp } from "../components/ComingUp";
import { EmptyState } from "../components/EmptyState";
import { FolderIcon, MicIcon, PlusIcon, SearchIcon, UploadIcon, WaveformIcon } from "../components/icons";
import { Menu, type MenuItem } from "../components/Menu";
import { SearchField } from "../components/SearchField";
import { SkeletonRow } from "../components/Skeleton";
import { Snippet } from "../components/Snippet";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toaster";
import { createBlankNote } from "../lib/createBlankNote";
import { relativeTime } from "../lib/time";
import { useCaptures, type Capture } from "../lib/useCaptures";
import { useDebouncedValue } from "../lib/useDebouncedValue";
import { useSpaces } from "../spaces/SpacesContext";

/** Extra pages to pull through when a space narrows the list client-side. */
const SPACE_PAGES = 4;

/** The home greeting, by hour — as the Mac app's header. */
function greeting(): string {
  const h = new Date().getHours();
  if (h >= 5 && h < 12) return "Good morning";
  if (h >= 12 && h < 18) return "Good afternoon";
  return "Good evening";
}

/** "Wednesday, 2 September" under the greeting. */
function todayLabel(): string {
  return new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}

/** "Today" / "Yesterday" / … for the list's day groups. */
function dayGroup(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Earlier";
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((start(new Date()) - start(d)) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return "This week";
  if (days < 30) return "This month";
  return "Earlier";
}

function CaptureRow({
  capture,
  creating,
  noteError,
  onCreate,
  onCancel,
  onDismiss,
}: {
  capture: Capture;
  creating: boolean;
  /** The automatic note write failed; the row offers a retry. */
  noteError?: string;
  onCreate: () => void;
  onCancel: () => void;
  onDismiss: () => void;
}) {
  const { job, title, mine } = capture;
  const pending = job.status === "queued" || job.status === "running";
  const failed = job.status === "failed";
  const status = failed
    ? job.error_message ?? "Transcription failed"
    : noteError && !creating
      ? noteError
      : job.status === "queued"
      ? "Waiting to start…"
      : job.status === "running"
        ? "Transcribing…"
        : mine || creating
          ? "Writing your note…"
          : "Transcript ready";

  return (
    <div className="row capture-row">
      <span className={`row-ico ${failed ? "rec" : "indigo"} ${pending || (mine && !failed && !noteError) ? "pulse" : ""}`}>
        <WaveformIcon size={15} />
      </span>
      <div className="row-body">
        <div className="row-1">
          <span className="row-name">{title || "Untitled meeting"}</span>
        </div>
        <div className={`row-2 ${failed || (noteError && !creating) ? "err" : ""}`}>{status}</div>
      </div>
      <div className="row-side">
        {pending && (
          <button className="btn ghost sm" onClick={onCancel}>
            Cancel
          </button>
        )}
        {failed && (
          <button className="btn ghost sm" onClick={onDismiss}>
            Dismiss
          </button>
        )}
        {job.status === "complete" && (!mine || noteError) && (
          <button className="btn primary sm" onClick={onCreate} disabled={creating}>
            {creating ? "Creating…" : noteError ? "Try again" : "Create note"}
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * One note in the list. A div, not a button, so the ⋯ menu can live inside
 * the row without nesting one button in another.
 */
function NoteRow({
  hit,
  spaceName,
  moveItems,
  onOpen,
}: {
  hit: SearchHit;
  /** Shown as a chip when the list is not already narrowed to that space. */
  spaceName?: string;
  moveItems: MenuItem[];
  onOpen: () => void;
}) {
  const access = noteAccess(hit);
  return (
    <div
      className="row click"
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        // Only the row itself opens the note — not the ⋯ button inside it,
        // whose Escape has to reach the document to close the menu.
        if (e.target !== e.currentTarget) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
    >
      <span className="row-body">
        <span className="row-1">
          <span className="row-name">{hit.title || "Untitled note"}</span>
          {hit.status !== "draft" && <StatusBadge status={hit.status} />}
          {spaceName && (
            <span className="chip space-chip">
              <FolderIcon size={11} /> {spaceName}
            </span>
          )}
        </span>
        {hit.snippet && (
          <span className="row-2 snippet">
            <Snippet text={hit.snippet} />
          </span>
        )}
      </span>
      {access && <AccessBadge access={access} />}
      <span className="row-time">{relativeTime(hit.updated_at)}</span>
      {moveItems.length > 0 && (
        <span className="row-side" onClick={(e) => e.stopPropagation()}>
          <Menu anchored items={moveItems} label={`Move “${hit.title || "Untitled note"}”`} />
        </span>
      )}
    </div>
  );
}

export function NotesPage() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [makingBlank, setMakingBlank] = useState(false);
  const debouncedQ = useDebouncedValue(q, 300);
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const abortRef = useRef<AbortController | null>(null);
  const newMeetingRef = useRef<HTMLButtonElement>(null);

  // A space in the URL narrows the list to the notes filed in it.
  const { spaceId } = useParams();
  const { spaces, spaceOf, loading: spacesLoading, file } = useSpaces();
  const space = spaces.find((s) => s.id === spaceId);

  // The space was deleted (here or on another device) — fall back to all notes.
  useEffect(() => {
    if (spaceId && !spacesLoading && !space) navigate("/", { replace: true });
  }, [spaceId, spacesLoading, space, navigate]);

  const runSearch = useCallback(
    async (query: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);
      try {
        const limit = spaceId ? 100 : 25;
        const res = await searchNotes({ q: query, limit, signal: controller.signal });
        let page = res.hits;
        let cursor = res.next_cursor;
        // The space filter runs on the client, so a space's notes could be
        // sitting behind the first page. Pull the rest (bounded) so the count
        // in the header and "nothing here yet" tell the truth.
        for (let i = 0; spaceId && cursor && i < SPACE_PAGES; i++) {
          const more = await searchNotes({ q: query, limit, cursor, signal: controller.signal });
          page = [...page, ...more.hits];
          cursor = more.next_cursor;
        }
        setHits(page);
        setNextCursor(cursor);
      } catch (err) {
        if (!controller.signal.aborted) {
          setHits([]);
          setNextCursor(null);
          toast.error(errorMessage(err));
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [toast, spaceId],
  );

  useEffect(() => {
    void runSearch(debouncedQ);
  }, [debouncedQ, runSearch]);

  // A meeting that just finished shows up in the list without a reload.
  const { captures, creating, noteErrors, createNote, cancel, dismissFailed } = useCaptures({
    onNoteReady: () => void runSearch(debouncedQ),
  });

  const loadMore = async () => {
    if (!nextCursor) return;
    setLoadingMore(true);
    try {
      const res = await searchNotes({ q: debouncedQ, limit: spaceId ? 100 : 25, cursor: nextCursor });
      setHits((prev) => [...(prev ?? []), ...res.hits]);
      setNextCursor(res.next_cursor);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setLoadingMore(false);
    }
  };

  /**
   * `/welcome` sends people here with the caret owed to the recorder.
   *
   * The state is cleared as it is read: this is a handover for one
   * navigation, and leaving it on the entry would re-steal focus every
   * time the browser's Back button returned to this page — from a note the
   * person was reading, which is exactly where they wanted to be.
   */
  useEffect(() => {
    if (!(location.state as { focusNewMeeting?: boolean } | null)?.focusNewMeeting) return;
    newMeetingRef.current?.focus();
    navigate(location.pathname, { replace: true, state: null });
  }, [location.state, location.pathname, navigate]);

  const onBlank = async () => {
    setMakingBlank(true);
    try {
      navigate(`/notes/${await createBlankNote()}`);
    } catch (err) {
      toast.error(errorMessage(err));
      setMakingBlank(false);
    }
  };

  const searching = q.trim() !== "";
  /** The search results, narrowed to the space the sidebar has selected. */
  const visible = useMemo(
    () => (spaceId ? (hits ?? []).filter((h) => spaceOf[h.note_id] === spaceId) : hits ?? []),
    [hits, spaceId, spaceOf],
  );
  /** "12 results" beside the caret; a cursor means there are more behind it. */
  const resultCount =
    hits === null
      ? undefined
      : `${visible.length}${nextCursor ? "+" : ""} ${visible.length === 1 ? "result" : "results"}`;
  const groups = useMemo(() => {
    const out: { label: string; hits: SearchHit[] }[] = [];
    for (const hit of visible) {
      const label = searching ? "Results" : dayGroup(hit.updated_at);
      const last = out[out.length - 1];
      if (last && last.label === label) last.hits.push(hit);
      else out.push({ label, hits: [hit] });
    }
    return out;
  }, [visible, searching]);

  /** "Move to …" for every space, the note's own one unfiling it again. */
  const moveItems = useCallback(
    (noteId: string): MenuItem[] => {
      const current = spaceOf[noteId];
      return spaces.map((s) => ({
        label: current === s.id ? `Remove from ${s.name}` : `Move to ${s.name}`,
        icon: <FolderIcon size={14} />,
        onClick: () => void file(noteId, current === s.id ? null : s.id),
      }));
    },
    [spaces, spaceOf, file],
  );

  // Captures only show on All notes, so a space is empty on its notes alone.
  const empty =
    !loading && hits !== null && visible.length === 0 && (!!spaceId || (captures?.length ?? 0) === 0);

  /**
   * Whether this workspace is known to hold anything at all.
   *
   * Deliberately false while `hits` is null, i.e. while the search is still
   * in flight: "we don't know yet" must not render as "there is nothing",
   * or the calendar invitation flashes up and vanishes on the one page load
   * where that is most jarring.
   *
   * `firstUse` narrows it to the case the panel below answers. On `/` it
   * coincides with `empty` — an empty all-notes list with no captures is by
   * definition a workspace with nothing in it — but the two ask different
   * questions, and `hasSomething` is the one `<ComingUp>` needs, because it
   * has to be right *before* the list has loaded.
   */
  const hasSomething = (hits?.length ?? 0) > 0 || (captures?.length ?? 0) > 0;
  const firstUse = !searching && !spaceId && !hasSomething;

  return (
    <div className="home">
      <div className="home-h">
        <div>
          <h1>{space ? space.name : greeting()}</h1>
          <div className="home-date">
            {space
              ? `${visible.length} ${visible.length === 1 ? "note" : "notes"} in ${space.name}`
              : todayLabel()}
          </div>
        </div>
        {/* Named as a group: the sidebar carries its own "New meeting", and
            without this the two are indistinguishable to a screen reader
            moving by landmark — and to anything else asking for "the New
            meeting button on this page". */}
        <div className="home-actions" role="group" aria-label="Start a note">
          <button className="btn ghost" onClick={() => navigate("/meeting/new?mode=upload")} title="Upload a recording">
            <UploadIcon size={14} /> Upload
          </button>
          <button className="btn" onClick={() => void onBlank()} disabled={makingBlank} title="Blank note (B)">
            <PlusIcon size={14} /> {makingBlank ? "Creating…" : "Blank note"}
          </button>
          <button
            ref={newMeetingRef}
            className="btn accent"
            onClick={() => navigate("/meeting/new")}
            title="New meeting (N)"
          >
            <MicIcon size={14} /> New meeting
          </button>
        </div>
      </div>

      <div className="home-search">
        <SearchField
          value={q}
          onChange={setQ}
          label="Search notes"
          placeholder="Search notes, transcripts and people…"
          busy={searching && loading}
          status={searching && !loading && hits ? resultCount : undefined}
        />
      </div>

      {!searching && !spaceId && <ComingUp invite={hasSomething} />}

      {!spaceId && captures && captures.length > 0 && (
        <section className="home-group" aria-label="In progress">
          <h2 className="home-group-h">In progress</h2>
          <div className="panel">
            {captures.map((c) => (
              <CaptureRow
                key={c.job.id}
                capture={c}
                creating={creating.has(c.job.id)}
                noteError={noteErrors[c.job.id]}
                onCreate={() =>
                  void createNote(c.job)
                    .then((id) => navigate(`/notes/${id}`))
                    .catch((err) => toast.error(errorMessage(err)))
                }
                onCancel={() => void cancel(c.job).catch((err) => toast.error(errorMessage(err)))}
                onDismiss={() => dismissFailed(c.job)}
              />
            ))}
          </div>
        </section>
      )}

      {loading && (
        <div className="panel" aria-busy="true" aria-label="Loading notes">
          <SkeletonRow />
          <SkeletonRow />
          <SkeletonRow />
        </div>
      )}

      {empty && !searching && spaceId && (
        <EmptyState
          icon={<FolderIcon size={20} />}
          title="Nothing in this space yet"
          message="Use “Move to …” in a note's ⋯ menu to file it here."
          action={
            <button className="btn" onClick={() => navigate("/")}>
              All notes
            </button>
          }
        />
      )}

      {/* First use. One sentence and one button — not a list with nothing
          in it, and not a tour. The whole product is "press record and
          talk", so the screen that introduces it should be readable in the
          time it takes to decide to try. The blank note stays a quiet
          second line rather than a matching button: offering two equal
          choices here is how a one-click product becomes a menu. */}
      {empty && firstUse && (
        <section className="first-use" aria-label="Get started">
          <span className="first-use-art" aria-hidden="true">
            <MicIcon size={22} />
          </span>
          <p className="first-use-line">
            Press <strong>New meeting</strong>, talk, press Stop — the transcript and a written-up
            note land here on their own.
          </p>
          <button className="btn accent lg" onClick={() => navigate("/meeting/new")}>
            <MicIcon size={15} /> New meeting
          </button>
          <p className="first-use-alt">
            or{" "}
            <button className="link-btn" onClick={() => void onBlank()} disabled={makingBlank}>
              {makingBlank ? "creating…" : "start a blank note"}
            </button>
          </p>
        </section>
      )}

      {empty && searching && (
        <EmptyState
          icon={<SearchIcon size={20} />}
          title="Nothing matches"
          message="Try different keywords."
          action={
            <button className="btn" onClick={() => setQ("")}>
              Clear search
            </button>
          }
        />
      )}

      {!loading &&
        groups.map((g) => (
          <section key={g.label} className="home-group" aria-label={g.label}>
            <h2 className="home-group-h">{g.label}</h2>
            <div className="panel">
              {g.hits.map((hit) => (
                <NoteRow
                  key={hit.note_id}
                  hit={hit}
                  spaceName={spaceId ? undefined : spaces.find((s) => s.id === spaceOf[hit.note_id])?.name}
                  moveItems={moveItems(hit.note_id)}
                  onOpen={() => navigate(`/notes/${hit.note_id}`)}
                />
              ))}
            </div>
          </section>
        ))}

      {!loading && nextCursor && (
        <div className="center-row">
          <button className="btn sm" onClick={() => void loadMore()} disabled={loadingMore}>
            {loadingMore ? "Loading…" : "Show more"}
          </button>
        </div>
      )}
    </div>
  );
}
