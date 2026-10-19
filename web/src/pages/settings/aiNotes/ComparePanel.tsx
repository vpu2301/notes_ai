import { useEffect, useMemo, useRef, useState } from "react";
import { getExperiment, getRunArtifact, submitReview } from "../../../api/aiNotes";
import type {
  ArtifactFact,
  ExperimentRun,
  ExperimentSummary,
  ExperimentView,
  FindingLabel,
  PromptProfilesView,
  ReviewRequest,
  RunArtifact,
} from "../../../api/types";
import { useToast } from "../../../components/Toaster";
import { messageFor } from "../../../lib/errorCopy";
import { STAGE_LABELS, mmss, moneyOrUnknown, versionLabel } from "./shared";

const FINDINGS: { value: FindingLabel; label: string }[] = [
  { value: "wrong_actor", label: "Wrong actor" },
  { value: "missing_condition", label: "Missing condition" },
  { value: "unsupported_claim", label: "Unsupported claim" },
  { value: "omission", label: "Omission" },
  { value: "duplicate", label: "Duplicate" },
  { value: "unclear_attribution", label: "Unclear attribution" },
];

const PREFERENCES: { value: ReviewRequest["preference"]; label: string }[] = [
  { value: "a", label: "1 is better" },
  { value: "b", label: "2 is better" },
  { value: "tie", label: "Tie" },
  { value: "neither", label: "Neither is acceptable" },
];

interface Pair {
  key: string;
  source: number;
  repetition: number;
  a: ExperimentRun;
  b: ExperimentRun;
}

function pairsOf(experiment: ExperimentView): Pair[] {
  const out: Pair[] = [];
  for (const a of experiment.runs.filter((r) => r.candidate_index === 0)) {
    const b = experiment.runs.find(
      (r) => r.candidate_index === 1 && r.source_index === a.source_index && r.repetition === a.repetition,
    );
    if (b) out.push({ key: `${a.source_index}/${a.repetition}`, source: a.source_index, repetition: a.repetition, a, b });
  }
  return out;
}

/**
 * Side by side on the same transcript: a blind review by default (order shuffled per
 * pair, identities hidden until the reviewer submits or chooses to reveal), each line
 * opening its original-language evidence, and every repeat's numbers with their limits.
 */
