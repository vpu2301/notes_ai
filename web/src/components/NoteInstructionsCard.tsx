import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteAiInstructions,
  getAiInstructions,
  previewAiInstructions,
  putAiInstructions,
} from "../api/aiInstructions";
import { ApiError } from "../api/http";
import type { AiInstructions, InstructionsScope } from "../api/types";
import { messageFor } from "../lib/errorCopy";
import { relativeTime } from "../lib/time";
import { ConfirmDialog } from "./ConfirmDialog";
import { NoteInstructionsGuide } from "./NoteInstructionsGuide";
import { useToast } from "./Toaster";

export const FAILED_COPY =
  "Your text was saved but could not be read right now (the model was unavailable). Notes are written as usual until you press Check again.";
// The Spend view's sentence: one wording for a spent budget.
const BUDGET_COPY =
  "This workspace has used its AI budget for the month, so new recordings are transcribed but not written up.";
// The counter warns this close to the limit.
const NEAR_LIMIT = 200;

/** The tabs: the workspace text, then one per meeting type that extends it (N4). */
export const SCOPES: ReadonlyArray<readonly [InstructionsScope, string, string]> = [
  ["workspace", "Workspace", "note"],
  ["client", "Client calls", "client call"],
  ["team", "Team meetings", "team meeting"],
  ["sales", "Sales calls", "sales call"],
  ["one_on_one", "1:1s", "1:1"],
  ["interview", "Interviews", "interview"],
  ["broadcast", "Broadcasts", "broadcast"],
  ["memo", "Memos", "memo"],
];

export function errorCopy(err: unknown): string {
  if (err instanceof ApiError && err.status === 429) {
    if (err.code === "too_many_previews") {
      return `Too many checks — try again in ${err.retryAfter ?? 60} s.`;
    }
    if (err.code === "budget_exceeded") return BUDGET_COPY;
  }
  return messageFor(err);
}

