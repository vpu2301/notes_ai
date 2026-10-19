import { useCallback, useEffect, useMemo, useState } from "react";
import { previewDraft, saveVersion } from "../../../api/aiNotes";
import { ApiError } from "../../../api/http";
import type {
  ModelCapability,
  PreviewFlags,
  PreviewMode,
  ProfileConfig,
  ProfileProblem,
  ProfileStage,
  PromptProfile,
  ResolvedCall,
  StageParams,
} from "../../../api/types";
import { Segmented } from "../../../components/Segmented";
import { useToast } from "../../../components/Toaster";
import { messageFor } from "../../../lib/errorCopy";
import {
  CALL_LABELS,
  LANGUAGES,
  LENGTHS,
  SOURCE_LABELS,
  STAGE_HELP,
  STAGE_LABELS,
  STAGES,
  dropDraft,
  lineDiff,
  loadDraft,
  normalise,
  storeDraft,
} from "./shared";

const PARAMS: { key: keyof StageParams; label: string; step: string }[] = [
  { key: "temperature", label: "Temperature", step: "0.1" },
  { key: "max_output_tokens", label: "Output tokens (max)", step: "64" },
  { key: "timeout_s", label: "Timeout (s)", step: "5" },
];

/** An emptied stage means "use the bundled instructions" (null), never an empty override. */
function withBlanksBundled(config: ProfileConfig): ProfileConfig {
  const stages = Object.fromEntries(
    Object.entries(config.stages).map(([k, v]) => [k, v !== null && v !== undefined && !v.trim() ? null : v]),
  ) as ProfileConfig["stages"];
  return { ...config, stages };
}

/**
 * Edit a profile as a new version. The browser keeps the unsaved draft (it survives a
 * reload); Save creates an immutable version and never changes what writes notes now.
 */