export function ComparePanel({
  view,
  experiments,
  initialExperiment,
}: {
  view: PromptProfilesView;
  experiments: ExperimentSummary[];
  initialExperiment: string | null;
}) {
  const toast = useToast();
  const [experimentId, setExperimentId] = useState<string | null>(initialExperiment ?? experiments[0]?.id ?? null);
  const [experiment, setExperiment] = useState<ExperimentView | null>(null);
  const [pairKey, setPairKey] = useState<string | null>(null);
  const [blind, setBlind] = useState(true);
  const [revealed, setRevealed] = useState(false);
  // Decided once per pair and kept for the session: which candidate shows as "1".
  const swapped = useRef<Record<string, boolean>>({}).current;
  const [artifacts, setArtifacts] = useState<Record<string, RunArtifact | "unavailable">>({});
  const [selectedLine, setSelectedLine] = useState<{ side: 1 | 2; factIds: string[] } | null>(null);
  const [preference, setPreference] = useState<ReviewRequest["preference"] | null>(null);
  const [findings, setFindings] = useState<Record<string, boolean>>({});
  const [comment, setComment] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [pane, setPane] = useState<"source" | "1" | "2">("1");

  useEffect(() => {
    if (!experimentId) return;
    void getExperiment(experimentId)
      .then((e) => {
        setExperiment(e);
        setPairKey(pairsOf(e)[0]?.key ?? null);
      })
      .catch((err) => toast.error(messageFor(err)));
  }, [experimentId, toast]);

  const pairs = useMemo(() => (experiment ? pairsOf(experiment) : []), [experiment]);
  const pair = pairs.find((p) => p.key === pairKey) ?? null;
  if (pair && swapped[pair.key] === undefined) swapped[pair.key] = Math.random() < 0.5;
  const shownFirst = pair ? (swapped[pair.key] ? pair.b : pair.a) : null;
  const shownSecond = pair ? (swapped[pair.key] ? pair.a : pair.b) : null;
  const identityVisible = !blind || revealed || submitted;

  useEffect(() => {
    if (!experiment || !pair) return;
    for (const run of [pair.a, pair.b]) {
      if (artifacts[run.id] || !run.artifact_available) continue;
      void getRunArtifact(experiment.id, run.id)
        .then((a) => setArtifacts((all) => ({ ...all, [run.id]: a })))
        .catch(() => setArtifacts((all) => ({ ...all, [run.id]: "unavailable" })));
    }
  }, [experiment, pair, artifacts]);

  useEffect(() => {
    setPreference(null);
    setFindings({});
    setComment("");
    setSubmitted(false);
    setRevealed(false);
    setSelectedLine(null);
  }, [pairKey]);

  if (experiments.length === 0) {
    return <p className="help">No tests yet. Start one under Test.</p>;
  }

  const candidateName = (run: ExperimentRun | null) =>
    run ? versionLabel(view, experiment?.candidates[run.candidate_index] ?? null) : "";

  const submit = async () => {
    if (!experiment || !shownFirst || !shownSecond || !preference) return;
    try {
      await submitReview(experiment.id, {
        run_a_id: shownFirst.id,
        run_b_id: shownSecond.id,
        blind,
        revealed,
        preference,
        findings: Object.entries(findings)
          .filter(([, on]) => on)
          .map(([k]) => {
            const [side, label] = k.split(":") as ["1" | "2", FindingLabel];
            return { run: side === "1" ? "a" : "b", label };
          }),
        comment,
      });
      setSubmitted(true);
      toast.success("Review saved.");
    } catch (err) {
      toast.error(messageFor(err));
    }
  };

  const artifactOf = (run: ExperimentRun | null): RunArtifact | "unavailable" | null =>
    run ? (artifacts[run.id] ?? (run.artifact_available ? null : "unavailable")) : null;
  const evidence: ArtifactFact[] = (() => {
    if (!selectedLine) return [];
    const run = selectedLine.side === 1 ? shownFirst : shownSecond;
    const art = artifactOf(run);
    if (!art || art === "unavailable") return [];
    return art.facts.filter((f) => selectedLine.factIds.includes(f.item_key));
  })();

  return (
    <div className="settings-stack">
      <section className="card pad settings-card" aria-label="Choose a test">
        <div className="ai-editor-row">
          <label className="field">
            <span>Test</span>
            <select className="input" value={experimentId ?? ""} onChange={(e) => setExperimentId(e.target.value)}>
              {experiments.map((e) => (
                <option key={e.id} value={e.id}>
                  {new Date(e.created_at).toLocaleString()} · {e.state} · {e.sources} transcript
                  {e.sources === 1 ? "" : "s"} × {e.repetitions}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Transcript and repetition</span>
            <select className="input" value={pairKey ?? ""} onChange={(e) => setPairKey(e.target.value)}>
              {pairs.map((p) => (
                <option key={p.key} value={p.key}>
                  Transcript {p.source + 1}, run {p.repetition}
                </option>
              ))}
            </select>
          </label>
          <label className="chk-row">
            <input
              type="checkbox"
              checked={blind}
              disabled={submitted}
              onChange={(e) => setBlind(e.target.checked)}
            />
            Blind review
          </label>
        </div>
        {experiment?.stale && (
          <p className="banner banner-warn" role="status">
            A transcript changed after this test ran. It no longer counts as evidence for activating
            a version.
          </p>
        )}
      </section>

      {pair && (
        <section className="card pad settings-card ai-compare" aria-label="Side by side">
          <div className="ai-compare-tabs" role="tablist" aria-label="Show">
            {(["source", "1", "2"] as const).map((p) => (
              <button
                key={p}
                type="button"
                role="tab"
                aria-selected={pane === p}
                className="seg-opt"
                onClick={() => setPane(p)}
              >
                {p === "source" ? "Evidence" : `Output ${p}`}
              </button>
            ))}
          </div>
          <div className="ai-compare-grid">
            <aside className="ai-pane" data-shown={pane === "source"} aria-label="Evidence">
              <h3 className="settings-h">Evidence</h3>
              {evidence.length === 0 ? (
                <p className="help">Choose a line to see what was said, in the language it was said in.</p>
              ) : (
                evidence.map((f) => (
                  <figure key={f.item_key} className="ai-evidence">
                    <blockquote lang={f.source_language ?? undefined}>{f.quote}</blockquote>
                    <figcaption className="help">
                      Original{f.source_language ? ` · ${f.source_language.toUpperCase()}` : ""} ·{" "}
                      {mmss(f.start_ms)}–{mmss(f.end_ms)}
                      {f.attributed_to ? ` · held by ${f.attributed_to}` : ""}
                      {f.flags.includes("meaning_unverified") ? " · needs review" : ""}
                    </figcaption>
                  </figure>
                ))
              )}
            </aside>
            {([shownFirst, shownSecond] as const).map((run, i) => {
              const side = (i + 1) as 1 | 2;
              const art = artifactOf(run);
              return (
                <article
                  key={side}
                  className="ai-pane"
                  data-shown={pane === String(side)}
                  aria-label={`Output ${side}`}
                >
                  <h3 className="settings-h">
                    Output {side}
                    {identityVisible ? ` — ${candidateName(run)}` : ""}
                  </h3>
                  {art === null && <p className="help">Loading…</p>}
                  {art === "unavailable" && (
                    <p className="help">
                      {run?.state === "done"
                        ? "You can no longer read this transcript, so its output is hidden."
                        : `This run ${run?.state ?? "did not run"}.`}
                    </p>
                  )}
                  {art &&
                    art !== "unavailable" &&
                    art.sections.map((s) => (
                      <div key={s.section_key}>
                        {s.title && <h4 className="ai-topic">{s.title}</h4>}
                        {s.lines
                          .filter((l) => l.kind !== "heading")
                          .map((l, n) => (
                            <button
                              key={`${s.section_key}-${n}`}
                              type="button"
                              className="ai-line"
                              aria-pressed={
                                selectedLine?.side === side && selectedLine.factIds.join() === l.fact_ids.join()
                              }
                              disabled={l.fact_ids.length === 0}
                              onClick={() => {
                                setSelectedLine({ side, factIds: l.fact_ids });
                                setPane("source");
                              }}
                            >
                              {l.text}
                            </button>
                          ))}
                      </div>
                    ))}
                </article>
              );
            })}
          </div>

          <fieldset className="ai-review" disabled={submitted}>
            <legend className="settings-h">Your review</legend>
            <div className="seg" role="group" aria-label="Preference">
              {PREFERENCES.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  className="seg-opt"
                  aria-pressed={preference === p.value}
                  onClick={() => setPreference(p.value)}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <p className="help">Style preference and factual errors are recorded separately.</p>
            <div className="ai-findings">
              {(["1", "2"] as const).map((side) => (
                <div key={side} role="group" aria-label={`Factual errors in output ${side}`}>
                  <strong>Output {side}</strong>
                  {FINDINGS.map((f) => (
                    <label key={f.value} className="chk-row">
                      <input
                        type="checkbox"
                        checked={!!findings[`${side}:${f.value}`]}
                        onChange={(e) => setFindings((all) => ({ ...all, [`${side}:${f.value}`]: e.target.checked }))}
                      />
                      {f.label}
                    </label>
                  ))}
                </div>
              ))}
            </div>
            <label className="field">
              <span>Comment (may quote the recording; only people who can read it see it)</span>
              <textarea className="input" rows={3} value={comment} onChange={(e) => setComment(e.target.value)} />
            </label>
            <div className="row-actions">
              {blind && !revealed && !submitted && (
                <button className="btn sm ghost" type="button" onClick={() => setRevealed(true)}>
                  Reveal which is which
                </button>
              )}
              <button className="btn sm primary" type="button" disabled={!preference} onClick={() => void submit()}>
                Submit review
              </button>
            </div>
            {blind && revealed && !submitted && (
              <p className="help">Revealed before submitting: the review is stored as not blind-preserved.</p>
            )}
          </fieldset>
        </section>
      )}

      {experiment && (
        <section className="card pad settings-card" aria-label="Every run">
          <h2 className="settings-h">Every run</h2>
          <p className="help">
            Factual accuracy (weighted recall, duplicate rate) is <strong>not measured</strong>: these
            notes have no reference annotations. The counts below are automated, not a quality score.
          </p>
          <div className="ai-table-wrap">
            <table className="data-table" aria-label="Runs">
              <thead>
                <tr>
                  <th scope="col">Version</th>
                  <th scope="col">Transcript</th>
                  <th scope="col">Run</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Time</th>
                  <th scope="col">Models used (calls)</th>
                  <th scope="col">Tokens</th>
                  <th scope="col">Meaning checks</th>
                  <th scope="col">Final check</th>
                  <th scope="col">Unverified / fallback</th>
                  <th scope="col">Clean comparison</th>
                  <th scope="col">Profile hash</th>
                  <th scope="col">Cost</th>
                </tr>
              </thead>
              <tbody>
                {experiment.runs.map((r) => (
                  <tr key={r.id}>
                    <th scope="row">{identityVisible ? candidateName(r) : "hidden"}</th>
                    <td>
                      {r.source_index + 1}
                      <span className="help"> (rev {experiment.sources[r.source_index]?.transcript_rev ?? "?"})</span>
                    </td>
                    <td>{r.repetition}</td>
                    <td>
                      {r.state}
                      {r.metrics.partial ? " (partial)" : ""}
                      {r.error_kind ? ` — ${r.error_kind}` : ""}
                    </td>
                    <td>{r.latency_ms !== null ? `${(r.latency_ms / 1000).toFixed(0)} s` : "—"}</td>
                    <td>
                      {identityVisible
                        ? (r.metrics.calls ?? [])
                            .map((c) => `${STAGE_LABELS[c.stage] ?? c.stage}: ${c.model_id} (${c.calls}${c.failed ? `, ${c.failed} failed` : ""})`)
                            .join("; ") || "—"
                        : "hidden"}
                    </td>
                    <td>{r.metrics.tokens ?? "—"}</td>
                    <td>
                      {Object.entries(r.metrics.meaning_check ?? {})
                        .filter(([k]) => ["supported", "contradicted", "repaired", "unavailable"].includes(k))
                        .map(([k, v]) => `${k} ${v}`)
                        .join(", ") || "—"}
                    </td>
                    <td>
                      {(() => {
                        const f = r.metrics.final_check as Record<string, number | boolean> | undefined;
                        if (!f || !f.ran) return "not run";
                        return `${f.supported ?? 0} supported, ${f.repaired ?? 0} repaired, ${f.restored ?? 0} restored, ${
                          f.unverified ?? 0
                        } held for review`;
                      })()}
                    </td>
                    <td>
                      {r.metrics.meaning_unverified ?? 0}
                      {r.metrics.summary_fallback || r.metrics.topics_fallback ? " · fallback" : ""}
                    </td>
                    <td>
                      {r.metrics.clean === undefined
                        ? "—"
                        : r.metrics.clean
                          ? "yes"
                          : `no — ${((r.metrics.unclean_reasons as string[] | undefined) ?? []).join("; ")}`}
                    </td>
                    <td>
                      {identityVisible ? String((r.config as { content_hash?: string }).content_hash ?? "").slice(0, 10) : "hidden"}
                    </td>
                    <td>{experiment.cost_known ? moneyOrUnknown(r.cost_cents) : "unknown"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
