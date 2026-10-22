/** "Export diagnostics" (telemetry sprint 4): a run's Markdown report, as a file or copied. */
import { recordingRuns, reportBlob, reportFilename, type RunSummary } from "../api/telemetry";
import { saveBlob } from "./exportNote";

type RunRef = Pick<RunSummary, "recording_id" | "processing_run_id">;

export async function downloadDiagnostics(run: RunRef): Promise<void> {
  saveBlob(await reportBlob(run.processing_run_id), reportFilename(run));
}

export async function copyDiagnostics(run: RunRef): Promise<void> {
  const text = await (await reportBlob(run.processing_run_id)).text();
  await navigator.clipboard.writeText(text);
}

/** The recording's newest run (a reprocess after the initial one), or null when it has none. */
export async function latestRun(recordingId: string): Promise<RunSummary | null> {
  const { runs } = await recordingRuns(recordingId);
  return runs[0] ?? null;
}
