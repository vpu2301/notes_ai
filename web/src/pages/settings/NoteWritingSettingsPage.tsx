import { useCallback, useEffect, useState } from "react";
import { getAiSettings, putAiSettings } from "../../api/aiSettings";
import type { AiSettings, AiSettingsUpdate } from "../../api/types";
import { ModelBehaviourCard } from "../../components/ModelBehaviourCard";
import { NoteInstructionsCard } from "../../components/NoteInstructionsCard";
import { TemplatesCard } from "../../components/TemplatesCard";
import { useToast } from "../../components/Toaster";
import { messageFor } from "../../lib/errorCopy";

/**
 * `/settings/writing` — how this workspace's notes are written, top to bottom: the
 * templates, the instructions, automatic writing, and (closed) the model behaviour. Every
 * member reads it; an admin changes it (the API checks). Each section loads and fails on its own.
 */
export function NoteWritingSettingsPage() {
  const toast = useToast();
  const [settings, setSettings] = useState<AiSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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

  return (
    <div className="settings-stack">
      {settings && !settings.can_edit && (
        <p className="help">Only a workspace admin can change these.</p>
      )}

      <TemplatesCard />

      <NoteInstructionsCard />

      {error && !settings && <p className="help danger-text">{error}</p>}
      {!error && !settings && <p className="help">Loading…</p>}

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
    </div>
  );
}
