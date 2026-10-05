import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { messageFor } from "../lib/errorCopy";
import { deleteNote, searchNotes } from "../api/notes";
import type { SearchHit, SharingView } from "../api/types";
import { AccessMenu, noteAccess, withSharing } from "../components/AccessBadge";
import { useAuthOptional } from "../auth/AuthContext";
import { ComingUp } from "../components/ComingUp";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { EmptyState } from "../components/EmptyState";
import { AlertIcon, FolderIcon, LayersIcon, MicIcon, PlusIcon, SearchIcon, TrashIcon, UploadIcon, WaveformIcon } from "../components/icons";
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

/** In-progress captures shown before "Show N more" — the notes come first. */
const CAPTURES_SHOWN = 3;

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
          <button className="btn sm" onClick={onCreate} disabled={creating}>
            {creating ? "Creating…" : noteError ? "Try again" : "Create note"}
          </button>
        )}
      </div>
    </div>
  );
}

/** One list row. A div, not a button, so the ⋯ menu is not a nested button. */
function NoteRow({
  hit,
  spaceName,
  menuItems,
  onOpen,
  onAccessChange,
}: {
  hit: SearchHit;
  /** Shown as a chip when the list is not already narrowed to that space. */
  spaceName?: string;
  menuItems: MenuItem[];
  onOpen: () => void;
  onAccessChange: (view: SharingView) => void;
}) {
  const access = noteAccess(hit);
  return (
    <div
      className="row click"
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        // Only the row itself opens the note; the ⋯ button's Escape must reach the document.
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
          {hit.status === "cancelled" && <StatusBadge status={hit.status} />}
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
      {access && <AccessMenu hit={hit} access={access} onChange={onAccessChange} />}
      <span className="row-time">{relativeTime(hit.updated_at)}</span>
      <span className="row-side" onClick={(e) => e.stopPropagation()}>
        <Menu anchored items={menuItems} label={`Actions for “${hit.title || "Untitled note"}”`} />
      </span>
    </div>
  );
}

