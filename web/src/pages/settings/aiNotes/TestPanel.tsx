import { useEffect, useMemo, useRef, useState } from "react";
import {
  cancelExperiment,
  estimateExperiment,
  getExperiment,
  getVersion,
  startExperiment,
} from "../../../api/aiNotes";
import { getGeneration } from "../../../api/generation";
import { ApiError } from "../../../api/http";
import { searchNotes } from "../../../api/notes";
import type {
  ExperimentEstimate,
  ExperimentRequest,
  ExperimentView,
  ProfileConfig,
  PromptProfilesView,
  SearchHit,
} from "../../../api/types";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Segmented } from "../../../components/Segmented";
import { useToast } from "../../../components/Toaster";
import { messageFor } from "../../../lib/errorCopy";
import {
  EMPTY_CONFIG,
  LANGUAGES,
  LENGTHS,
  describeDiff,
  diffConfigs,
  moneyOrUnknown,
  newKey,
  normalise,
  versionLabel,
} from "./shared";

interface Source {
  note: SearchHit;
  transcriptRev: number;
  languages: string[];
}

const FINAL = new Set(["completed", "partial", "failed", "cancelled"]);
const MAX_SOURCES = 12;

/** Every version in the workspace, newest first, plus the bundled profile (value ""). */
function versionOptions(view: PromptProfilesView): { value: string; label: string }[] {
  const all = view.profiles.flatMap((p) => p.versions.map((v) => ({ v, p })));
  all.sort((a, b) => b.v.created_at.localeCompare(a.v.created_at));
  return [
    { value: "", label: "Bundled profile" },
    ...all.map(({ v, p }) => ({ value: v.id, label: `${p.name} · v${v.version_number}` })),
  ];
}

/**
 * A/B on fixed transcripts: same sources, same language and length, the configuration
 * the only thing that changes. No note is touched, and ASR is never rerun.
 */
