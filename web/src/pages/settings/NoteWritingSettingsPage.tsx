import { useCallback, useEffect, useState } from "react";
import { getAiSettings, putAiSettings } from "../../api/aiSettings";
import type { AiSettings, AiSettingsUpdate } from "../../api/types";
import { ModelBehaviourCard, WritingStyleCard } from "../../components/ModelBehaviourCard";
import { NoteInstructionsCard } from "../../components/NoteInstructionsCard";
import { useToast } from "../../components/Toaster";
import { messageFor } from "../../lib/errorCopy";

/**
 * `/settings/writing` — how this workspace's notes are written, top to bottom: the style,
 * the note instructions, automatic writing, and (closed) the model behaviour. Every member
 * reads it; an admin changes it (the API checks). Each section loads and fails on its own.
 */
export function NoteWritingSettingsPage() {
  const toast = useToast();
  const [settings, setSettings] = useState<AiSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // The style the note instructions name, if any: the style picker says it is overridden.
  const [instructedStyle, setInstructedStyle] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setSettings(await getAiSettings());
      setError(null);
    } catch (err) {
      setError(messageFor(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (body: AiSettingsUpdate, done: string | ((saved: AiSettings) => string)) => {
    setBusy(true);
    try {
      const saved = await putAiSettings(body);
      setSettings(saved);
      toast.success(typeof done === "function" ? done(saved) : done);
    } catch (err) {
      toast.error(messageFor(err));
      // The server's view is the truth after a refusal.
      await load();
    } finally {
      setBusy(false);
    }
  };

  const settingsLine = error ? (
    <p className="help danger-text">{error}</p>
  ) : (
    <p className="help">Loading…</p>
  );

  return (
    <div className="settings-stack">
      {settings && !settings.can_edit && (
        <p className="help">Only a workspace admin can change these.</p>
      )}

      {settings ? (
        <WritingStyleCard
          settings={settings}
          busy={busy}
          onSave={save}
          overriddenBy={instructedStyle}
        />
      ) : (
        settingsLine
      )}

      <NoteInstructionsCard
        onLoaded={(instructions) =>
          setInstructedStyle(
            (instructions?.profile as { style?: string | null } | undefined)?.style ?? null,
          )
        }
      />

      {settings && (
        <section className="card pad settings-card" aria-label="Automatic note writing">
          <h2 className="settings-h">Automatic writing</h2>
          <p className="help">
            When this is off, recordings are still transcribed and your own typing is untouched —
            the note simply is not written for you. Notes already written keep every word they
            have.
          </p>
          <label className="chk-row">
            <input
              type="checkbox"
              checked={settings.generation_enabled}
              disabled={!settings.can_edit || busy}
              onChange={(e) =>
                void save(
                  { generation_enabled: e.target.checked },
                  e.target.checked
                    ? "Notes will be written automatically."
                    : "Automatic note writing is off.",
                )
              }
            />
            Write notes automatically after a recording
          </label>
        </section>
      )}

      {settings && <ModelBehaviourCard settings={settings} busy={busy} onSave={save} />}

      <p className="help">
        The instructions and models used for each stage of note writing, and tests of changes to
        them, are under <a href="/settings/ai-notes">AI notes</a>.
      </p>
    </div>
  );
}
