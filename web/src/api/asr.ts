import { api } from "./http";
import type { AsrJob, AsrLanguage, TranscriptResult } from "./types";

export function submitJob(params: {
  audio: Blob;
  filename: string;
  /** "auto" (default) lets the recording decide; "en"/"uk" pin the decoder. */
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
