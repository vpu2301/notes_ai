import { useCallback, useEffect, useRef, useState } from "react";
import { deleteAiInstructions, getAiInstructions, putAiInstructions } from "../api/aiInstructions";
import { ApiError } from "../api/http";
import type { AiInstructions } from "../api/types";
import { messageFor } from "../lib/errorCopy";
import { relativeTime } from "../lib/time";
import { ConfirmDialog } from "./ConfirmDialog";
import { useToast } from "./Toaster";

// The Spend view's sentence: one wording for a spent budget.
const BUDGET_COPY =
  "This workspace has used its AI budget for the month, so new recordings are transcribed but not written up.";
// The counter warns this close to the limit.
const NEAR_LIMIT = 200;

/** The skeleton one note's own text shows as its placeholder (the sheet). */
export const SKELETON = `Reader: who reads these notes and what they need from them.
Length: how long a note should be.
Sections: which sections every note must have, and in what order.
Emphasis: what to bring out (decisions, numbers, risks, next steps).
Wording: tone, person, terms to use or avoid.
Examples: a line or two written the way you want.`;

/** The help line under the box (P2a): what a workspace adds below the default rules. */
export const OWN_RULES_HELP =
  "Add your own rules below the defaults: who reads these notes, how long, which sections, what to emphasise, wording, examples.";

export function errorCopy(err: unknown): string {
  if (err instanceof ApiError && err.status === 429 && err.code === "budget_exceeded") {
    return BUDGET_COPY;
  }
  return messageFor(err);
}

/**
 * Settings › Note writing › Instructions: the text the writer follows, verbatim. It holds
 * the default rules until an admin edits them (or pastes a file); "Reset to default" goes
 * back to the rules that ship. Every member reads it. Absent while the server has the
 * feature off.
 */
export function NoteInstructionsCard() {
  const toast = useToast();
  const [stored, setStored] = useState<AiInstructions | null>(null);
  const [absent, setAbsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<"saving" | "resetting" | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setStored(await getAiInstructions());
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404 && err.code === "not_available") {
        setAbsent(true);
        return;
      }
      setError(messageFor(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = stored !== null && draft.trim() !== stored.text.trim();

  useEffect(() => {
    if (!(editing && dirty)) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [editing, dirty]);

  if (absent) return null;

  const save = async () => {
    setBusy("saving");
    try {
      const saved = await putAiInstructions({ text: draft });
      setStored(saved);
      setEditing(false);
      toast.success(
        saved.source === "default"
          ? "Back to the default rules."
          : `Instructions saved (v${saved.version}). The next note written in this workspace follows them.`,
      );
    } catch (err) {
      toast.error(errorCopy(err));
    } finally {
      setBusy(null);
    }
  };

  const reset = async () => {
    setBusy("resetting");
    try {
      await deleteAiInstructions();
      setConfirmReset(false);
      setEditing(false);
      toast.success("Back to the default rules.");
      await load();
    } catch (err) {
      toast.error(errorCopy(err));
    } finally {
      setBusy(null);
    }
  };

  const max = stored?.max_chars ?? 0;

  // "Load from file": the file is read here, into the box only; nothing is saved until Save.
  const loadFile = (file: File | undefined) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const text = String(reader.result ?? "");
      if (text.length > max) {
        toast.error(`That file is longer than the limit of ${max} characters.`);
        return;
      }
      setDraft(text);
    };
    reader.onerror = () => toast.error("That file could not be read.");
    reader.readAsText(file);
  };

  const sourceLabel = stored?.source === "default" ? "Default rules" : "Edited";

  return (
    <section className="card pad settings-card" aria-label="Note instructions">
      <h2 className="settings-h">Instructions</h2>
      <p className="help">
        The rules the writer follows, as written here, with the template and the transcript. Edit
        them, paste your own file, or reset to the default rules.
      </p>
      {error && !stored && <p className="help danger-text">{error}</p>}
      {!error && !stored && <p className="help">Loading…</p>}

      {stored && !editing && (
        <>
          <p className="help instructions-source" data-testid="instructions-source">
            <strong>{sourceLabel}</strong>
            {stored.source !== "default" && stored.version > 0 ? ` · v${stored.version}` : ""}
            {stored.source !== "default" && stored.updated_at
              ? ` · updated ${relativeTime(stored.updated_at)}`
              : ""}
          </p>
          <pre className="instructions-text">{stored.text}</pre>
          {stored.can_edit && (
            <div className="settings-actions">
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setDraft(stored.text);
                  setEditing(true);
                }}
              >
                Edit
              </button>
              {stored.source !== "default" && (
                <button
                  type="button"
                  className="btn ghost"
                  disabled={busy !== null}
                  onClick={() => setConfirmReset(true)}
                >
                  Reset to default
                </button>
              )}
            </div>
          )}
        </>
      )}

      {stored && editing && (
        <>
          <p className="help instructions-source" data-testid="instructions-source">
            <strong>{dirty ? "Edited" : sourceLabel}</strong>
          </p>
          <textarea
            className="textarea instructions-input"
            aria-label="Note instructions"
            aria-describedby="instructions-help instructions-counter"
            value={draft}
            maxLength={max}
            rows={18}
            spellCheck
            disabled={busy !== null}
            onChange={(e) => setDraft(e.target.value)}
          />
          <p id="instructions-help" className="help">
            {OWN_RULES_HELP}
          </p>
          <p
            id="instructions-counter"
            className={`help${max - draft.length <= NEAR_LIMIT ? " danger-text" : ""}`}
          >
            {draft.length} / {max}
          </p>
          <div className="settings-actions">
            <button
              type="button"
              className="btn primary"
              disabled={busy !== null || !dirty}
              onClick={() => void save()}
            >
              {busy === "saving" ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              className="btn ghost"
              disabled={busy !== null}
              onClick={() => setEditing(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn ghost"
              disabled={busy !== null}
              onClick={() => fileInput.current?.click()}
            >
              Load from file
            </button>
            <input
              ref={fileInput}
              type="file"
              accept=".md,.txt,text/markdown,text/plain"
              aria-label="Instructions file"
              hidden
              onChange={(e) => {
                loadFile(e.target.files?.[0]);
                e.target.value = "";
              }}
            />
            {stored.source !== "default" && (
              <button
                type="button"
                className="btn ghost"
                disabled={busy !== null}
                onClick={() => setConfirmReset(true)}
              >
                Reset to default
              </button>
            )}
          </div>
        </>
      )}

      {confirmReset && (
        <ConfirmDialog
          title="Replace your instructions with the default rules?"
          confirmLabel="Reset"
          confirmDanger
          busy={busy === "resetting"}
          onConfirm={() => void reset()}
          onCancel={() => setConfirmReset(false)}
        >
          Your text will be lost. Notes already written keep every word they have.
        </ConfirmDialog>
      )}
    </section>
  );
}
