import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { getRun, reportBlob, type RunRecord, type SpanRow } from "../../api/telemetry";
import { ArrowLeftIcon, CopyIcon, DownloadIcon } from "../../components/icons";
import { RichText } from "../../components/RichText";
import { Skeleton } from "../../components/Skeleton";
import { useToast } from "../../components/Toaster";
import { copyDiagnostics, downloadDiagnostics } from "../../lib/diagnostics";
import { messageFor } from "../../lib/errorCopy";
import { useDocumentTitle } from "../../lib/useDocumentTitle";
import { RequirePlatformAdmin, seconds } from "./telemetryShared";

/** `/admin/dashboard/runs/:processingRunId` — the run's report (the same Markdown as the
 *  download, rendered by the app's Markdown component) and its raw span tree. */
export function TelemetryRunPage() {
  useDocumentTitle("Telemetry run");
  return (
    <RequirePlatformAdmin>
      <RunView />
    </RequirePlatformAdmin>
  );
}

function RunView() {
  const { processingRunId = "" } = useParams();
  const toast = useToast();
  const [record, setRecord] = useState<RunRecord | null>(null);
  const [report, setReport] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setRecord(null);
    setReport(null);
    setError(null);
    Promise.all([getRun(processingRunId), reportBlob(processingRunId).then((b) => b.text())])
      .then(([r, md]) => {
        if (!live) return;
        setRecord(r);
        setReport(md);
      })
      .catch((err) => live && setError(messageFor(err)));
    return () => {
      live = false;
    };
  }, [processingRunId]);

  const run = record?.processing_run;
  const act = async (fn: () => Promise<void>, done?: string) => {
    try {
      await fn();
      if (done) toast.success(done);
    } catch (err) {
      toast.error(messageFor(err));
    }
  };

  return (
    <div className="doc">
      <div className="page-h">
        <h1>Run {processingRunId.slice(0, 8)}</h1>
        {run && (
          <div className="page-h-actions">
            <button
              type="button"
              className="btn ghost"
              onClick={() => void act(() => copyDiagnostics(run), "Copied as Markdown")}
            >
              <CopyIcon size={14} /> Copy as Markdown
            </button>
            <button
              type="button"
              className="btn primary"
              onClick={() => void act(() => downloadDiagnostics(run))}
            >
              <DownloadIcon size={14} /> Export diagnostics
            </button>
          </div>
        )}
      </div>
      <p className="sub">
        <Link to="/admin/dashboard">
          <ArrowLeftIcon size={14} /> All runs
        </Link>
      </p>
      {error && (
        <div className="banner banner-danger" role="alert">
          {error}
        </div>
      )}
      {!record && !error && <Skeleton height={320} />}
      {report !== null && <RichText text={report} allowSpeakerTurns={false} />}
      {record && (
        <details className="doc-section">
          <summary className="section-name">Raw span tree ({record.spans.length} spans)</summary>
          <SpanTree spans={record.spans} />
        </details>
      )}
    </div>
  );
}

function SpanTree({ spans }: { spans: SpanRow[] }) {
  const ids = new Set(spans.map((s) => s.span_id));
  const children = new Map<string | null, SpanRow[]>();
  for (const s of spans) {
    const parent = s.parent_span_id && ids.has(s.parent_span_id) ? s.parent_span_id : null;
    children.set(parent, [...(children.get(parent) ?? []), s]);
  }
  const duration = (s: SpanRow) =>
    s.start_wall_utc && s.end_wall_utc
      ? (Date.parse(s.end_wall_utc) - Date.parse(s.start_wall_utc)) / 1000
      : null;
  const render = (parent: string | null): ReactNode => {
    const rows = children.get(parent);
    if (!rows) return null;
    return (
      <ul className="span-tree">
        {rows.map((s) => (
          <li key={s.span_id}>
            <code>
              {s.stage} · {s.name} · {s.status} · {seconds(duration(s))}
              {s.attempt > 1 ? ` · attempt ${s.attempt}` : ""}
            </code>
            <pre className="help">{JSON.stringify(s.attributes, null, 2)}</pre>
            {render(s.span_id)}
          </li>
        ))}
      </ul>
    );
  };
  return render(null);
}
