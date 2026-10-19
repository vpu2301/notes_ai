import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type {
  AiProcessor,
  AiSettings,
  AiSettingsUpdate,
  ModelParamLimit,
  ModelParams,
  WritingStyle,
} from "../api/types";
import { ConfirmDialog } from "./ConfirmDialog";

const STYLES: ReadonlyArray<readonly [WritingStyle, string, string]> = [
  [
    "business",
    "Business",
    "An executive record of what was said and decided — the notes as they are today.",
  ],
  [
    "formal",
    "Formal",
    "Full forms and no colloquial words; titles and surnames as given; one claim per sentence.",
  ],
  [
    "informal",
    "Informal",
    "Plain, direct wording with short sentences and short headings; no figure tables.",
  ],
  [
    "academic",
    "Academic",
    "Precise and hedged: who argues what, every qualifier kept, figures with their units.",
  ],
];

type Field = keyof ModelParams;

const FIELDS: ReadonlyArray<{ key: Field; label: string; help: string; unit?: string }> = [
  {
    key: "temperature",
    label: "Temperature",
    help: "How freely the writer words a line. 0 = the same wording every time. Higher: more varied phrasing; lines the verifier cannot support are dropped, so notes may get shorter.",
  },
  {
    key: "context_window_tokens",
    label: "Context window",
    unit: "tokens",
    help: "How much of the recording the writer reads at once. Larger: fewer passes, better cross-references, more memory and cost per call.",
  },
  {
    key: "max_output_tokens",
    label: "Output budget per call",
    unit: "tokens",
    help: "The longest answer one writing call may give. Too small cuts sections short; larger costs more.",
  },
  {
    key: "max_concurrency",
    label: "Parallel calls",
    help: "Parallel calls per note. Faster notes, more load on the model.",
  },
  {
    key: "facts_per_window",
    label: "Facts per pass",
    help: "How many facts the reader may take from one pass. Fewer: sharper notes on noisy recordings; more: longer notes.",
  },
  {
    key: "retries",
    label: "Second reading",
    help: "Whether a thin part of the recording is read a second time. Thorough: better coverage, slower.",
  },
  {
    key: "ask_temperature",
    label: "“Ask this note” temperature",
    help: "How freely “Ask this note” answers.",
  },
  {
    key: "ask_max_tokens",
    label: "“Ask this note” answer length",
    unit: "tokens",
    help: "The longest answer “Ask this note” may give.",
  },
];

const RETRIES: Record<string, string> = { off: "Off", standard: "Standard", thorough: "Thorough" };

const fmt = (v: number | string | null | undefined, unit?: string): string =>
  v === null || v === undefined
    ? "Set by the model"
    : typeof v === "number"
      ? `${v.toLocaleString("en-US")}${unit ? ` ${unit}` : ""}`
      : (RETRIES[v] ?? v);

interface Props {
  settings: AiSettings;
  busy: boolean;
  /** `done`: the toast, or one built from the saved settings (to name the new version). */
  onSave: (body: AiSettingsUpdate, done: string | ((saved: AiSettings) => string)) => Promise<void>;
}

/**
 * Settings → Data & AI → Note writing: the writing style (N0) — business is today's notes.
 * When the workspace's note instructions name a style, that one is used and the picker
 * says so; it stays usable (changing it does not change the instructions).
 */
export function WritingStyleCard({
  settings,
  busy,
  onSave,
  overriddenBy = null,
}: Props & { overriddenBy?: string | null }) {
  const style = settings.writing_style ?? "business";
  const editable = settings.can_edit;
  const named = STYLES.find(([v]) => v === overriddenBy)?.[1];
  return (
    <section className="card pad settings-card" aria-label="Writing style">
      <h2 className="settings-h">Writing style</h2>
      <div className="seg" role="group" aria-label="Writing style">
        {STYLES.map(([value, label]) => (
          <button
            key={value}
            type="button"
            className="seg-opt"
            aria-pressed={style === value}
            disabled={!editable || busy}
            onClick={() => {
              if (style !== value)
                void onSave(
                  { writing_style: value },
                  `Notes will be written in the ${label.toLowerCase()} style.`,
                );
            }}
          >
            {label}
          </button>
        ))}
      </div>
      <p className="help">{STYLES.find(([v]) => v === style)?.[2]}</p>
      {named && (
        <p className="help">
          Overridden by your instructions: notes are written in the {named.toLowerCase()} style.
        </p>
      )}
      {!editable && <p className="help">Only a workspace admin can change this.</p>}
    </section>
  );
}