export function EditorPanel({
  profile,
  baseVersionId,
  baseConfig,
  models,
  maxChars,
  variables,
  onSaved,
  onDirtyChange,
}: {
  profile: PromptProfile;
  baseVersionId: string | null;
  baseConfig: ProfileConfig;
  models: ModelCapability[];
  maxChars: number;
  variables: string[];
  onSaved: (versionId: string) => void;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const toast = useToast();
  const restored = loadDraft(profile.id);
  const [config, setConfig] = useState<ProfileConfig>(() =>
    normalise(restored && restored.baseVersionId === baseVersionId ? restored.config : baseConfig),
  );
  const [stage, setStage] = useState<ProfileStage>("extraction");
  const [problems, setProblems] = useState<ProfileProblem[]>([]);
  const [bundled, setBundled] = useState<Partial<Record<ProfileStage, string>>>({});
  const [effective, setEffective] = useState<Partial<Record<ProfileStage, string>> | null>(null);
  const [previewLanguage, setPreviewLanguage] = useState<"en" | "de" | "uk">("en");
  const [previewMode, setPreviewMode] = useState<PreviewMode>("production");
  const [calls, setCalls] = useState<ResolvedCall[]>([]);
  const [flags, setFlags] = useState<PreviewFlags | null>(null);
  const [required, setRequired] = useState<Partial<Record<ProfileStage, string[]>>>({});
  const [busy, setBusy] = useState(false);
  const [showDiff, setShowDiff] = useState(false);

  const dirty = useMemo(() => JSON.stringify(config) !== JSON.stringify(normalise(baseConfig)), [config, baseConfig]);
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);
  useEffect(() => {
    if (dirty) storeDraft({ profileId: profile.id, baseVersionId, config });
  }, [config, dirty, profile.id, baseVersionId]);

  const refresh = useCallback(
    async (language: string, mode: PreviewMode) => {
      try {
        const preview = await previewDraft(withBlanksBundled(config), language, mode);
        setProblems(preview.problems);
        setEffective(preview.effective);
        setBundled(preview.bundled);
        setCalls(preview.calls ?? []);
        setFlags(preview.flags ?? null);
        setRequired(preview.required_variables ?? {});
      } catch (err) {
        toast.error(messageFor(err));
      }
    },
    [config, toast],
  );

  // The bundled texts are where an edit starts: loaded once with the first preview.
  useEffect(() => {
    void refresh(previewLanguage, previewMode);
    // Only on mount and when the preview language or mode changes; edits preview on request.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [previewLanguage, previewMode]);

  const text = config.stages[stage];
  // Emptied by hand: the bundled instructions apply (saved as null), and the field says so.
  const emptied = text !== null && text !== undefined && !text.trim();
  const shown = text ?? bundled[stage] ?? "";
  const stageProblems = problems.filter((p) => p.field.startsWith(`stages.${stage}`));
  const modelName = config.models[stage] ?? null;
  const capability =
    models.find((m) => m.backend === modelName) ?? (modelName === null ? models[0] : undefined);
  const params = config.params[stage] ?? {};

  const setStageText = (value: string | null) =>
    setConfig((c) => ({ ...c, stages: { ...c.stages, [stage]: value } }));
  const setParam = (key: keyof StageParams, value: number | null) =>
    setConfig((c) => {
      const next = { ...(c.params[stage] ?? {}), [key]: value };
      if (value === null) delete next[key];
      return { ...c, params: { ...c.params, [stage]: next } };
    });

  const save = async () => {
    setBusy(true);
    try {
      const saved = await saveVersion(profile.id, withBlanksBundled(config));
      dropDraft(profile.id);
      setProblems([]);
      toast.success(`Saved as version ${saved.version_number}. It is not active — test it, then activate.`);
      onSaved(saved.id);
    } catch (err) {
      if (err instanceof ApiError && Array.isArray(err.problem.problems)) {
        setProblems(err.problem.problems as ProfileProblem[]);
      }
      toast.error(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const discard = () => {
    dropDraft(profile.id);
    setConfig(normalise(baseConfig));
    setProblems([]);
  };

  const diff = lineDiff(baseConfig.stages[stage] ?? bundled[stage] ?? "", shown);

  return (
    <section className="card pad settings-card ai-editor" aria-label="Edit profile">
      <div className="settings-card-h">
        <h2 className="settings-h">
          {profile.name} — new version{baseVersionId ? "" : " (from the bundled profile)"}
        </h2>
        <div className="row-actions">
          {dirty && <span className="help">Unsaved changes</span>}
          <button className="btn sm" type="button" disabled={!dirty || busy} onClick={discard}>
            Discard
          </button>
          <button className="btn sm primary" type="button" disabled={!dirty || busy} onClick={() => void save()}>
            Save as new version
          </button>
        </div>
      </div>

      <div className="ai-editor-row">
        <label className="field">
          <span>Output language</span>
          <select
            className="input"
            value={config.output_language}
            onChange={(e) => setConfig((c) => ({ ...c, output_language: e.target.value as ProfileConfig["output_language"] }))}
          >
            {LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
        <div className="field">
          <span>Default length</span>
          <Segmented
            label="Default length"
            options={LENGTHS}
            value={config.length}
            onChange={(length) => setConfig((c) => ({ ...c, length }))}
          />
        </div>
      </div>
      <p className="help">
        The note is written in this language; every language spoken in the recording is still
        used as evidence, and quotes stay in the language they were spoken in.
      </p>

      <Segmented
        label="Stage"
        options={STAGES.map((s) => ({ value: s, label: STAGE_LABELS[s] }))}
        value={stage}
        onChange={setStage}
      />
      <p className="help">{STAGE_HELP[stage]}</p>

      <label className="field">
        <span>
          {STAGE_LABELS[stage]} instructions{" "}
          {text === null || text === undefined ? "(bundled)" : emptied ? "(empty: bundled will be used)" : "(edited)"}
        </span>
        <textarea
          className="input ai-stage-text"
          aria-label={`${STAGE_LABELS[stage]} instructions`}
          aria-invalid={stageProblems.length > 0}
          aria-describedby={`ai-stage-${stage}-count`}
          value={shown}
          rows={14}
          onChange={(e) => setStageText(e.target.value)}
        />
      </label>
      {emptied && (
        <p className="help" role="status">
          This stage is empty, so it will use the bundled instructions — nothing is sent empty.
        </p>
      )}
      {(required[stage] ?? []).length > 0 && (
        <p className="help">
          Keep {(required[stage] ?? []).map((v) => `{{${v}}}`).join(", ")}: the bundled text uses{" "}
          {(required[stage] ?? []).length === 1 ? "it" : "them"}, and the version is refused without.
        </p>
      )}
      <div className="ai-stage-meta">
        <span id={`ai-stage-${stage}-count`} className={shown.length > maxChars ? "danger-text" : "help"}>
          {shown.length.toLocaleString()} / {maxChars.toLocaleString()} characters
        </span>
        <span className="help">
          Placeholders: {variables.map((v) => `{{${v}}}`).join(", ")}. Anything else in {"{{ }}"} is refused.
        </span>
        <button
          className="btn sm ghost"
          type="button"
          disabled={text === null || text === undefined}
          onClick={() => setStageText(null)}
        >
          Use bundled instructions
        </button>
        <button className="btn sm ghost" type="button" aria-expanded={showDiff} onClick={() => setShowDiff((v) => !v)}>
          {showDiff ? "Hide changes" : "Changes against the base version"}
        </button>
      </div>
      {stageProblems.length > 0 && (
        <ul className="ai-problems" role="alert">
          {stageProblems.map((p) => (
            <li key={`${p.field}-${p.code}`} className="danger-text">
              {p.detail}
            </li>
          ))}
        </ul>
      )}
      {showDiff && (
        <div className="ai-diff" aria-label="Changes against the base version">
          {diff.removed.length + diff.added.length === 0 ? (
            <p className="help">No changes in this stage.</p>
          ) : (
            <>
              {diff.removed.map((l, i) => (
                <div key={`r${i}`} className="ai-diff-removed">
                  − {l}
                </div>
              ))}
              {diff.added.map((l, i) => (
                <div key={`a${i}`} className="ai-diff-added">
                  + {l}
                </div>
              ))}
            </>
          )}
        </div>
      )}

      <div className="ai-editor-row">
        <label className="field">
          <span>Model for {STAGE_LABELS[stage].toLowerCase()}</span>
          <select
            className="input"
            value={modelName ?? ""}
            onChange={(e) =>
              setConfig((c) => ({ ...c, models: { ...c.models, [stage]: e.target.value || null } }))
            }
          >
            <option value="">Workspace routing (default)</option>
            {models.map((m) => (
              <option key={m.backend} value={m.backend}>
                {m.processor ? `${m.processor} (${m.region})` : m.backend} · {m.model_id}
                {m.acknowledged ? "" : " — needs an admin's agreement"}
              </option>
            ))}
          </select>
        </label>
        {PARAMS.map(({ key, label, step }) => {
          const bounds = capability?.supported[key as keyof ModelCapability["supported"]];
          const value = params[key];
          return (
            <label key={key} className="field">
              <span>{label}</span>
              <input
                className="input"
                type="number"
                step={step}
                min={bounds?.min}
                max={bounds?.max}
                disabled={!bounds}
                title={bounds ? `${bounds.min}–${bounds.max}` : "This model does not take this setting"}
                aria-invalid={problems.some((p) => p.field === `params.${stage}.${key}`)}
                value={value ?? ""}
                placeholder={bounds ? "default" : "not supported"}
                onChange={(e) => setParam(key, e.target.value === "" ? null : Number(e.target.value))}
              />
            </label>
          );
        })}
      </div>
      {capability && Object.keys(capability.unsupported).length > 0 && (
        <p className="help">
          Not available for this model:{" "}
          {Object.entries(capability.unsupported)
            .map(([k, why]) => `${k} (${why})`)
            .join("; ")}
          .
        </p>
      )}
      {problems
        .filter((p) => p.field.startsWith(`params.${stage}`) || p.field.startsWith(`models.${stage}`))
        .map((p) => (
          <p key={`${p.field}-${p.code}`} className="danger-text" role="alert">
            {p.detail}
          </p>
        ))}

      <details className="ai-preview">
        <summary>Effective instructions (exactly what each call sends)</summary>
        <div className="ai-preview-head">
          <Segmented
            label="Preview for"
            options={[
              { value: "production", label: "New notes here" },
              { value: "test", label: "Test runs" },
            ]}
            value={previewMode}
            onChange={setPreviewMode}
          />
          <Segmented
            label="Preview language"
            options={[
              { value: "en", label: "English" },
              { value: "de", label: "German" },
              { value: "uk", label: "Ukrainian" },
            ]}
            value={previewLanguage}
            onChange={setPreviewLanguage}
          />
          <button className="btn sm" type="button" onClick={() => void refresh(previewLanguage, previewMode)}>
            Refresh preview
          </button>
        </div>
        {flags && (
          <p className="help" data-testid="ai-preview-flags">
            {flags.profile_instructions_apply === false
              ? "New notes here run the previous engine: this version's instructions are not sent, and no line is checked before saving."
              : `Multilingual evidence on · meaning checks ${flags.fidelity ? "on" : "off"} · final check ${
                  flags.final_check ? "on" : "off"
                }`}
            {flags.small_model ? " · small-model profile (bullets and heading in separate calls)" : ""}
          </p>
        )}
        <p className="help">
          The same resolver feeds this preview, test runs and new notes; each run records the
          hash of every request it sent, to compare with these. The service always adds the
          contract (output format, and that the transcript is data, not instructions). A
          preview is not a test: nothing has run on this configuration.
        </p>
        {calls.length === 0 ? (
          <pre className="ai-preview-text" aria-label={`Effective ${STAGE_LABELS[stage]} instructions`}>
            {effective?.[stage] ?? "Fix the problems above to see the preview."}
          </pre>
        ) : (
          <>
            {calls
              .filter((c) => c.stage === stage)
              .map((c) => (
                <PreviewCall key={c.call} call={c} />
              ))}
            <details className="ai-preview-code">
              <summary>Code-owned rules (read-only)</summary>
              <p className="help">
                Common rules, conversation context, merging repeated points and the participant
                check are owned by the service and versioned with it. They cannot be changed in
                Settings.
              </p>
              {calls
                .filter((c) => c.source === "code")
                .map((c) => (
                  <PreviewCall key={c.call} call={c} />
                ))}
            </details>
          </>
        )}
      </details>
    </section>
  );
}

function PreviewCall({ call }: { call: ResolvedCall }) {
  return (
    <div className="ai-preview-call">
      <div className="ai-preview-call-h">
        <strong>{CALL_LABELS[call.call] ?? call.call}</strong>
        <span className="help">
          {SOURCE_LABELS[call.source] ?? call.source} · sha {call.sha.slice(0, 12)}
        </span>
      </div>
      <pre className="ai-preview-text" aria-label={`${CALL_LABELS[call.call] ?? call.call} instructions`}>
        {call.system}
      </pre>
    </div>
  );
}
