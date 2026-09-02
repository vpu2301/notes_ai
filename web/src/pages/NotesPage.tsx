import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorMessage } from "../api/http";
import { searchNotes } from "../api/notes";
import type { SearchHit } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { FileTextIcon, MicIcon, PlusIcon, SearchIcon, UploadIcon, WaveformIcon } from "../components/icons";
import { SkeletonRow } from "../components/Skeleton";
import { Snippet } from "../components/Snippet";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toaster";
import { createBlankNote } from "../lib/createBlankNote";
import { relativeTime } from "../lib/time";
import { useCaptures, type Capture } from "../lib/useCaptures";
import { useDebouncedValue } from "../lib/useDebouncedValue";

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
  onCreate,
  onCancel,
  onDismiss,
}: {
  capture: Capture;
  creating: boolean;
  onCreate: () => void;
  onCancel: () => void;
  onDismiss: () => void;
}) {
  const { job, title, mine } = capture;
  const pending = job.status === "queued" || job.status === "running";
  const failed = job.status === "failed";
  const status = failed
    ? job.error_message ?? "Transcription failed"
    : job.status === "queued"
      ? "Waiting to start…"
      : job.status === "running"
        ? "Transcribing…"
        : mine || creating
          ? "Writing your note…"
          : "Transcript ready";

  return (
    <div className="row capture-row">
      <span className={`row-ico ${failed ? "rec" : "indigo"} ${pending || (mine && !failed) ? "pulse" : ""}`}>
        <WaveformIcon size={15} />
      </span>
      <div className="row-body">
        <div className="row-1">
          <span className="row-name">{title || "Untitled meeting"}</span>
        </div>
        <div className={`row-2 ${failed ? "err" : ""}`}>{status}</div>
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
        {job.status === "complete" && !mine && (
          <button className="btn primary sm" onClick={onCreate} disabled={creating}>
            {creating ? "Creating…" : "Create note"}
          </button>
        )}
      </div>
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
  const toast = useToast();
  const abortRef = useRef<AbortController | null>(null);

  const runSearch = useCallback(
    async (query: string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);
      try {
        const res = await searchNotes({ q: query, signal: controller.signal });
        setHits(res.hits);
        setNextCursor(res.next_cursor);
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
    [toast],
  );

  useEffect(() => {
    void runSearch(debouncedQ);
  }, [debouncedQ, runSearch]);

  // A meeting that just finished shows up in the list without a reload.
  const { captures, creating, createNote, cancel, dismissFailed } = useCaptures({
    onNoteReady: () => void runSearch(debouncedQ),
  });

  const loadMore = async () => {
    if (!nextCursor) return;
    setLoadingMore(true);
    try {
      const res = await searchNotes({ q: debouncedQ, cursor: nextCursor });
      setHits((prev) => [...(prev ?? []), ...res.hits]);
      setNextCursor(res.next_cursor);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setLoadingMore(false);
    }
  };

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
  const groups = useMemo(() => {
    const out: { label: string; hits: SearchHit[] }[] = [];
    for (const hit of hits ?? []) {
      const label = searching ? "Results" : dayGroup(hit.updated_at);
      const last = out[out.length - 1];
      if (last && last.label === label) last.hits.push(hit);
      else out.push({ label, hits: [hit] });
    }
    return out;
  }, [hits, searching]);

  const empty = !loading && hits !== null && hits.length === 0 && (captures?.length ?? 0) === 0;

  return (
    <div className="home">
      <div className="home-h">
        <h1>Notes</h1>
        <div className="home-actions">
          <button className="btn ghost" onClick={() => navigate("/meeting/new?mode=upload")} title="Upload a recording">
            <UploadIcon size={14} /> Upload
          </button>
          <button className="btn" onClick={() => void onBlank()} disabled={makingBlank} title="Blank note (B)">
            <PlusIcon size={14} /> {makingBlank ? "Creating…" : "Blank note"}
          </button>
          <button className="btn accent" onClick={() => navigate("/meeting/new")} title="New meeting (N)">
            <MicIcon size={14} /> New meeting
          </button>
        </div>
      </div>

      <label className="search-input home-search">
        <SearchIcon />
        <input
          type="search"
          placeholder="Search notes…"
          aria-label="Search notes"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </label>

      {captures && captures.length > 0 && (
        <section className="home-group" aria-label="In progress">
          <h2 className="home-group-h">In progress</h2>
          <div className="panel">
            {captures.map((c) => (
              <CaptureRow
                key={c.job.id}
                capture={c}
                creating={creating.has(c.job.id)}
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

      {empty && !searching && (
        <EmptyState
          icon={<MicIcon size={20} />}
          title="Record your first meeting"
          message="Press New meeting, talk, press Stop. The transcript and a written-up note appear here on their own."
          action={
            <>
              <button className="btn accent" onClick={() => navigate("/meeting/new")}>
                <MicIcon size={14} /> New meeting
              </button>
              <button className="btn" onClick={() => void onBlank()} disabled={makingBlank}>
                Blank note
              </button>
            </>
          }
        />
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
                <button key={hit.note_id} className="row click" onClick={() => navigate(`/notes/${hit.note_id}`)}>
                  <span className={`row-ico ${hit.status === "amended" ? "indigo" : ""}`}>
                    <FileTextIcon size={15} />
                  </span>
                  <span className="row-body">
                    <span className="row-1">
                      <span className="row-name">{hit.title || "Untitled note"}</span>
                      {hit.status !== "draft" && <StatusBadge status={hit.status} />}
                    </span>
                    {hit.snippet && (
                      <span className="row-2 snippet">
                        <Snippet text={hit.snippet} />
                      </span>
                    )}
                  </span>
                  <span className="row-time">{relativeTime(hit.updated_at)}</span>
                </button>
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
