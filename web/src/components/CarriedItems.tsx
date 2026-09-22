import { useCallback, useEffect, useState } from "react";
import { errorMessage } from "../api/http";
import { getCarried, setCarriedState } from "../api/notes";
import type { CarriedItem, CarriedView } from "../api/types";
import { useToast } from "./Toaster";

function formatDate(iso: string | null): string {
  if (!iso) return "last time";
  const when = new Date(iso);
  return Number.isNaN(when.getTime())
    ? "last time"
    : when.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/**
 * "Still open from 12 Sep" — the previous meeting's unfinished business,
 * at the top of this one.
 *
 * The items keep the PREVIOUS note's key, so ticking one here does not
 * detach it from the meeting where it was agreed, or from the
 * recipient's confirmation on that meeting's shared page.
 */
export function CarriedItems({ noteId, readOnly = false }: { noteId: string; readOnly?: boolean }) {
  const toast = useToast();
  const [view, setView] = useState<CarriedView | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setView(await getCarried(noteId));
    } catch {
      // No series, or the previous note is no longer readable. Either
      // way there is simply nothing to show.
      setView(null);
    }
  }, [noteId]);

  useEffect(() => {
    void load();
  }, [load]);

  const update = async (item: CarriedItem, state: "open" | "done_marked" | "dropped") => {
    setBusy(item.item_key);
    const before = view;
    // Optimistic: ticking a box should feel like ticking a box.
    setView((cur) =>
      cur
        ? {
            ...cur,
            items: cur.items.map((i) => (i.item_key === item.item_key ? { ...i, state } : i)),
          }
        : cur,
    );
    try {
      await setCarriedState(noteId, item.item_key, state);
    } catch (err) {
      setView(before);
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const items = (view?.items ?? []).filter((i) => i.state !== "dropped");
  if (items.length === 0) return null;

  return (
    <section className="carried" aria-label="Still open from the last meeting">
      <h3 className="carried-head">
        Still open from {formatDate(view?.from_date ?? null)}
        {view?.from_note_id && (
          <a className="link carried-source" href={`/notes/${view.from_note_id}`}>
            {view.from_note_code ?? "that meeting"}
          </a>
        )}
      </h3>
      <ul className="carried-list">
        {items.map((item) => {
          const done = item.state === "done_marked" || item.state === "done_mentioned";
          return (
            <li key={item.item_key} className={done ? "done" : ""}>
              <label className="chk-row">
                <input
                  type="checkbox"
                  className="chk"
                  checked={done}
                  disabled={readOnly || busy === item.item_key}
                  onChange={() => void update(item, done ? "open" : "done_marked")}
                />
                <span>
                  {item.owner_label && <strong>{item.owner_label}: </strong>}
                  {item.text}
                  {item.due_text && <span className="help"> — {item.due_text}</span>}
                </span>
              </label>
              {/* The recording said it was done, and these are the words. */}
              {item.state === "done_mentioned" && item.done_quote && (
                <p className="help carried-quote">
                  {item.done_speaker ? `${item.done_speaker}: ` : ""}“{item.done_quote}”
                </p>
              )}
              {!readOnly && (
                <button
                  className="btn ghost sm"
                  disabled={busy === item.item_key}
                  onClick={() => void update(item, "dropped")}
                  aria-label={`Drop ${item.text}`}
                >
                  Drop
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
