import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  listRuns,
  overview,
  type Overview,
  type RunFilters,
  type RunStatus,
  type RunSummary,
} from "../../api/telemetry";
import { EmptyState } from "../../components/EmptyState";
import { DownloadIcon, LayersIcon } from "../../components/icons";
import { Select } from "../../components/Select";
import { Skeleton } from "../../components/Skeleton";
import { StatusBadge } from "../../components/StatusBadge";
import { useToast } from "../../components/Toaster";
import { downloadDiagnostics } from "../../lib/diagnostics";
import { messageFor } from "../../lib/errorCopy";
import { useDocumentTitle } from "../../lib/useDocumentTitle";
import { percent, ratio, RequirePlatformAdmin, seconds, shortId, when } from "./telemetryShared";

const PERIODS = { "24h": 1, "7d": 7, "30d": 30 } as const;
type Period = keyof typeof PERIODS;
const STATUSES: Array<RunStatus | ""> = [
  "",
  "succeeded",
  "partial",
  "failed",
  "cancelled",
  "running",
  "queued",
];

/** `/admin/dashboard` — pipeline telemetry across every workspace. Numbers only. */
export function TelemetryDashboardPage() {
  useDocumentTitle("Telemetry");
  return (
    <RequirePlatformAdmin>
      <Dashboard />
    </RequirePlatformAdmin>
  );
}

