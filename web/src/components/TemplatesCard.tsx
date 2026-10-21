import { useCallback, useEffect, useState } from "react";
import { deleteTemplate, getTemplates, putTemplate } from "../api/aiTemplates";
import type { NoteTemplate, TemplateLanguage, WorkspaceTemplate } from "../api/types";
import { NOTE_TEMPLATE_LABELS } from "../api/types";
import { messageFor } from "../lib/errorCopy";
import { relativeTime } from "../lib/time";
import { ConfirmDialog } from "./ConfirmDialog";
import { useToast } from "./Toaster";

const LANGUAGES: ReadonlyArray<readonly [TemplateLanguage, string]> = [
  ["en", "English"],
  ["de", "Deutsch"],
  ["uk", "Українська"],
];
// The server's limit on a workspace's text.
const MAX_CHARS = 4000;
const NEAR_LIMIT = 200;

/**
 * Settings › Note writing › Templates (P2): the seven templates the writer knows, per
 * language. Every member reads them; an admin edits one (the workspace's own text replaces
 * the built-in one) or resets it to the built-in text.
 */
export function TemplatesCard() {
  const toast = useToast();
  const [language, setLanguage] = useState<TemplateLanguage>("en");
  const [templates, setTemplates] = useState<WorkspaceTemplate[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<NoteTemplate | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<"saving" | "resetting" | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  const load = useCallback(async (which: TemplateLanguage) => {
    try {
      setTemplates(await getTemplates(which));
      setError(null);
    } catch (err) {
      setError(messageFor(err));
    }
  }, []);

  useEffect(() => {
    void load(language);
  }, [load, language]);

  const current = templates?.find((t) => t.name === open) ?? null;
  const dirty = current !== null && draft !== current.markdown;

  const switchLanguage = (next: TemplateLanguage) => {
    if (next === language) return;
    if (editing && dirty && !window.confirm("Discard your unsaved changes?")) return;
    setEditing(false);
    setTemplates(null);
    setLanguage(next);
  };

  const show = (name: NoteTemplate) => {
    if (editing && dirty && !window.confirm("Discard your unsaved changes?")) return;
    setEditing(false);
    setOpen(open === name ? null : name);
  };

  const save = async () => {
    if (!current) return;
    setBusy("saving");
    try {
      const saved = await putTemplate(current.name, { language, markdown: draft });
      setTemplates((all) => all?.map((t) => (t.name === saved.name ? saved : t)) ?? null);
      setEditing(false);
      toast.success(
        `${NOTE_TEMPLATE_LABELS[saved.name]} template saved. The next note written with it follows your text.`,
      );
    } catch (err) {
      toast.error(messageFor(err));
    } finally {
      setBusy(null);
    }
  };

  const reset = async () => {
    if (!current) return;
    setBusy("resetting");
    try {
      await deleteTemplate(current.name, language);
      setConfirmReset(false);
      setEditing(false);
      toast.success(`${NOTE_TEMPLATE_LABELS[current.name]} template reset to the built-in text.`);
      await load(language);
    } catch (err) {
      toast.error(messageFor(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="card pad settings-card" aria-label="Templates">
      <h2 className="settings-h">Templates</h2>
      <p className="help">
        The shape a note is written in: its sections and what goes in each. A note's template is
        chosen when it is created, or by the writer when it is set to Automatic. Edit one to
        replace the built-in text for this workspace.
      </p>
      <div className="seg" role="tablist" aria-label="Template language">
        {LANGUAGES.map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            className="seg-opt"
            aria-selected={language === value}
            aria-pressed={language === value}
            onClick={() => switchLanguage(value)}
          >
            {label}
          </button>
        ))}
      </div>
      {error && !templates && <p className="help danger-text">{error}</p>}
      {!error && !templates && <p className="help">Loading…</p>}
      {templates && (
        <ul className="template-list" aria-label="Templates">
          {templates.map((t) => (
            <li key={t.name}>
              <button
                type="button"
                className="link-btn template-name"
                aria-expanded={open === t.name}
                onClick={() => show(t.name)}
              >
                {NOTE_TEMPLATE_LABELS[t.name] ?? t.name}
              </button>
              {t.source === "workspace" ? (
                <span className="chip">Customised</span>
              ) : (
                <span className="chip draft">Built-in</span>
              )}
              {open === t.name && (
                <div className="template-body">
                  {editing ? (
                    <>
                      <textarea
                        className="textarea instructions-input"
                        aria-label={`${NOTE_TEMPLATE_LABELS[t.name]} template`}
                        value={draft}
                        maxLength={MAX_CHARS}
                        rows={12}
                        spellCheck
                        disabled={busy !== null}
                        onChange={(e) => setDraft(e.target.value)}
                      />
                      <p
                        className={`help${MAX_CHARS - draft.length <= NEAR_LIMIT ? " danger-text" : ""}`}
                      >
                        {draft.length} / {MAX_CHARS} · at least one “## ” heading
                      </p>
                      <div className="settings-actions">
                        <button
                          type="button"
                          className="btn primary"
                          disabled={busy !== null || !dirty || !draft.trim()}
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
                      </div>
                    </>
                  ) : (
                    <>
                      <pre className="instructions-text">{t.markdown}</pre>
                      {t.source === "workspace" && t.updated_at && (
                        <p className="help">Customised {relativeTime(t.updated_at)}</p>
                      )}
                      {t.can_edit && (
                        <div className="settings-actions">
                          <button
                            type="button"
                            className="btn"
                            onClick={() => {
                              setDraft(t.markdown);
                              setEditing(true);
                            }}
                          >
                            Edit
                          </button>
                          {t.source === "workspace" && (
                            <button
                              type="button"
                              className="btn ghost"
                              onClick={() => setConfirmReset(true)}
                            >
                              Reset to built-in
                            </button>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {confirmReset && current && (
        <ConfirmDialog
          title={`Reset the ${NOTE_TEMPLATE_LABELS[current.name]} template?`}
          confirmLabel="Reset"
          busy={busy === "resetting"}
          onConfirm={() => void reset()}
          onCancel={() => setConfirmReset(false)}
        >
          Notes written with it from now on use the built-in text. Notes already written keep
          every word they have.
        </ConfirmDialog>
      )}
    </section>
  );
}