/** What the writer understood: rendered by the server, shown as sent. */
export function Readout({ data }: { data: AiInstructions }) {
  return (
    <div className="instructions-readout">
      <h3 className="settings-sub">Understood</h3>
      {data.understood.length > 0 ? (
        <ul className="instructions-list">
          {data.understood.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : (
        data.text.trim() && (
          <p className="help">Nothing specific — the notes are written as usual.</p>
        )
      )}
      {data.guidance.length > 0 && (
        <>
          <h3 className="settings-sub">Also passed to the writer as wording guidance</h3>
          <ul className="instructions-list">
            {data.guidance.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </>
      )}
      {data.not_applied.length > 0 && (
        <>
          <h3 className="settings-sub">Not applied</h3>
          <ul className="instructions-list">
            {data.not_applied.map((item) => (
              <li key={`${item.reason}:${item.text}`} className="help">
                “{item.text}” — {item.message}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/**
 * Settings → Data & AI → Note writing: how this workspace wants its notes written. Every
 * member reads the text and what the writer understood; an admin edits, presses Check
 * (compiled, nothing saved) and saves. Absent while the server has the feature off.
 */
export function NoteInstructionsCard({
  onLoaded,
}: {
  /** The stored instructions whenever they load or change (null: none or the feature off). */
  onLoaded?: (instructions: AiInstructions | null) => void;
} = {}) {
  const toast = useToast();
  const [scope, setScope] = useState<InstructionsScope>("workspace");
  const [stored, setStored] = useState<AiInstructions | null>(null);
  // The workspace text: the tabs' state (`scopes`) and the parent a type text extends.
  const [workspace, setWorkspace] = useState<AiInstructions | null>(null);
  const loadedRef = useRef(onLoaded);
  loadedRef.current = onLoaded;
  useEffect(
    () => loadedRef.current?.(workspace && workspace.version > 0 ? workspace : null),
    [workspace],
  );
  const [absent, setAbsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [preview, setPreview] = useState<AiInstructions | null>(null);
  const [busy, setBusy] = useState<"checking" | "saving" | "clearing" | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);

  const load = useCallback(async (which: InstructionsScope) => {
    try {
      const data = await getAiInstructions(which);
      setStored(data);
      if (which === "workspace") setWorkspace(data);
      else setWorkspace(await getAiInstructions());
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
    void load(scope);
  }, [load, scope]);

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

  const [, , noun] = SCOPES.find(([v]) => v === scope) ?? SCOPES[0]!;
  const parentVersion = workspace?.version ?? 0;
  const has = (s: InstructionsScope) => workspace?.scopes?.find((x) => x.scope === s);
  const switchTo = (next: InstructionsScope) => {
    if (next === scope) return;
    if (editing && dirty && !window.confirm("Discard your unsaved changes?")) return;
    setEditing(false);
    setPreview(null);
    setStored(null);
    setScope(next);
  };

  const startEditing = (text?: string) => {
    setDraft(text ?? stored?.text ?? "");
    setPreview(null);
    setEditing(true);
  };

  const cancel = () => {
    setEditing(false);
    setPreview(null);
  };

  const check = async (text = draft) => {
    setBusy("checking");
    try {
      setPreview(await previewAiInstructions({ text }, scope));
    } catch (err) {
      toast.error(errorCopy(err));
    } finally {
      setBusy(null);
    }
  };

  const save = async (text: string) => {
    setBusy("saving");
    try {
      const saved = await putAiInstructions({ text }, scope);
      setStored(saved);
      setEditing(false);
      setPreview(null);
      // The tabs' state (a type may now wait for its recompile).
      setWorkspace(await getAiInstructions());
      toast.success(
        saved.version === 0
          ? "Instructions cleared. Notes are written as usual."
          : `Instructions saved (v${saved.version}). The next ${noun} written in this workspace follows them.`,
      );
    } catch (err) {
      toast.error(errorCopy(err));
    } finally {
      setBusy(null);
    }
  };

  const clear = async () => {
    setBusy("clearing");
    try {
      await deleteAiInstructions(scope);
      setConfirmClear(false);
      setEditing(false);
      setPreview(null);
      toast.success(
        scope === "workspace"
          ? "Instructions cleared. Notes are written as usual."
          : `Instructions cleared. A ${noun} is written with the workspace instructions.`,
      );
      await load(scope);
    } catch (err) {
      toast.error(errorCopy(err));
    } finally {
      setBusy(null);
    }
  };

  const max = stored?.max_chars ?? 0;
  const shown = preview ?? stored;

  return (
    <section className="card pad settings-card" aria-label="Note instructions">
      <h2 className="settings-h">Note instructions</h2>
      <p className="help">
        How this workspace wants its notes written — length, sections, emphasis and wording. They
        change the form of a note, never what it says.
      </p>
      {workspace && (
        <div className="seg instructions-scopes" role="tablist" aria-label="Instructions for">
          {SCOPES.map(([value, label]) => {
            const state = has(value);
            return (
              <button
                key={value}
                type="button"
                role="tab"
                className="seg-opt"
                aria-selected={scope === value}
                aria-pressed={scope === value}
                onClick={() => switchTo(value)}
              >
                {label}
                {state && <span className="scope-dot" aria-label="has instructions" />}
                {state?.stale && <span className="help"> Updating…</span>}
              </button>
            );
          })}
        </div>
      )}
      {scope !== "workspace" && workspace && (
        <>
          <p className="help">
            {parentVersion > 0
              ? `Extends the workspace instructions (v${parentVersion}) — the readout below is the combined result.`
              : "No workspace instructions yet — this text stands on its own."}
          </p>
          {parentVersion > 0 && (
            <details className="instructions-parent">
              <summary className="help">Workspace instructions</summary>
              <pre className="instructions-text">{workspace.text}</pre>
            </details>
          )}
        </>
      )}
      {stored?.stale && (
        <p className="banner banner-warn" role="status">
          Updating — this text is being read again with the new workspace instructions. Until then a{" "}
          {noun} is written with the workspace instructions.
        </p>
      )}
      {error && !stored && <p className="help danger-text">{error}</p>}
      {!error && !stored && <p className="help">Loading…</p>}

      {stored && !editing && (
        <>
          {stored.version === 0 ? (
            <p className="help">
              None set — notes are written as usual.
              {!stored.can_edit && " A workspace admin can add them."}
            </p>
          ) : (
            <>
              <pre className="instructions-text">{stored.text}</pre>
              {stored.compile_status === "failed" && (
                <div className="banner banner-warn" role="status">
                  {FAILED_COPY}{" "}
                  {stored.can_edit && (
                    <button
                      type="button"
                      className="btn sm ghost"
                      disabled={busy !== null}
                      onClick={() => void save(stored.text)}
                    >
                      Try again
                    </button>
                  )}
                </div>
              )}
              <Readout data={stored} />
              <p className="help">
                v{stored.version}
                {stored.updated_at ? ` · updated ${relativeTime(stored.updated_at)}` : ""}
              </p>
            </>
          )}
          {stored.can_edit && (
            <div className="settings-actions">
              <button type="button" className="btn" onClick={() => startEditing()}>
                {stored.version === 0 ? "Add instructions" : "Edit"}
              </button>
            </div>
          )}
        </>
      )}

      {stored && editing && (
        <>
          <textarea
            className="textarea instructions-input"
            aria-label="Note instructions"
            aria-describedby="instructions-counter"
            value={draft}
            maxLength={max}
            rows={12}
            spellCheck
            disabled={busy !== null}
            onChange={(e) => {
              setDraft(e.target.value);
              setPreview(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && draft.trim()) {
                e.preventDefault();
                void check();
              }
            }}
          />
          <p
            id="instructions-counter"
            className={`help${max - draft.length <= NEAR_LIMIT ? " danger-text" : ""}`}
          >
            {draft.length} / {max}
          </p>
          {busy === "checking" && (
            <p className="help" role="status">
              Reading your instructions…
            </p>
          )}
          {preview && (
            <>
              <span className="chip draft">Preview — not saved yet</span>
              {preview.compile_status === "failed" && (
                <p className="banner banner-warn" role="status">
                  Your text could not be read right now (the model was unavailable). Try Check
                  again.
                </p>
              )}
              <Readout data={preview} />
            </>
          )}
          <div className="settings-actions">
            <button
              type="button"
              className="btn"
              disabled={busy !== null || !draft.trim()}
              onClick={() => void check()}
            >
              Check
            </button>
            <button
              type="button"
              className="btn primary"
              disabled={busy !== null || !dirty}
              onClick={() => void save(draft)}
            >
              {busy === "saving" ? "Saving…" : "Save"}
            </button>
            <button type="button" className="btn ghost" disabled={busy !== null} onClick={cancel}>
              Cancel
            </button>
            {stored.version > 0 && (
              <button
                type="button"
                className="btn ghost danger-text"
                disabled={busy !== null}
                onClick={() => setConfirmClear(true)}
              >
                Clear
              </button>
            )}
          </div>
        </>
      )}

      {shown && (
        <NoteInstructionsGuide
          onPreset={
            stored?.can_edit
              ? (preset) => {
                  // An example fills the text and is checked at once; it is saved only by Save.
                  if (editing) {
                    setDraft(preset.text);
                    setPreview(null);
                  } else {
                    startEditing(preset.text);
                  }
                  void check(preset.text);
                }
              : undefined
          }
          presetsDisabled={editing ? draft.trim() !== "" : (stored?.text ?? "").trim() !== ""}
        />
      )}

      {confirmClear && (
        <ConfirmDialog
          title="Clear the note instructions?"
          confirmLabel="Clear"
          confirmDanger
          busy={busy === "clearing"}
          onConfirm={() => void clear()}
          onCancel={() => setConfirmClear(false)}
        >
          Notes written from now on follow no workspace instructions. Notes already written keep
          every word they have.
        </ConfirmDialog>
      )}
    </section>
  );
}
