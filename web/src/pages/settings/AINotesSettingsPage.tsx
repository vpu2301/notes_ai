import { useCallback, useEffect, useMemo, useState } from "react";
import {
  activateVersion,
  activationHistory,
  aiRuntime,
  createProfile,
  getVersion,
  listExperiments,
  listProfiles,
  modelCapabilities,
} from "../../api/aiNotes";
import { ApiError } from "../../api/http";
import type {
  ActivationRecord,
  AiRuntime,
  ExperimentSummary,
  ModelCapabilities,
  ProfileConfig,
  PromptProfile,
  PromptProfilesView,
} from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Segmented } from "../../components/Segmented";
import { useToast } from "../../components/Toaster";
import { messageFor } from "../../lib/errorCopy";
import { useSettingsView } from "../../lib/useSettingsView";
import { ComparePanel } from "./aiNotes/ComparePanel";
import { EditorPanel } from "./aiNotes/EditorPanel";
import {
  EMPTY_CONFIG,
  LANGUAGES,
  STAGE_LABELS,
  STAGES,
  describeDiff,
  diffConfigs,
  normalise,
  versionLabel,
} from "./aiNotes/shared";
import { TestPanel } from "./aiNotes/TestPanel";

const VIEWS = [
  { value: "profiles", label: "Profiles" },
  { value: "edit", label: "Edit" },
  { value: "test", label: "Test" },
  { value: "compare", label: "Compare" },
] as const;
type View = (typeof VIEWS)[number]["value"];

interface Editing {
  profile: PromptProfile;
  baseVersionId: string | null;
  baseConfig: ProfileConfig;
}

interface Activating {
  profileId: string;
  versionId: string | null;
  rollback: boolean;
}

/**
 * `/settings/ai-notes` — how this workspace's notes are written: instructions and models,
 * saved as versions, tested on the same transcripts, then activated by an admin. The
 * server's active version is the truth; this page holds only an unsaved draft.
 */
