import { useEffect, useRef, useState } from "react";
import { regenerate } from "../api/generation";
import { ApiError } from "../api/http";
import {
  deleteNoteInstructions,
  getNoteInstructions,
  putNoteInstructions,
} from "../api/aiInstructions";
import type { AiInstructions } from "../api/types";
import { SKELETON, errorCopy } from "./NoteInstructionsCard";
import { useToast } from "./Toaster";

const NEAR_LIMIT = 200;

/**
 * "Write this note differently…": instructions for this note only, added to the
 * workspace's, then the note is written again. Any editor of the note. Regenerate = save,
 * then rewrite; Remove and rewrite = remove, then rewrite.
 */
export function NoteInstructionsSheet({
  noteId,
  onClose,
  onRewritten,
}: {
  noteId: string;
  onClose: () => void;
  /** The note is being written again: the status line should follow the new run. */
  onRewritten: () => void;
}) {
  const toast = useToast();
  const [stored, setStored] = useState<AiInstructions | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<"saving" | null>(null);
  // Read through refs: the page rebuilds them each render, and the text must load once.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  const toastRef = useRef(toast);
  toastRef.current = toast;

  useEffect(() => {
    let alive = true;
    getNoteInstructions(noteId)
      .then((data) => {
        if (!alive) return;
        setStored(data);
        setDraft(data.text);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        if (err instanceof ApiError && err.status === 404 && err.code === "not_available") {
          setUnavailable(true);
        } else {
          toastRef.current.error(errorCopy(err));
          closeRef.current();
        }
      });
    return () => {
      alive = false;
    };
  }, [noteId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && closeRef.current();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const max = stored?.max_chars ?? 4000;

  const rewrite = async (save: () => Promise<unknown>, saved: string) => {
    setBusy("saving");
    try {
      await save();
    } catch (err) {
      toast.error(errorCopy(err));
      setBusy(null);
      return;
    }
    try {
      await regenerate(noteId);
      toast.success(saved);
      onRewritten();
      onClose();
    } catch (err) {
      // The instructions are kept; the rewrite can be tried again from the menu.
      toast.error(
        err instanceof ApiError && err.status === 409
          ? "Saved; the note could not be rewritten right now."
          : errorCopy(err),
      );
      setBusy(null);
    }
  };

  return (
    <div className="modal-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className="modal note-instructions-sheet"
        role="dialog"
        aria-modal="true"
        aria-label="Write this note differently"
      >
        <h2 className="settings-h">Write this note differently</h2>
        {unavailable ? (
          <p className="help">This isn&rsquo;t available in this workspace yet.</p>
        ) : !stored ? (
          <p className="help">Loading…</p>
        ) : (
          <>
            <p className="help">
              Instructions for this note only. They are added to the workspace&rsquo;s instructions
              and the note is written again.
            </p>
            <textarea
              className="textarea instructions-input"
              aria-label="Instructions for this note"
              aria-describedby="note-instructions-counter"
              value={draft}
              placeholder={SKELETON}
              maxLength={max}
              rows={8}
              spellCheck
              disabled={busy !== null}
              onChange={(e) => setDraft(e.target.value)}
            />
            <p
              id="note-instructions-counter"
              className={`help${max - draft.length <= NEAR_LIMIT ? " danger-text" : ""}`}
            >
              {draft.length} / {max}
            </p>
            <div className="settings-actions">
              <button
                type="button"
                className="btn primary"
                disabled={busy !== null || !draft.trim()}
                onClick={() =>
                  void rewrite(
                    () => putNoteInstructions(noteId, { text: draft }),
                    "Saved. The note is being written again.",
                  )
                }
              >
                {busy === "saving" ? "Regenerating…" : "Regenerate this note with the new instructions"}
              </button>
              {stored.version > 0 && (
                <button
                  type="button"
                  className="btn ghost danger-text"
                  disabled={busy !== null}
                  onClick={() =>
                    void rewrite(
                      () => deleteNoteInstructions(noteId),
                      "Removed. The note is being written with the workspace instructions.",
                    )
                  }
                >
                  Remove and rewrite
                </button>
              )}
              <button
                type="button"
                className="btn ghost"
                disabled={busy !== null}
                onClick={onClose}
              >
                Cancel
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
