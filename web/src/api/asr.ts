import { api } from "./http";
import type { AsrJob } from "./types";

export function submitJob(params: {
  audio: Blob;
  filename: string;
  language: "en" | "uk";
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
