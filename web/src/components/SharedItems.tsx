import { useState, type FormEvent } from "react";
import { ApiError, errorMessage } from "../api/http";
import { flagSection, respondToItem, unflagSection, withdrawItemResponse } from "../api/notes";
import type { SharedItem } from "../api/types";
import { CheckIcon, CloseIcon } from "./icons";

const MAX_COMMENT = 280;

function tooMany(err: unknown): boolean {
  return err instanceof ApiError && err.status === 429;
}

function friendly(err: unknown): string {
  return tooMany(err) ? "Too many actions — try again in a minute." : errorMessage(err);
}

/** A 280-character "what's different?" box. Plain text in, plain text out. */
function CommentBox({
  label,
  onSubmit,
  onCancel,
  busy,
}: {
  label: string;
  onSubmit: (comment: string) => void;
  onCancel: () => void;
  busy: boolean;
}) {
  const [text, setText] = useState("");
  const over = text.length > MAX_COMMENT;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (over) return;
    onSubmit(text.trim());
  };
  return (
    <form className="shared-comment" onSubmit={submit}>
      <label className="field">
        <span className="label">{label}</span>
        <textarea
          className="textarea"
          rows={2}
          maxLength={MAX_COMMENT + 20}
          value={text}
          autoFocus
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
      <div className="row-actions">
        <button className="btn primary sm" type="submit" disabled={busy || over}>
          Send
        </button>
        <button className="btn ghost sm" type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <span className={`help grow right ${over ? "danger-text" : ""}`}>
          {text.length}/{MAX_COMMENT}
        </span>
      </div>
    </form>
  );
}

/**
 * "Who does what" on the shared page (Sprint 20). Each line is an item
 * the recipient can confirm, mark done, or dispute — no account needed;
 * the link is who they are. Optimistic: the state flips at once and
 * rolls back if the server refuses.
 */
