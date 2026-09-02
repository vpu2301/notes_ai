import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errorMessage } from "../api/http";
import { searchNotes } from "../api/notes";
import type { SearchHit } from "../api/types";
import { EmptyState } from "../components/EmptyState";
import { NotesIcon, SearchIcon } from "../components/icons";
import { SkeletonCard } from "../components/Skeleton";
import { Snippet } from "../components/Snippet";
import { StatusBadge } from "../components/StatusBadge";
import { useToast } from "../components/Toaster";
import { relativeTime } from "../lib/time";
import { useDebouncedValue } from "../lib/useDebouncedValue";

const STATUS_FILTERS = ["draft", "finalized", "amended"] as const;

export function NotesPage() {
  const [q, setQ] = useState("");
  const [statuses, setStatuses] = useState<string[]>([]);
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const debouncedQ = useDebouncedValue(q, 300);
  const navigate = useNavigate();
  const toast = useToast();
  const abortRef = useRef<AbortController | null>(null);

  const runSearch = useCallback(
    async (query: string, statusFilter: string[]) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);
      try {
        const res = await searchNotes({
          q: query,
          status: statusFilter,
          signal: controller.signal,
        });
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
    void runSearch(debouncedQ, statuses);
  }, [debouncedQ, statuses, runSearch]);

  const loadMore = async () => {
    if (!nextCursor) return;
    setLoadingMore(true);
    try {
      const res = await searchNotes({ q: debouncedQ, status: statuses, cursor: nextCursor });
      setHits((prev) => [...(prev ?? []), ...res.hits]);
      setNextCursor(res.next_cursor);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setLoadingMore(false);
    }
  };

  const toggleStatus = (s: string) => {
    setStatuses((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));
  };

  const filtered = q.trim() !== "" || statuses.length > 0;

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">Notes</h1>
          <p className="page-sub">Everything your team has written down.</p>
        </div>
        <Link to="/new" className="btn btn-primary" style={{ textDecoration: "none" }}>
          New note
        </Link>
      </div>

      <div className="search-row">
        <div className="search-box">
          <SearchIcon />
          <input
            className="input"
            type="search"
            placeholder="Search notes…"
            aria-label="Search notes"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <div className="chip-row" role="group" aria-label="Filter by status">
          {STATUS_FILTERS.map((s) => (
            <button
              key={s}
              className="chip"
              aria-pressed={statuses.includes(s)}
              onClick={() => toggleStatus(s)}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="note-list" aria-busy="true" aria-label="Loading notes">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {!loading && hits !== null && hits.length === 0 && !filtered && (
        <div className="card">
          <EmptyState
            icon={<NotesIcon size={26} />}
            title="No notes yet"
            message="Create your first note from a template, or capture a meeting and let the transcript write it for you."
            action={
              <span style={{ display: "inline-flex", gap: "var(--s-2)" }}>
                <Link to="/new" className="btn btn-primary" style={{ textDecoration: "none" }}>
                  New note
                </Link>
                <Link to="/capture" className="btn" style={{ textDecoration: "none" }}>
                  Capture audio
                </Link>
              </span>
            }
          />
        </div>
      )}

      {!loading && hits !== null && hits.length === 0 && filtered && (
        <div className="card">
          <EmptyState
            icon={<SearchIcon size={26} />}
            title="Nothing matches"
            message="Try different keywords, or clear the status filters to widen the search."
            action={
              <button
                className="btn"
                onClick={() => {
                  setQ("");
                  setStatuses([]);
                }}
              >
                Clear filters
              </button>
            }
          />
        </div>
      )}

      {!loading && hits !== null && hits.length > 0 && (
        <div className="note-list">
          {hits.map((hit) => (
            <button
              key={hit.note_id}
              className="card card-hover note-card"
              onClick={() => navigate(`/notes/${hit.note_id}`)}
            >
              <div className="row1">
                <span className="title">{hit.title || "Untitled note"}</span>
                <StatusBadge status={hit.status} />
              </div>
              {hit.snippet && (
                <p className="snippet">
                  <Snippet text={hit.snippet} />
                </p>
              )}
              <div className="meta">
                <span className="code-tag">{hit.code}</span>
                <span>Updated {relativeTime(hit.updated_at)}</span>
              </div>
            </button>
          ))}
          {nextCursor && (
            <div className="center-row">
              <button className="btn" onClick={() => void loadMore()} disabled={loadingMore}>
                {loadingMore ? "Loading…" : "Load more"}
              </button>
            </div>
          )}
        </div>
      )}
    </>
  );
}