export function NotesPage() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  /** The list could not be read; the page says so in place instead of showing "nothing yet". */
  const [loadError, setLoadError] = useState<string | null>(null);
  const [makingBlank, setMakingBlank] = useState(false);
  const [allCaptures, setAllCaptures] = useState(false);
  const debouncedQ = useDebouncedValue(q, 300);
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const abortRef = useRef<AbortController | null>(null);
  const newMeetingRef = useRef<HTMLButtonElement>(null);

  // A space in the URL narrows the list to the notes filed in it.
  const { spaceId } = useParams();
  const { spaces, spaceOf, loading: spacesLoading, file, forgetNote } = useSpaces();
  /** The note the row menu asked to move to the trash, until confirmed. */
  const [pendingTrash, setPendingTrash] = useState<SearchHit | null>(null);
  const [trashing, setTrashing] = useState(false);
  const [trashError, setTrashError] = useState<string | null>(null);
  const space = spaces.find((s) => s.id === spaceId);
  // First word of a real name, never an e-mail.
  const realName = useAuthOptional()?.identity?.display_name?.trim() ?? "";
  const firstName = realName.includes("@") ? "" : realName.split(/\s+/)[0];
  useDocumentTitle(space ? space.name : "Notes");

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
      setLoadError(null);
      try {
        const limit = spaceId ? 100 : 25;
        const res = await searchNotes({ q: query, limit, signal: controller.signal });
        let page = res.hits;
        let cursor = res.next_cursor;
        // The space filter is client-side: pull more pages (bounded) so the count is honest.
        for (let i = 0; spaceId && cursor && i < SPACE_PAGES; i++) {
          const more = await searchNotes({ q: query, limit, cursor, signal: controller.signal });
          page = [...page, ...more.hits];
          cursor = more.next_cursor;
        }
        setHits(page);
        setNextCursor(cursor);
      } catch (err) {
        if (!controller.signal.aborted) {
          setHits(null);
          setNextCursor(null);
          setLoadError(messageFor(err));
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [spaceId],
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
      toast.error(messageFor(err));
    } finally {
      setLoadingMore(false);
    }
  };

  /** `/welcome` hands over focus once; the state is cleared on read so Back does not re-steal it. */
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
      toast.error(messageFor(err));
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

  /** Row ⋯ menu: "Move to …" per space (its own one unfiles), then "Move to trash". */
  const menuItems = useCallback(
    (hit: SearchHit): MenuItem[] => {
      const current = spaceOf[hit.note_id];
      const items: MenuItem[] = spaces.map((s) => ({
        label: current === s.id ? `Remove from ${s.name}` : `Move to ${s.name}`,
        icon: <FolderIcon size={14} />,
        onClick: () => void file(hit.note_id, current === s.id ? null : s.id),
      }));
      items.push({
        label: "Move to trash",
        icon: <TrashIcon size={14} />,
        sep: items.length > 0,
        danger: true,
        onClick: () => {
          setTrashError(null);
          setPendingTrash(hit);
        },
      });
      return items;
    },
    [spaces, spaceOf, file],
  );

  const onTrash = async () => {
    if (!pendingTrash) return;
    const id = pendingTrash.note_id;
    setTrashing(true);
    setTrashError(null);
    try {
      await deleteNote(id);
      forgetNote(id);
      setHits((prev) => prev?.filter((h) => h.note_id !== id) ?? prev);
      setPendingTrash(null);
      toast.success("Note moved to trash");
    } catch (err) {
      setTrashError(messageFor(err));
    } finally {
      setTrashing(false);
    }
  };

  // Captures only show on All notes, so a space is empty on its notes alone.
  const empty =
    !loading && hits !== null && visible.length === 0 && (!!spaceId || (captures?.length ?? 0) === 0);

  /** Known to hold anything; deliberately false while `hits` is null so "unknown" never renders as "empty". */
  const hasSomething = (hits?.length ?? 0) > 0 || (captures?.length ?? 0) > 0;
  const firstUse = !searching && !spaceId && !hasSomething && !loadError;

  return (
    <div className="home">
      <div className="home-top">
        <div className="home-title">
          <h1>{space ? space.name : firstName ? `${greeting()}, ${firstName}` : greeting()}</h1>
          <span className="home-sub">
            {space ? `${visible.length} ${visible.length === 1 ? "note" : "notes"}` : todayLabel()}
          </span>
        </div>
        <SearchField
          value={q}
          onChange={setQ}
          label="Search notes"
          placeholder="Search notes, transcripts and people…"
          busy={searching && loading}
          status={searching && !loading && hits ? resultCount : undefined}
        />
        {/* Named as a group so it is distinguishable from the sidebar's "New meeting". */}
        <div className="home-start" role="group" aria-label="Start a note">
          <button ref={newMeetingRef} className="btn accent" onClick={() => navigate("/meeting/new")} title="New meeting (N)">
            <MicIcon size={14} /> New meeting
          </button>
          <Menu
            anchored
            label="More ways to start"
            triggerClassName="icon-btn home-more"
            items={[
              { label: makingBlank ? "Creating…" : "Blank note", icon: <PlusIcon size={14} />, onClick: () => void onBlank(), disabled: makingBlank },
              { label: "Upload a recording", icon: <UploadIcon size={14} />, onClick: () => navigate("/meeting/new?mode=upload") },
              { label: "New from template…", icon: <LayersIcon size={14} />, onClick: () => navigate("/new") },
            ]}
          />
        </div>
      </div>

      {!searching && !spaceId && <ComingUp invite={hasSomething} />}

      {!spaceId && captures && captures.length > 0 && (
        <section className="home-group" aria-label="In progress">
          <h2 className="home-group-h">
            In progress <span className="home-group-count">{captures.length}</span>
          </h2>
          <div className="home-list">
            {(allCaptures ? captures : captures.slice(0, CAPTURES_SHOWN)).map((c) => (
              <CaptureRow
                key={c.job.id}
                capture={c}
                creating={creating.has(c.job.id)}
                noteError={noteErrors[c.job.id]}
                onCreate={() =>
                  void createNote(c.job)
                    .then((id) => navigate(`/notes/${id}`))
                    .catch((err) => toast.error(messageFor(err)))
                }
                onCancel={() => void cancel(c.job).catch((err) => toast.error(messageFor(err)))}
                onDismiss={() => dismissFailed(c.job)}
              />
            ))}
            {captures.length > CAPTURES_SHOWN && (
              <button className="home-list-more" onClick={() => setAllCaptures((v) => !v)} aria-expanded={allCaptures}>
                {allCaptures ? "Show fewer" : `Show ${captures.length - CAPTURES_SHOWN} more`}
              </button>
            )}
          </div>
        </section>
      )}

      {loading && (
        <div className="home-list" aria-busy="true" aria-label="Loading notes">
          <SkeletonRow />
          <SkeletonRow />
          <SkeletonRow />
        </div>
      )}

      {!loading && loadError && (
        <EmptyState
          icon={<AlertIcon size={20} />}
          title="Your notes could not be loaded"
          message={loadError}
          action={
            <button className="btn" onClick={() => void runSearch(debouncedQ)}>
              Try again
            </button>
          }
        />
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

      {/* First use: one sentence, one button; the blank note stays a quiet second line. */}
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
            <div className="home-list">
              {g.hits.map((hit) => (
                <NoteRow
                  key={hit.note_id}
                  hit={hit}
                  spaceName={spaceId ? undefined : spaces.find((s) => s.id === spaceOf[hit.note_id])?.name}
                  menuItems={menuItems(hit)}
                  onOpen={() => navigate(`/notes/${hit.note_id}`)}
                  onAccessChange={(view) =>
                    setHits((prev) => prev?.map((h) => (h.note_id === view.note_id ? withSharing(h, view) : h)) ?? prev)
                  }
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

      {pendingTrash && (
        <ConfirmDialog
          title="Move this note to the trash?"
          subtitle="It disappears from everyone's list and any public link stops working."
          confirmLabel="Move to trash"
          confirmDanger
          busy={trashing}
          error={trashError}
          onConfirm={() => void onTrash()}
          onCancel={() => setPendingTrash(null)}
        >
          The note is kept for the workspace's records but is no longer shown anywhere.
        </ConfirmDialog>
      )}
    </div>
  );
}
