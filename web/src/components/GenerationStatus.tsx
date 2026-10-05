import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getGeneration, regenerate } from "../api/generation";
import { ApiError } from "../api/http";
import { messageFor } from "../lib/errorCopy";
import type { GenerationView } from "../api/types";
import { MAX_SHOWN_RANGES, excludedItems } from "../lib/generation";
import { useToast } from "./Toaster";

const POLL_MS = 2_000;

/** A sentence per closed-vocabulary reason. The API never sends prose. */
const REASONS: Record<string, string> = {
  budget_exceeded:
    "This workspace has used its AI budget for the month, so this note was not written up. Your recording and your own notes are untouched.",
  generation_disabled: "Automatic note writing is off for this workspace.",
  processor_unacknowledged:
    "A workspace admin has to agree to who processes your meetings before notes are written.",
  no_snapshot: "The recording could not be read when the note was written.",
  snapshot_unreadable: "The recording could not be read when the note was written.",
  model_unavailable: "The model was unavailable. Try writing the note again.",
};

/**
 * Engine status line, never a blocking overlay (generation only writes untouched sections).
 * `blocked`: no generation row will ever appear. `canGenerate`: the one place the
 * Generate Summary button lives, until a run exists. `onSeek`: opens the transcript
 * at a left-out range. `onView`: hands the latest run to the page.
 */
export function GenerationStatus({
  noteId,
  blocked,
  canGenerate,
  canRegenerate,
  onFinished,
  onSeek,
  onView,
}: {
  noteId: string;
  blocked?: "generation_disabled" | "budget_exceeded" | "processor_unacknowledged" | null;
  canGenerate?: boolean;
  canRegenerate?: boolean;
  onFinished?: () => void;
  onSeek?: (ms: number) => void;
  onView?: (view: GenerationView | null) => void;
}) {
  const toast = useToast();
  const [view, setView] = useState<GenerationView | null>(null);
  // "not asked yet" vs "asked, none": the button must not flash before the first answer.
  const [never, setNever] = useState(false);
  const [busy, setBusy] = useState(false);
  const wasLive = useRef(false);

  const load = useCallback(async () => {
    try {
      const latest = await getGeneration(noteId);
      setView(latest);
      onView?.(latest);
      // `superseded` = reset by an operator: treat as none.
      setNever(latest.status === "superseded");
    } catch (err) {
      // 404 = never generated.
      if (err instanceof ApiError && err.status === 404) setNever(true);
      else setView(null);
    }
    // onView is a notification: a new identity must not refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [noteId]);

  useEffect(() => {
    if (blocked) return;
    void load();
  }, [blocked, load]);

  const live = view?.status === "queued" || view?.status === "running";

  useEffect(() => {
    if (!live) {
      if (wasLive.current) {
        wasLive.current = false;
        onFinished?.();
      }
      return;
    }
    wasLive.current = true;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [live, load, onFinished]);

  if (blocked) {
    return (
      <p className="banner banner-warn gen-status" role="status">
        <span className="grow">
          {REASONS[blocked] ?? "This note was not written automatically."}
          {blocked === "processor_unacknowledged" && (
            <>
              {" "}
              <Link to="/settings/data">Settings › Data &amp; AI</Link>
            </>
          )}
        </span>
      </p>
    );
  }
  const again = async () => {
    setBusy(true);
    try {
      await regenerate(noteId);
      await load();
    } catch (err) {
      // Closed vocabulary first, general copy otherwise — never the detail.
      const code = err instanceof ApiError ? err.code : undefined;
      toast.error((code && REASONS[code]) || messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  if (never && canGenerate) {
    return (
      <div className="gen-empty">
        <p>Create a structured summary from this conversation.</p>
        <button className="btn primary" disabled={busy} onClick={() => void again()}>
          {busy ? "Starting…" : "Generate Summary"}
        </button>
      </div>
    );
  }
  if (!view || view.status === "superseded") return null;

  if (live) {
    const done = view.windows_done ?? 0;
    const total = view.windows_total ?? 0;
    return (
      <p className="banner banner-info gen-status" role="status" aria-live="polite">
        <span className="grow">
          Writing this note{total > 0 ? ` — ${Math.min(done, total)} of ${total} minutes read` : "…"}
        </span>
      </p>
    );
  }

  if (view.status === "failed") {
    return (
      <p className="banner banner-warn gen-status" role="status">
        <span className="grow">
          {REASONS[view.error_kind ?? ""] ?? "This note could not be written automatically."}
        </span>
        {canRegenerate && view.error_kind !== "budget_exceeded" && (
          <button className="btn sm" disabled={busy} onClick={() => void again()}>
            Try again
          </button>
        )}
      </p>
    );
  }

  if ((view.status === "complete" || view.status === "partial") && view.sections_written === 0) {
    return (
      <p className="banner banner-warn gen-status" role="status">
        <span className="grow">
          Nothing could be written from this recording: no statement in it could be verified
          against the words that were said.
        </span>
        {canRegenerate && (
          <button className="btn sm" disabled={busy} onClick={() => void again()}>
            Try again
          </button>
        )}
      </p>
    );
  }

  const excluded = <NotIncluded view={view} onSeek={onSeek} />;

  if (view.status === "partial") {
    const minutes = view.failed_ranges
      .map((range) => Math.round((range[0] ?? 0) / 60_000))
      .slice(0, 3)
      .join(", ");
    return (
      <p className="banner banner-warn gen-status" role="status">
        <span className="grow">
          Some of the recording could not be read{minutes ? ` (around minute ${minutes})` : ""}. The
          rest of the note is written from what was readable.
        </span>
        {canRegenerate && (
          <button className="btn sm" disabled={busy} onClick={() => void again()}>
            Write it again
          </button>
        )}
        {excluded}
      </p>
    );
  }

  return view.status === "complete" ? excluded : null;
}

/** "Not included: 00:45–00:52 (background speech), …", each a link into the transcript. */
function NotIncluded({
  view,
  onSeek,
}: {
  view: GenerationView;
  onSeek?: (ms: number) => void;
}) {
  const items = excludedItems(view.excluded_ranges ?? [], view.language);
  if (items.length === 0) return null;
  const shown = items.slice(0, MAX_SHOWN_RANGES);
  const more = items.length - shown.length;
  return (
    <span className="gen-excluded muted" role="note">
      Not included:{" "}
      {shown.map((item, i) => (
        <span key={`${item.startMs}-${i}`}>
          {i > 0 && ", "}
          {onSeek ? (
            <button type="button" className="link-btn" onClick={() => onSeek(item.startMs)}>
              {item.text}
            </button>
          ) : (
            item.text
          )}
        </span>
      ))}
      {more > 0 && ` +${more} more`}
    </span>
  );
}