function Dashboard() {
  const toast = useToast();
  const [period, setPeriod] = useState<Period>("7d");
  const [status, setStatus] = useState<RunStatus | "">("");
  const [search, setSearch] = useState("");
  const [stats, setStats] = useState<Overview | null>(null);
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const range = useMemo(() => {
    const to = new Date();
    const from = new Date(to.getTime() - PERIODS[period] * 86_400_000);
    return { from: from.toISOString(), to: to.toISOString() };
  }, [period]);
  const recordingId = /^[0-9a-f-]{36}$/i.test(search.trim()) ? search.trim() : undefined;
  const filters: RunFilters = { ...range, status: status || undefined, recording_id: recordingId };

  useEffect(() => {
    let live = true;
    setStats(null);
    setError(null);
    overview(range.from, range.to)
      .then((s) => live && setStats(s))
      .catch((err) => live && setError(messageFor(err)));
    return () => {
      live = false;
    };
  }, [range]);

  useEffect(() => {
    let live = true;
    setRuns(null);
    listRuns(filters)
      .then((page) => {
        if (!live) return;
        setRuns(page.runs);
        setCursor(page.next_cursor);
      })
      .catch((err) => live && setError(messageFor(err)));
    return () => {
      live = false;
    };
    // `filters` is rebuilt every render from these.
  }, [range, status, recordingId]);

  const more = async () => {
    if (!cursor) return;
    try {
      const page = await listRuns({ ...filters, cursor });
      setRuns((prev) => [...(prev ?? []), ...page.runs]);
      setCursor(page.next_cursor);
    } catch (err) {
      toast.error(messageFor(err));
    }
  };

  const exportRun = async (run: RunSummary) => {
    try {
      await downloadDiagnostics(run);
    } catch (err) {
      toast.error(messageFor(err));
    }
  };

  return (
    <div className="doc">
      <div className="page-h">
        <h1>Telemetry</h1>
        <div className="seg" role="group" aria-label="Period">
          {(Object.keys(PERIODS) as Period[]).map((p) => (
            <button
              key={p}
              type="button"
              className="seg-opt"
              aria-pressed={period === p}
              onClick={() => setPeriod(p)}
            >
              {p === "24h" ? "24 hours" : `${PERIODS[p]} days`}
            </button>
          ))}
        </div>
      </div>
      {error && (
        <div className="banner banner-danger" role="alert">
          {error}
        </div>
      )}
      {!stats && !error && (
        <div className="stat-tiles" aria-busy="true" aria-label="Loading telemetry figures">
          <Skeleton height={86} />
          <Skeleton height={86} />
          <Skeleton height={86} />
          <Skeleton height={86} />
        </div>
      )}
      {stats && (
        <>
          <div className="stat-tiles">
            <Tile
              label="Runs"
              value={String(stats.runs)}
              sub={`${stats.status_counts.succeeded} ok · ${stats.status_counts.partial} partial · ${stats.status_counts.failed} failed · ${stats.status_counts.cancelled} cancelled`}
            />
            <Tile
              label="rtf p50 / p95"
              value={`${ratio(stats.rtf.p50)} / ${ratio(stats.rtf.p95)}`}
              sub={`${stats.rtf.n} runs with a wall time`}
            />
            <Tile
              label="User wait p50 / p95"
              value={`${seconds(stats.user_wait_seconds.p50)} / ${seconds(stats.user_wait_seconds.p95)}`}
              sub={`${stats.user_wait_seconds.n} runs seen by a client`}
            />
            <Tile
              label="Telemetry overhead"
              value={seconds(stats.telemetry_overhead_seconds.median)}
              sub="median per run"
            />
          </div>
          {stats.capped && <p className="help">Figures cover the newest 500 runs of the period.</p>}
          <section className="doc-section">
            <h2 className="section-name">Mean share of wall time per stage</h2>
            {Object.keys(stats.stage_share).length === 0 ? (
              <p className="help">No run with a measured wall time in this period.</p>
            ) : (
              <table className="data-table" aria-label="Mean critical-path share per stage">
                <tbody>
                  {Object.entries(stats.stage_share)
                    .sort((a, b) => b[1] - a[1])
                    .map(([stage, share]) => (
                      <tr key={stage} title={`${stage}: ${percent(share)} of wall time on average`}>
                        <th scope="row">{stage}</th>
                        <td style={{ width: "60%" }}>
                          <span className="meter" aria-hidden="true" style={{ display: "block" }}>
                            <span
                              className="meter-fill"
                              style={{ width: `${Math.min(100, share * 100)}%` }}
                            />
                          </span>
                        </td>
                        <td>{percent(share)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            )}
            <p className="help">
              Critical path only; stages that overlap are not added up. Over {stats.runs_with_wall}{" "}
              runs.
            </p>
          </section>
          <section className="doc-section">
            <h2 className="section-name">Backends and devices in use</h2>
            {stats.backends.length === 0 ? (
              <p className="help">None recorded.</p>
            ) : (
              <ul className="share-people" aria-label="Backends in use">
                {stats.backends.map((b) => (
                  <li key={`${b.kind}-${b.name}-${b.device}-${b.observation}`}>
                    <span className="row-name">
                      {b.kind} · {b.name} · {b.device}
                    </span>
                    <span
                      className={`chip ${b.observation === "observed" ? "complete" : "queued"}`}
                    >
                      {b.observation}
                    </span>
                    <span className="help">{b.runs} runs</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
      <section className="doc-section">
        <h2 className="section-name">Recent runs</h2>
        <div className="page-h-actions" style={{ flexWrap: "wrap" }}>
          <Select
            label="Status"
            value={status}
            options={STATUSES.map((s) => ({ value: s, label: s || "Any status" }))}
            onChange={setStatus}
          />
          <input
            className="input"
            type="search"
            placeholder="Recording id"
            aria-label="Search by recording id"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {runs === null && !error && <Skeleton height={120} />}
        {runs !== null && runs.length === 0 && (
          <EmptyState
            icon={<LayersIcon size={20} />}
            title="No runs"
            message="No run matches this period and filter."
            compact
          />
        )}
        {runs !== null && runs.length > 0 && (
          <table className="data-table" aria-label="Recent runs">
            <thead>
              <tr>
                <th>Recording</th>
                <th>Run</th>
                <th>Kind</th>
                <th>Status</th>
                <th>Submitted</th>
                <th>Audio</th>
                <th>Wall</th>
                <th>rtf</th>
                <th>User wait</th>
                <th>ASR</th>
                <th>LLM</th>
                <th>
                  <span className="sr-only">Export</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.processing_run_id}>
                  <td title={r.recording_id}>{shortId(r.recording_id)}</td>
                  <td>
                    <Link to={`/admin/dashboard/runs/${r.processing_run_id}`}>
                      {shortId(r.processing_run_id)}
                    </Link>
                  </td>
                  <td>{r.kind}</td>
                  <td>
                    <StatusBadge status={r.status} />
                  </td>
                  <td>{when(r.submitted_at)}</td>
                  <td>{seconds(r.audio_duration_seconds)}</td>
                  <td>{seconds(r.processing_wall_seconds)}</td>
                  <td>{ratio(r.rtf)}</td>
                  <td>{seconds(r.user_wait_seconds)}</td>
                  <td>{r.asr_backend ?? "—"}</td>
                  <td>{r.llm_model ?? "—"}</td>
                  <td>
                    <button
                      type="button"
                      className="btn ghost sm"
                      onClick={() => void exportRun(r)}
                    >
                      <DownloadIcon size={14} /> Export diagnostics
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {cursor && (
          <button type="button" className="btn ghost" onClick={() => void more()}>
            Load more
          </button>
        )}
      </section>
    </div>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="stat-tile">
      <span className="label">{label}</span>
      <span className="stat-value">{value}</span>
      <span className="help">{sub}</span>
    </div>
  );
}