export function TestPanel({
  view,
  initialCandidate,
  canEdit,
  onStarted,
}: {
  view: PromptProfilesView;
  initialCandidate: string | null;
  canEdit: boolean;
  onStarted: (experimentId: string) => void;
}) {
  const toast = useToast();
  const options = useMemo(() => versionOptions(view), [view]);
  const active = view.active.profile_version_id ?? "";
  const newestDraft = options.find((o) => o.value && o.value !== active)?.value ?? "";
  const [baseline, setBaseline] = useState<string>(active);
  const [candidate, setCandidate] = useState<string>(initialCandidate ?? newestDraft);
  const [configs, setConfigs] = useState<Record<string, ProfileConfig>>({});
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [language, setLanguage] = useState<ExperimentRequest["output_language"]>("auto");
  const [length, setLength] = useState<ExperimentRequest["length"]>("standard");
  const [repetitions, setRepetitions] = useState(3);
  const [cap, setCap] = useState("3.00");
  const [estimate, setEstimate] = useState<ExperimentEstimate | null>(null);
  const [experiment, setExperiment] = useState<ExperimentView | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  // One key per intended start: a retry after a network error never doubles a paid run.
  const key = useRef(newKey());

  // The configurations being compared, for the diff.
  useEffect(() => {
    for (const id of [baseline, candidate]) {
      if (!id || configs[id]) continue;
      const profile = view.profiles.find((p) => p.versions.some((v) => v.id === id));
      if (!profile) continue;
      void getVersion(profile.id, id, "en")
        .then((v) => setConfigs((c) => ({ ...c, [id]: normalise(v.config) })))
        .catch(() => undefined);
    }
  }, [baseline, candidate, configs, view.profiles]);

  // While it runs: follow it until it finishes.
  useEffect(() => {
    if (!experiment || FINAL.has(experiment.state)) return;
    const timer = window.setTimeout(() => {
      void getExperiment(experiment.id)
        .then(setExperiment)
        .catch(() => undefined);
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [experiment]);

  const configOf = (id: string): ProfileConfig => (id ? (configs[id] ?? EMPTY_CONFIG) : EMPTY_CONFIG);
  const diff = diffConfigs(configOf(baseline), configOf(candidate));
  const capCents = Math.round(Number(cap) * 100);

  const request = (): ExperimentRequest => ({
    sources: sources.map((s) => ({ note_id: s.note.note_id, transcript_rev: s.transcriptRev })),
    candidate_version_ids: [baseline || null, candidate || null],
    repetitions,
    length,
    output_language: language,
    budget_cap_cents: Number.isFinite(capCents) && capCents >= 0 ? capCents : 0,
    idempotency_key: key.current,
  });

  const search = async () => {
    try {
      setHits((await searchNotes({ q: query, limit: 10 })).hits ?? []);
    } catch (err) {
      toast.error(messageFor(err));
    }
  };

  const add = async (note: SearchHit) => {
    if (sources.some((s) => s.note.note_id === note.note_id) || sources.length >= MAX_SOURCES) return;
    let transcriptRev = 1;
    let languages: string[] = [];
    try {
      const generation = await getGeneration(note.note_id);
      transcriptRev = generation.transcript_rev ?? 1;
      languages = generation.source_languages ?? [];
    } catch {
      // Never written yet: the estimate reports the current revision if this one is stale.
    }
    setSources((s) => [...s, { note, transcriptRev, languages }]);
    setEstimate(null);
  };

  const refreshEstimate = async () => {
    setBusy(true);
    try {
      const found = await estimateExperiment(request());
      setEstimate(found);
      // The service read each transcript: show the revision and languages it would freeze.
      setSources((s) =>
        s.map((src) => {
          const seen = found.sources.find((x) => x.note_id === src.note.note_id);
          return seen ? { ...src, transcriptRev: seen.transcript_rev, languages: seen.languages } : src;
        }),
      );
    } catch (err) {
      if (err instanceof ApiError && err.problem.code === "source_revision_conflict") {
        const rev = Number(err.problem.transcript_rev);
        const noteId = String(err.problem.note_id ?? "");
        setSources((s) => s.map((src) => (src.note.note_id === noteId ? { ...src, transcriptRev: rev } : src)));
      }
      toast.error(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    setBusy(true);
    try {
      const started = await startExperiment(request());
      setExperiment(started);
      key.current = newKey();
      onStarted(started.id);
    } catch (err) {
      toast.error(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (!experiment) return;
    setBusy(true);
    try {
      setExperiment(await cancelExperiment(experiment.id));
      setConfirmCancel(false);
    } catch (err) {
      toast.error(messageFor(err));
    } finally {
      setBusy(false);
    }
  };

  const jobs = sources.length * 2 * repetitions;
  const done = experiment?.runs.filter((r) => r.state === "done").length ?? 0;

  return (
    <div className="settings-stack">
      <section className="card pad settings-card" aria-label="Choose transcripts">
        <h2 className="settings-h">1. Transcripts to test on</h2>
        <p className="help">
          Existing notes you can read, at their current transcript. Speech recognition is not run
          again: both candidates read exactly the same text.
        </p>
        <form
          className="ai-search"
          onSubmit={(e) => {
            e.preventDefault();
            void search();
          }}
        >
          <input
            className="input"
            aria-label="Find a note"
            placeholder="Find a note"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button className="btn sm" type="submit">
            Search
          </button>
        </form>
        {hits.length > 0 && (
          <ul className="ai-hits" aria-label="Notes found">
            {hits.map((h) => (
              <li key={h.note_id}>
                <button className="btn sm ghost" type="button" onClick={() => void add(h)}>
                  Add
                </button>{" "}
                {h.title || h.code}
              </li>
            ))}
          </ul>
        )}
        {sources.length > 0 && (
          <table className="data-table" aria-label="Chosen transcripts">
            <thead>
              <tr>
                <th scope="col">Note</th>
                <th scope="col">Transcript revision</th>
                <th scope="col">Languages spoken</th>
                <th scope="col">
                  <span className="sr-only">Remove</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s.note.note_id}>
                  <th scope="row">{s.note.title || s.note.code}</th>
                  <td>{s.transcriptRev}</td>
                  <td>{s.languages.length ? s.languages.join(", ").toUpperCase() : "—"}</td>
                  <td>
                    <button
                      className="btn sm ghost"
                      type="button"
                      onClick={() => setSources((all) => all.filter((x) => x.note.note_id !== s.note.note_id))}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card pad settings-card" aria-label="Choose what to compare">
        <h2 className="settings-h">2. What to compare</h2>
        <div className="ai-editor-row">
          <label className="field">
            <span>Baseline (A)</span>
            <select className="input" value={baseline} onChange={(e) => setBaseline(e.target.value)}>
              {options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                  {o.value === active ? " (active)" : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Candidate (B)</span>
            <select className="input" value={candidate} onChange={(e) => setCandidate(e.target.value)}>
              {options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                  {o.value === active ? " (active)" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="ai-diff-summary" aria-label="What differs">
          {baseline === candidate ? (
            <p className="help">Both sides are the same version: this measures run-to-run variation only.</p>
          ) : diff.empty ? (
            <p className="help">The two versions have the same configuration.</p>
          ) : (
            <>
              <p className="help">Differs in: {describeDiff(diff).join(" · ")}</p>
              {diff.multiple && (
                <p className="banner banner-warn" role="status">
                  Multiple variables changed. A difference in the results cannot be attributed to
                  one of them.
                </p>
              )}
            </>
          )}
        </div>
        <p className="help">
          A: {versionLabel(view, baseline || null)} · B: {versionLabel(view, candidate || null)}
        </p>
      </section>

      <section className="card pad settings-card" aria-label="Run settings">
        <h2 className="settings-h">3. Run settings</h2>
        <div className="ai-editor-row">
          <label className="field">
            <span>Output language</span>
            <select
              className="input"
              value={language}
              onChange={(e) => setLanguage(e.target.value as ExperimentRequest["output_language"])}
            >
              {LANGUAGES.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
          </label>
          <div className="field">
            <span>Length</span>
            <Segmented label="Length" options={LENGTHS} value={length} onChange={setLength} />
          </div>
          <label className="field">
            <span>Repetitions</span>
            <select className="input" value={repetitions} onChange={(e) => setRepetitions(Number(e.target.value))}>
              {[1, 2, 3].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Spending limit (USD)</span>
            <input className="input" inputMode="decimal" value={cap} onChange={(e) => setCap(e.target.value)} />
          </label>
        </div>
        <p className="help" data-testid="ai-jobs">
          {jobs} runs ({sources.length} transcript{sources.length === 1 ? "" : "s"} × 2 × {repetitions}).
          {estimate
            ? ` Estimated cost: ${moneyOrUnknown(estimate.estimate_cents)}${
                estimate.cost_known ? "" : " — a model has no price, so the run is limited by tokens instead"
              }.`
            : ""}
        </p>
        <div className="row-actions">
          <button
            className="btn sm"
            type="button"
            disabled={!canEdit || busy || sources.length === 0}
            onClick={() => void refreshEstimate()}
          >
            Estimate
          </button>
          <button
            className="btn sm primary"
            type="button"
            disabled={!canEdit || busy || sources.length === 0 || !estimate}
            onClick={() => void start()}
          >
            Start test
          </button>
        </div>
        {!canEdit && <p className="help">Only a workspace admin can run tests.</p>}
      </section>

      {experiment && (
        <section className="card pad settings-card" aria-label="Test status" aria-live="polite">
          <h2 className="settings-h">Status: {experiment.state}</h2>
          <p className="help">
            {done} of {experiment.runs.length} runs done · spent {moneyOrUnknown(experiment.cost_known ? experiment.spent_cents : null)}
            {experiment.stale ? " · a transcript changed since this test was queued" : ""}
          </p>
          {!FINAL.has(experiment.state) && canEdit && (
            <button className="btn sm" type="button" disabled={busy} onClick={() => setConfirmCancel(true)}>
              Cancel test
            </button>
          )}
        </section>
      )}

      {confirmCancel && (
        <ConfirmDialog
          title="Cancel this test?"
          subtitle="Runs that have not started will not start. A run already in progress may finish, and its cost is still counted. Finished results are kept."
          confirmLabel="Cancel test"
          confirmDanger
          busy={busy}
          onCancel={() => setConfirmCancel(false)}
          onConfirm={() => void cancel()}
        />
      )}
    </div>
  );
}