export function AINotesSettingsPage() {
  const toast = useToast();
  const [view, setViewRaw] = useSettingsView(VIEWS);
  const [profiles, setProfiles] = useState<PromptProfilesView | null>(null);
  const [capabilities, setCapabilities] = useState<ModelCapabilities | null>(null);
  const [runtime, setRuntime] = useState<AiRuntime | null>(null);
  const [experiments, setExperiments] = useState<ExperimentSummary[]>([]);
  const [history, setHistory] = useState<ActivationRecord[] | null>(null);
  const [historyFailed, setHistoryFailed] = useState(false);
  const [activeConfig, setActiveConfig] = useState<ProfileConfig>(EMPTY_CONFIG);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [dirty, setDirty] = useState(false);
  const [leaving, setLeaving] = useState<View | null>(null);
  const [testCandidate, setTestCandidate] = useState<string | null>(null);
  const [compareExperiment, setCompareExperiment] = useState<string | null>(null);
  const [activating, setActivating] = useState<Activating | null>(null);
  const [newName, setNewName] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [p, c, e] = await Promise.all([listProfiles(), modelCapabilities(), listExperiments()]);
      setProfiles(p);
      setCapabilities(c);
      setExperiments(e);
      setError(null);
      const activeId = p.active.profile_version_id;
      const owner = p.profiles.find((x) => x.versions.some((v) => v.id === activeId));
      setActiveConfig(
        activeId && owner ? normalise((await getVersion(owner.id, activeId, "en")).config) : EMPTY_CONFIG,
      );
    } catch (err) {
      setError(messageFor(err));
    }
    try {
      setRuntime(await aiRuntime());
    } catch {
      // An older server: say nothing about the engine rather than guess.
      setRuntime(null);
    }
    try {
      setHistory(await activationHistory());
      setHistoryFailed(false);
    } catch {
      setHistoryFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Leaving the editor with unsaved edits asks first.
  const setView = (next: View) => {
    if (view === "edit" && dirty && next !== "edit") setLeaving(next);
    else setViewRaw(next);
  };

  const canEdit = profiles?.can_edit ?? false;
  const writer = capabilities?.writer ?? null;
  const wasActive = useMemo(
    () => new Set((history ?? []).map((h) => h.profile_version_id).filter((x): x is string => !!x)),
    [history],
  );

  if (error && !profiles) {
    return (
      <div className="settings-stack">
        <p className="help danger-text">{error}</p>
        <button className="btn sm" type="button" onClick={() => void load()}>
          Try again
        </button>
      </div>
    );
  }
  if (!profiles || !capabilities) return <p className="help">Loading…</p>;

  const startEditing = async (profile: PromptProfile, versionId: string | null) => {
    const base = versionId ? normalise((await getVersion(profile.id, versionId, "en")).config) : EMPTY_CONFIG;
    setEditing({ profile, baseVersionId: versionId, baseConfig: base });
    setViewRaw("edit");
  };

  const duplicate = async (profile: PromptProfile, versionId: string) => {
    setBusy(true);
    try {
      const copy = await createProfile({ name: `${profile.name} (copy)`, copy_of_version_id: versionId });
      toast.success(`Created "${copy.name}" from that version.`);
      await load();
    } catch (err) {
      toast.error(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    if (!newName.trim()) return;
    setBusy(true);
    try {
      const profile = await createProfile({ name: newName.trim() });
      setNewName("");
      await load();
      await startEditing(profile, null);
    } catch (err) {
      toast.error(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const lastActivation = history?.[0] ?? null;
  const lastEvaluation = experiments[0] ?? null;

  return (
    <div className="settings-stack">
      <section className="card pad settings-card" aria-label="How notes are written now">
        <h2 className="settings-h">How notes are written now</h2>
        <dl className="ai-facts">
          <dt>Active</dt>
          <dd data-testid="ai-active">{versionLabel(profiles, profiles.active.profile_version_id)}</dd>
          <dt>Output language</dt>
          <dd>
            {LANGUAGES.find((l) => l.value === activeConfig.output_language)?.label ?? activeConfig.output_language}
            {activeConfig.output_language === "auto" ? " (the language most of the recording is in)" : ""}
            {runtime?.multilingual_evidence ? " — every spoken language is used as evidence" : ""}
          </dd>
          {runtime && (
            <>
              <dt>Checks</dt>
              <dd data-testid="ai-runtime">
                {runtime.fidelity
                  ? "Every point and every written line is checked against what was said before the note is saved."
                  : runtime.multilingual_evidence
                    ? "Points are checked against what was said; written lines are not checked again."
                    : "The previous engine: speech in another language than the recording's may be left out."}{" "}
                <span className="muted">
                  Prompts {runtime.prompt_version}
                  {runtime.build_sha ? ` · build ${runtime.build_sha}` : ""}
                </span>
              </dd>
            </>
          )}
          <dt>Models</dt>
          <dd>
            {STAGES.map((s) => (
              <div key={s}>
                {STAGE_LABELS[s]}: configured{" "}
                <strong>{activeConfig.models[s] ?? "workspace routing"}</strong>
                {!activeConfig.models[s] && writer ? (
                  <>
                    {" "}
                    · actually used <strong>{writer.model_id ?? writer.backend}</strong>
                    {writer.reason ? ` (fallback: ${writer.reason.replace("_", " ")})` : ""}
                  </>
                ) : null}
              </div>
            ))}
          </dd>
          <dt>Last activation</dt>
          <dd>
            {historyFailed
              ? "History could not be loaded."
              : lastActivation
                ? `${new Date(lastActivation.created_at).toLocaleString()} — ${versionLabel(profiles, lastActivation.profile_version_id)}`
                : "Never: the bundled profile has always been used."}
          </dd>
          <dt>Last evaluation</dt>
          <dd>
            {lastEvaluation
              ? `${new Date(lastEvaluation.created_at).toLocaleString()} — ${lastEvaluation.state}`
              : "None yet."}
          </dd>
        </dl>
        <p className="help">
          Changes here affect notes written from now on. Existing notes stay as they are; to apply a
          profile to one, regenerate it — your own edits in it are kept. Who processes the data, and
          spend, are under <a href="/settings/data">Data & AI</a>.
        </p>
        {runtime && !runtime.profile_instructions_apply && (
          <p className="help" data-testid="ai-instructions-unused">
            Instructions in these profiles are not used for new notes here yet: this environment still
            runs the previous engine. Test runs use them, so you can compare before it is switched on.
          </p>
        )}
        {!canEdit && <p className="help">Only a workspace admin can change these settings.</p>}
      </section>

      <Segmented label="AI notes" options={VIEWS} value={view} onChange={setView} />

      {view === "profiles" && (
        <>
          {profiles.profiles.length === 0 && (
            <p className="help">
              Notes are written with the bundled profile. Create a profile to change instructions or
              models — it stays a draft until it has been tested and activated.
            </p>
          )}
          {profiles.profiles.map((profile) => (
            <section key={profile.id} className="card pad settings-card" aria-label={`Profile ${profile.name}`}>
              <div className="settings-card-h">
                <h2 className="settings-h">{profile.name}</h2>
                {canEdit && (
                  <div className="row-actions">
                    <button
                      className="btn sm"
                      type="button"
                      onClick={() =>
                        void startEditing(profile, profile.versions[profile.versions.length - 1]?.id ?? null)
                      }
                    >
                      Edit as new version
                    </button>
                  </div>
                )}
              </div>
              {profile.description && <p className="help">{profile.description}</p>}
              {profile.versions.length === 0 ? (
                <p className="help">No saved version yet.</p>
              ) : (
                <table className="data-table" aria-label={`Versions of ${profile.name}`}>
                  <thead>
                    <tr>
                      <th scope="col">Version</th>
                      <th scope="col">Saved</th>
                      <th scope="col">State</th>
                      {canEdit && <th scope="col">Actions</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {[...profile.versions].reverse().map((v) => {
                      const isActive = v.id === profiles.active.profile_version_id;
                      return (
                        <tr key={v.id}>
                          <th scope="row">v{v.version_number}</th>
                          <td>{new Date(v.created_at).toLocaleString()}</td>
                          <td>
                            {isActive ? "Active" : v.compatible ? "Draft" : `Cannot run here: ${v.incompatible_reason}`}
                          </td>
                          {canEdit && (
                            <td className="row-actions">
                              <button className="btn sm ghost" type="button" onClick={() => void startEditing(profile, v.id)}>
                                Edit
                              </button>
                              <button className="btn sm ghost" type="button" disabled={busy} onClick={() => void duplicate(profile, v.id)}>
                                Duplicate
                              </button>
                              <button
                                className="btn sm ghost"
                                type="button"
                                disabled={!v.compatible}
                                onClick={() => {
                                  setTestCandidate(v.id);
                                  setViewRaw("test");
                                }}
                              >
                                Test
                              </button>
                              {!isActive && (
                                <button
                                  className="btn sm"
                                  type="button"
                                  disabled={!v.compatible}
                                  onClick={() =>
                                    setActivating({ profileId: profile.id, versionId: v.id, rollback: wasActive.has(v.id) })
                                  }
                                >
                                  {wasActive.has(v.id) ? "Roll back to this" : "Activate"}
                                </button>
                              )}
                            </td>
                          )}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </section>
          ))}

          {canEdit && (
            <section className="card pad settings-card" aria-label="New profile">
              <form
                className="budget-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void create();
                }}
              >
                <label className="field">
                  <span>New profile</span>
                  <input
                    className="input"
                    value={newName}
                    placeholder="e.g. Broadcasts"
                    maxLength={120}
                    onChange={(e) => setNewName(e.target.value)}
                  />
                </label>
                <button className="btn" type="submit" disabled={busy || !newName.trim()}>
                  Create
                </button>
              </form>
              {profiles.active.profile_version_id && (
                <button
                  className="btn sm ghost"
                  type="button"
                  onClick={() =>
                    setActivating({
                      profileId: profiles.profiles.find((p) => p.versions.some((v) => v.id === profiles.active.profile_version_id))?.id ?? "",
                      versionId: null,
                      rollback: true,
                    })
                  }
                >
                  Roll back to the bundled profile
                </button>
              )}
            </section>
          )}
        </>
      )}

      {view === "edit" &&
        (editing ? (
          <EditorPanel
            key={`${editing.profile.id}/${editing.baseVersionId ?? "bundled"}`}
            profile={editing.profile}
            baseVersionId={editing.baseVersionId}
            baseConfig={editing.baseConfig}
            models={capabilities.models}
            maxChars={profiles.max_stage_chars}
            variables={profiles.variables}
            onDirtyChange={setDirty}
            onSaved={(id) => {
              setDirty(false);
              setTestCandidate(id);
              void load();
              setViewRaw("profiles");
            }}
          />
        ) : (
          <p className="help">Choose “Edit” on a version under Profiles, or create a profile.</p>
        ))}

      {view === "test" && runtime && !runtime.fidelity && (
        <p className="help" data-testid="ai-test-path">
          Test runs always use every spoken language as evidence and check every line before
          writing. New notes here do not do that yet, so a test can differ from a regenerated note.
        </p>
      )}
      {view === "test" && (
        <TestPanel
          view={profiles}
          initialCandidate={testCandidate}
          canEdit={canEdit}
          onStarted={(id) => {
            setCompareExperiment(id);
            void listExperiments().then(setExperiments).catch(() => undefined);
          }}
        />
      )}

      {view === "compare" && (
        <ComparePanel view={profiles} experiments={experiments} initialExperiment={compareExperiment} />
      )}

      {leaving && (
        <ConfirmDialog
          title="Leave without saving?"
          subtitle="Your edits are kept in this browser as a draft until you save or discard them."
          confirmLabel="Leave and keep the draft"
          onCancel={() => setLeaving(null)}
          onConfirm={() => {
            setViewRaw(leaving);
            setLeaving(null);
          }}
        />
      )}

      {activating && (
        <ActivateDialog
          view={profiles}
          activating={activating}
          activeConfig={activeConfig}
          experiments={experiments}
          onDone={async () => {
            setActivating(null);
            await load();
          }}
          onCancel={() => setActivating(null)}
        />
      )}
    </div>
  );
}

function ActivateDialog({
  view,
  activating,
  activeConfig,
  experiments,
  onDone,
  onCancel,
}: {
  view: PromptProfilesView;
  activating: Activating;
  activeConfig: ProfileConfig;
  experiments: ExperimentSummary[];
  onDone: () => Promise<void>;
  onCancel: () => void;
}) {
  const toast = useToast();
  const [config, setConfig] = useState<ProfileConfig | null>(activating.versionId ? null : EMPTY_CONFIG);
  const [evaluation, setEvaluation] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!activating.versionId) return;
    void getVersion(activating.profileId, activating.versionId, "en")
      .then((v) => setConfig(normalise(v.config)))
      .catch((err) => setProblem(messageFor(err)));
  }, [activating]);

  // Evidence: finished tests in which this version ran.
  const evidence = experiments.filter(
    (e) => e.state === "completed" && activating.versionId !== null && e.candidates.includes(activating.versionId),
  );
  const needsEvidence = !activating.rollback && activating.versionId !== null;
  const diff = config ? describeDiff(diffConfigs(activeConfig, config)) : [];

  const confirm = async () => {
    setBusy(true);
    setProblem(null);
    try {
      await activateVersion(activating.profileId, {
        version_id: activating.versionId,
        expected_active_revision: view.active.revision,
        evaluation_ref: evaluation || null,
      });
      toast.success(
        activating.versionId
          ? `${versionLabel(view, activating.versionId)} now writes new notes.`
          : "New notes are written with the bundled profile again.",
      );
      await onDone();
    } catch (err) {
      if (err instanceof ApiError && err.problem.code === "active_revision_conflict") {
        // Someone else moved the pointer: say so, and show the page as it is now.
        toast.error(messageFor(err));
        await onDone();
      } else {
        setProblem(messageFor(err));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <ConfirmDialog
      title={
        activating.versionId
          ? `${activating.rollback ? "Roll back to" : "Activate"} ${versionLabel(view, activating.versionId)}?`
          : "Roll back to the bundled profile?"
      }
      subtitle="Only notes written from now on use it. Existing notes stay as they are, and notes already queued keep the settings they were queued with."
      confirmLabel={activating.rollback ? "Roll back" : "Activate"}
      busy={busy}
      confirmDisabled={needsEvidence && !evaluation}
      error={problem ?? undefined}
      onCancel={onCancel}
      onConfirm={() => void confirm()}
    >
      <p className="help">
        Compared with what is active now: {diff.length ? diff.join(" · ") : config ? "no difference" : "loading…"}
      </p>
      {needsEvidence && (
        <label className="field">
          <span>Evaluation this rests on</span>
          <select className="input" value={evaluation} onChange={(e) => setEvaluation(e.target.value)}>
            <option value="">Choose a finished test of this version</option>
            {evidence.map((e) => (
              <option key={e.id} value={e.id}>
                {new Date(e.created_at).toLocaleString()} — {e.sources} transcript{e.sources === 1 ? "" : "s"} × {e.repetitions}
              </option>
            ))}
          </select>
          {evidence.length === 0 && (
            <span className="help">
              This version has no finished test yet, so it stays a draft. Test it first.
            </span>
          )}
        </label>
      )}
      {needsEvidence && (
        <p className="help">
          The service refuses it if any review found a wrong actor, a missing condition or an
          unsupported claim in this version's output.
        </p>
      )}
    </ConfirmDialog>
  );
}