/**
 * Settings → Data & AI → Note writing, behind "Advanced": the model parameters the engine
 * reads, each bounded and capped by the model's own configuration. Members read; admins
 * change. Every change is a new settings version, recorded on the notes it writes.
 */
export function ModelBehaviourCard({ settings, busy, onSave }: Props) {
  const [params] = useSearchParams();
  const saved = settings.model_params;
  const [draft, setDraft] = useState<ModelParams | null>(saved ?? null);
  const [confirmReset, setConfirmReset] = useState(false);
  // A tier change that newly involves a processor needs the admin's agreement first.
  const [pendingTier, setPendingTier] = useState<string | null>(null);
  const unacknowledged = (tier: string): AiProcessor[] =>
    settings.processors.filter((p) => !p.acknowledged && p.tiers.includes(tier));
  const limits = settings.model_params_limits ?? {};
  const effective = settings.model_params_effective;
  const editable = settings.can_edit;

  useEffect(() => setDraft(saved ?? null), [saved]);

  const dirty = !!draft && !!saved && JSON.stringify(draft) !== JSON.stringify(saved);
  const set = <K extends Field>(key: K, value: ModelParams[K]) =>
    setDraft((d) => (d ? { ...d, [key]: value } : d));

  const measured = (t: number): string => {
    const rate = settings.model_params_measured?.temperature?.[t.toFixed(1)];
    if (t === 0) return "";
    return rate === null || rate === undefined
      ? "Not yet measured on the gold set."
      : `Measured on the gold set at ${t.toFixed(1)}: ${Math.round(rate * 100)} % of lines dropped.`;
  };

  const input = (key: Field, limit: ModelParamLimit) => {
    const value = draft?.[key];
    if (key === "retries") {
      return (
        <div className="seg" role="group" aria-label="Second reading">
          {(limit.options ?? []).map((o) => (
            <button
              key={o}
              type="button"
              className="seg-opt"
              aria-pressed={value === o}
              disabled={busy}
              onClick={() => set("retries", o as ModelParams["retries"])}
            >
              {RETRIES[o] ?? o}
            </button>
          ))}
        </div>
      );
    }
    const nullable = key === "context_window_tokens" || key === "max_output_tokens";
    return (
      <span className="param-input">
        {(key === "temperature" || key === "ask_temperature") && (
          <input
            type="range"
            aria-hidden="true"
            tabIndex={-1}
            min={limit.min}
            max={limit.max}
            step={limit.step}
            value={Number(value ?? 0)}
            disabled={busy}
            onChange={(e) => set(key, Number(e.target.value) as never)}
          />
        )}
        <input
          className="input"
          type="number"
          aria-label={FIELDS.find((f) => f.key === key)?.label}
          min={limit.min}
          max={limit.max}
          step={limit.step ?? 1}
          placeholder={nullable ? "Set by the model" : undefined}
          value={value === null || value === undefined ? "" : Number(value)}
          disabled={busy}
          onChange={(e) =>
            set(key, (e.target.value === "" && nullable ? null : Number(e.target.value)) as never)
          }
        />
      </span>
    );
  };

  return (
    <>
      <details
        className="card pad settings-card model-behaviour"
        open={params.get("advanced") === "1"}
      >
        <summary className="settings-h">
          Advanced: model behaviour
          {settings.model_params_version ? (
            <span className="help"> · v{settings.model_params_version}</span>
          ) : null}
        </summary>
        <p className="help">
          The settings the writing model works with. The recommended values are what notes use
          unless you change them; the model's own configuration may cap a value. Extraction and
          every check always run at temperature 0. Reasoning effort is set by the deployment.
        </p>
        <div className="model-tier">
          <h3 className="settings-sub">Quality tier</h3>
          <div className="seg" role="group" aria-label="Model tier">
            {["standard", "premium"].map((tier) => (
              <button
                key={tier}
                type="button"
                className="seg-opt"
                aria-pressed={settings.tier === tier}
                disabled={!editable || busy || (tier === "premium" && !settings.may_choose_premium)}
                onClick={() => {
                  if (settings.tier === tier) return;
                  if (unacknowledged(tier).length > 0) setPendingTier(tier);
                  else void onSave({ tier }, `Notes will be written on the ${tier} tier.`);
                }}
              >
                {tier === "standard" ? "Standard" : "Premium"}
              </button>
            ))}
          </div>
          <p className="help">
            The standard tier writes every note. The premium tier uses a larger model — slower and
            more expensive, and available on the Pro and Enterprise plans.
          </p>
        </div>
        {settings.model_params_valid === false && (
          <p className="banner banner-warn" role="status">
            The saved model settings can no longer be read, so notes use the recommended values.
            Reset needed.
          </p>
        )}
        <table className="param-table">
          <thead>
            <tr>
              <th scope="col">Setting</th>
              <th scope="col">Value</th>
              <th scope="col">Recommended</th>
              <th scope="col">Cap</th>
              <th scope="col">What it does</th>
            </tr>
          </thead>
          <tbody>
            {FIELDS.map(({ key, label, help, unit }) => {
              const limit = limits[key] ?? {};
              const capped =
                limit.cap !== undefined &&
                effective !== undefined &&
                saved !== undefined &&
                (effective[key] !== saved[key] || Number(saved[key]) === limit.cap);
              return (
                <tr key={key}>
                  <th scope="row">{label}</th>
                  <td>
                    {editable ? input(key, limit) : fmt(saved?.[key], unit)}
                    {capped && (
                      <div className="help">
                        capped at {Number(limit.cap).toLocaleString("en-US")} by the model&rsquo;s
                        configuration
                      </div>
                    )}
                  </td>
                  <td>{fmt(limit.default as number | string | null | undefined, unit)}</td>
                  <td>
                    {limit.cap !== undefined ? `${Number(limit.cap).toLocaleString("en-US")} (model)` : "—"}
                  </td>
                  <td className="help">
                    {help}
                    {key === "temperature" && saved ? (
                      <div>{measured(Number(draft?.temperature ?? 0))}</div>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {editable && (
          <div className="settings-actions">
            <button
              type="button"
              className="btn primary"
              disabled={busy || !dirty}
              onClick={() =>
                draft &&
                void onSave(
                  { model_params: draft },
                  (saved) => `Model settings saved (v${saved.model_params_version ?? 0}).`,
                )
              }
            >
              Save model settings
            </button>
            <button
              type="button"
              className="btn ghost"
              disabled={busy}
              onClick={() => setConfirmReset(true)}
            >
              Reset to recommended
            </button>
          </div>
        )}
      </details>

      {pendingTier && (
        <ConfirmDialog
          title={`Switch to the ${pendingTier} tier?`}
          subtitle="This lets new companies process your meetings. They are listed below by name and region."
          confirmLabel="Agree and switch"
          busy={busy}
          onCancel={() => setPendingTier(null)}
          onConfirm={() => {
            const tier = pendingTier;
            setPendingTier(null);
            void onSave(
              {
                tier,
                acknowledge: unacknowledged(tier).map((p) => ({ name: p.name, region: p.region })),
              },
              `Notes will be written on the ${tier} tier.`,
            );
          }}
        >
          <ul className="ack-list">
            {unacknowledged(pendingTier).map((p) => (
              <li key={`${p.name}/${p.region}`}>
                <strong>{p.name}</strong> — {p.region.toUpperCase()} — {p.purpose}
              </li>
            ))}
          </ul>
        </ConfirmDialog>
      )}

      {confirmReset && (
        <ConfirmDialog
          title="Reset the model settings?"
          confirmLabel="Reset"
          busy={busy}
          onConfirm={() => {
            setConfirmReset(false);
            void onSave(
              { reset_model_params: true },
              "Model settings reset to the recommended values.",
            );
          }}
          onCancel={() => setConfirmReset(false)}
        >
          Every setting goes back to its recommended value. Notes already written keep every word
          they have.
        </ConfirmDialog>
      )}
    </>
  );
}
