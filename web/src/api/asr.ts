import { api } from "./http";
import type { AsrJob, AsrLanguage, TranscriptResult } from "./types";

export function submitJob(params: {
  audio: Blob;
  filename: string;
  /** "auto" (default) lets the recording decide; "en"/"uk"/"de" pin the decoder. */
  language: AsrLanguage;
  diarize: boolean;
  vocabularyHint?: string;
}): Promise<AsrJob> {
  const form = new FormData();
  form.append("audio", params.audio, params.filename);
  form.append("language", params.language);
  form.append("diarize", String(params.diarize));
  if (params.vocabularyHint && params.vocabularyHint.trim()) {
    form.append("vocabulary_hint", params.vocabularyHint.trim());
  }
  return api<AsrJob>("asr", "/asr/jobs", { method: "POST", form });
}

export function listJobs(): Promise<AsrJob[]> {
  return api<AsrJob[]>("asr", "/asr/jobs");
}

export function getJob(id: string): Promise<AsrJob> {
  return api<AsrJob>("asr", `/asr/jobs/${id}`);
}

export function cancelJob(id: string): Promise<void> {
  return api<void>("asr", `/asr/jobs/${id}`, { method: "DELETE" });
}

/** Plaintext transcript of a COMPLETE job (409 while it is still running). */
export function getResult(id: string): Promise<TranscriptResult> {
  return api<TranscriptResult>("asr", `/asr/jobs/${id}/result`);
}

/**
 * Name the diarized speakers of a job. The full label → name mapping is
 * stored on the job, so every surface (web, desktop, the note) agrees;
 * an empty name puts a label back to its "Speaker N" default.
 */
export function setSpeakerNames(
  id: string,
  names: Record<string, string>,
): Promise<{ job_id: string; speaker_names: Record<string, string> }> {
  return api("asr", `/asr/jobs/${id}/speakers`, { method: "PUT", json: { names } });
}
