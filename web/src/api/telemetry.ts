// Pipeline telemetry reads (telemetry sprint 4). Timings, counts and backends only — no
// endpoint here returns transcript, note or prompt text.
import { api, apiBlob } from "./http";

export type RunStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled" | "partial";

export interface RunSummary {
  processing_run_id: string;
  tenant_id: string;
  recording_id: string;
  kind: "initial" | "reprocess";
  reprocess_scope: string | null;
  status: RunStatus;
  error_category: string | null;
  submitted_at: string;
  finished_at: string | null;
  audio_duration_seconds: number | null;
  processing_wall_seconds: number | null;
  rtf: number | null;
  user_wait_seconds: number | null;
  telemetry_overhead_seconds: number | null;
  asr_backend: string | null;
  llm_model: string | null;
}

export interface RunPage {
  runs: RunSummary[];
  next_cursor: string | null;
}

export interface RunFilters {
  recording_id?: string;
  status?: RunStatus;
  from?: string;
  to?: string;
  limit?: number;
  cursor?: string;
}

export interface SpanRow {
  span_id: string;
  parent_span_id: string | null;
  stage: string;
  name: string;
  attempt: number;
  status: string;
  start_wall_utc: string | null;
  end_wall_utc: string | null;
  attributes: Record<string, unknown>;
}

/** The run's full record; the dashboard reads only what it shows. */
export interface RunRecord {
  processing_run: RunSummary & Record<string, unknown>;
  spans: SpanRow[];
  missing_measurements: Array<{ group: string; item: string; field: string; reason: string }>;
}

export interface Percentiles {
  p50: number | null;
  p95: number | null;
  n: number;
}

export interface Overview {
  from: string;
  to: string;
  capped: boolean;
  runs: number;
  status_counts: Record<RunStatus, number>;
  rtf: Percentiles;
  user_wait_seconds: Percentiles;
  telemetry_overhead_seconds: { median: number | null; n: number };
  stage_share: Record<string, number>;
  runs_with_wall: number;
  backends: Array<{
    kind: string;
    name: string;
    device: string;
    observation: "observed" | "configured";
    runs: number;
  }>;
}

export function listRuns(filters: RunFilters = {}): Promise<RunPage> {
  return api<RunPage>("note", "/v1/telemetry/runs", { query: { ...filters } });
}

export function recordingRuns(recordingId: string): Promise<{ runs: RunSummary[] }> {
  return api("note", `/v1/telemetry/recordings/${recordingId}/runs`);
}

export function getRun(runId: string): Promise<RunRecord> {
  return api<RunRecord>("note", `/v1/telemetry/runs/${runId}`);
}

export function reportBlob(runId: string): Promise<Blob> {
  return apiBlob("note", `/v1/telemetry/runs/${runId}/report.md`);
}

export function overview(from?: string, to?: string): Promise<Overview> {
  return api<Overview>("note", "/v1/admin/telemetry/overview", { query: { from, to } });
}

/** `diagnostics-<recording>-<run>.md`, the name the server's download carries. */
export function reportFilename(
  run: Pick<RunSummary, "recording_id" | "processing_run_id">,
): string {
  return `diagnostics-${run.recording_id}-${run.processing_run_id}.md`;
}