export function SharedItems({
  token,
  items: initial,
  canRespond,
  onError,
  changedKeys = [],
}: {
  token: string;
  items: SharedItem[];
  canRespond: boolean;
  onError: (message: string) => void;
  /** Sprint 23: item keys the "what changed" strip points at. */
  changedKeys?: string[];
}) {
  const [items, setItems] = useState(initial);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [disputing, setDisputing] = useState<string | null>(null);

  const acted = items.filter((i) => i.my_response !== null).length;

  const patch = (key: string, next: Partial<SharedItem>) =>
    setItems((cur) => cur.map((i) => (i.item_key === key ? { ...i, ...next } : i)));

  const respond = async (item: SharedItem, kind: "confirm" | "done" | "dispute", comment?: string) => {
    const before = { my_response: item.my_response, my_comment: item.my_comment };
    patch(item.item_key, { my_response: kind, my_comment: kind === "dispute" ? comment ?? null : null });
    setBusyKey(item.item_key);
    try {
      await respondToItem(token, item.item_key, kind, comment);
      setDisputing(null);
    } catch (err) {
      patch(item.item_key, before);
      onError(friendly(err));
    } finally {
      setBusyKey(null);
    }
  };

  const undo = async (item: SharedItem) => {
    const before = { my_response: item.my_response, my_comment: item.my_comment };
    patch(item.item_key, { my_response: null, my_comment: null });
    setBusyKey(item.item_key);
    try {
      await withdrawItemResponse(token, item.item_key);
    } catch (err) {
      patch(item.item_key, before);
      onError(friendly(err));
    } finally {
      setBusyKey(null);
    }
  };

  const overdue = (iso: string | null) => iso !== null && new Date(iso) < new Date(new Date().toDateString());

  return (
    <section className="doc-section shared-key shared-items" aria-label="Who does what">
      <h2 className="section-name">Who does what</h2>
      {canRespond && items.length > 0 && (
        <p className="shared-progress">
          {acted === 0
            ? "Confirm what you agreed to, or dispute what's wrong."
            : `You responded to ${acted} of ${items.length} item${items.length === 1 ? "" : "s"}.`}
        </p>
      )}
      <ul className="shared-item-list">
        {items.map((item) => {
          const busy = busyKey === item.item_key;
          const state = item.status === "done" ? "done" : item.my_response ?? "open";
          return (
            <li key={item.item_key} className={`shared-item state-${state} ${changedKeys.includes(item.item_key) ? "changed" : ""}`}>
              <span className="shared-item-glyph" aria-hidden="true">
                {item.status === "done" || item.my_response === "done" ? "☑" : item.my_response === "dispute" ? "✗" : "☐"}
              </span>
              <div className="shared-item-body">
                <span className="shared-item-text">{item.text}</span>
                <span className="shared-item-meta">
                  {item.owner_label && <span className="chip owner">{item.owner_label}</span>}
                  {(item.due_date || item.due_text) && (
                    <span className={`chip due ${overdue(item.due_date) ? "overdue" : ""}`}>
                      {item.due_date
                        ? new Date(item.due_date).toLocaleDateString(undefined, { day: "numeric", month: "short" })
                        : item.due_text}
                    </span>
                  )}
                  {item.status === "done" && <span className="chip done">done</span>}
                  {item.status === "dropped" && <span className="chip cancelled">dropped</span>}
                </span>
                {item.my_response === "dispute" && item.my_comment && (
                  <p className="shared-item-comment">You said: {item.my_comment}</p>
                )}
                {canRespond && disputing === item.item_key && (
                  <CommentBox
                    label="What's different?"
                    busy={busy}
                    onCancel={() => setDisputing(null)}
                    onSubmit={(comment) => void respond(item, "dispute", comment)}
                  />
                )}
              </div>
              {canRespond && item.status !== "dropped" && (
                <span className="shared-item-actions">
                  {item.my_response ? (
                    <>
                      <span className="chip version">
                        {item.my_response === "confirm" ? "Confirmed" : item.my_response === "done" ? "Done" : "Disputed"}
                      </span>
                      <button className="btn ghost sm" disabled={busy} onClick={() => void undo(item)}>
                        Undo
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        className="btn sm"
                        aria-pressed={false}
                        disabled={busy}
                        title="Yes, that's what we agreed"
                        onClick={() => void respond(item, "confirm")}
                      >
                        <CheckIcon size={13} /> Confirm
                      </button>
                      {item.status !== "done" && (
                        <button className="btn sm" aria-pressed={false} disabled={busy} onClick={() => void respond(item, "done")}>
                          Done
                        </button>
                      )}
                      <button
                        className="btn ghost sm"
                        aria-pressed={disputing === item.item_key}
                        disabled={busy}
                        onClick={() => setDisputing(disputing === item.item_key ? null : item.item_key)}
                      >
                        <CloseIcon size={12} /> Dispute
                      </button>
                    </>
                  )}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** "Flag as inaccurate" under any other section. */
export function FlagControl({
  token,
  sectionKey,
  flagged: initial,
  onError,
}: {
  token: string;
  sectionKey: string;
  flagged: boolean;
  onError: (message: string) => void;
}) {
  const [flagged, setFlagged] = useState(initial);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const send = async (comment: string) => {
    setBusy(true);
    setFlagged(true);
    try {
      await flagSection(token, sectionKey, comment);
      setOpen(false);
    } catch (err) {
      setFlagged(false);
      onError(friendly(err));
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setBusy(true);
    setFlagged(false);
    try {
      await unflagSection(token, sectionKey);
    } catch (err) {
      setFlagged(true);
      onError(friendly(err));
    } finally {
      setBusy(false);
    }
  };

  if (flagged) {
    return (
      <p className="shared-flag">
        <span className="chip cancelled">Flagged as inaccurate</span>{" "}
        <button className="btn ghost sm" disabled={busy} onClick={() => void clear()}>
          Undo
        </button>
      </p>
    );
  }
  return (
    <div className="shared-flag">
      {open ? (
        <CommentBox label="What's inaccurate?" busy={busy} onCancel={() => setOpen(false)} onSubmit={(c) => void send(c)} />
      ) : (
        <button className="btn ghost sm" onClick={() => setOpen(true)}>
          Flag as inaccurate
        </button>
      )}
    </div>
  );
}
