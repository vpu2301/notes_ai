import { api } from "./http";
import type {
  AsrJob,
  AsrLanguage,
  CaptureSource,
  NameSource,
  ReassignResult,
  RediarizeAccepted,
  SpeakerEditResult,
  TranscriptResult,
} from "./types";

export function submitJob(params: {
  audio: Blob;
  filename: string;
  /** "auto" (default) lets the recording decide; "en"/"uk"/"de" pin the decoder. */
  language: AsrLanguage;
  diarize: boolean;
  vocabularyHint?: string;
  /** How many people spoke, when someone said so (1–8); omitted for "don't know". */
  speakersExpected?: number | null;
  /**
   * An upper bound on the speakers (1–8): a calendar event's invitee count,
   * never sent as `speakersExpected`. A set "People" value wins server-side.
   */
  speakersMax?: number | null;
  /** Names to offer when renaming speakers (≤ 12, sent as one JSON string field). */
  nameCandidates?: string[] | null;
  captureSource?: CaptureSource;
}): Promise<AsrJob> {
  const form = new FormData();
  form.append("audio", params.audio, params.filename);
  form.append("language", params.language);
  form.append("diarize", String(params.diarize));
  if (params.vocabularyHint && params.vocabularyHint.trim()) {
    form.append("vocabulary_hint", params.vocabularyHint.trim());
  }
  if (params.speakersExpected != null) {
    form.append("speakers_expected", String(params.speakersExpected));
  }
  if (params.speakersMax != null) {
    form.append("speakers_max", String(params.speakersMax));
  }
  if (params.nameCandidates && params.nameCandidates.length > 0) {
    form.append("name_candidates", JSON.stringify(params.nameCandidates));
  }
  if (params.captureSource) {
    form.append("capture_source", params.captureSource);
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
  /** How each changed name was chosen (a metric only; the server does not keep it). */
  sources?: Record<string, NameSource>,
): Promise<{ job_id: string; speaker_names: Record<string, string> }> {
  const json = sources && Object.keys(sources).length > 0 ? { names, sources } : { names };
  return api("asr", `/asr/jobs/${id}/speakers`, { method: "PUT", json });
}

/**
 * Turn down a name suggestion: that label/name pair never comes back for
 * this job (204, idempotent). Accepting one is a `setSpeakerNames` with
 * `sources[label] = "suggestion"`.
 */
export function dismissNameSuggestion(id: string, label: string, name: string): Promise<void> {
  return api<void>("asr", `/asr/jobs/${id}/speakers/suggestions/dismiss`, {
    method: "POST",
    json: { label, name },
  });
}

/**
 * Move turns to another speaker: an existing label, `"new"` (someone the
 * diarizer missed) or `null` (Unknown). `segmentIndices` are the turns'
 * own `segment_indices`, concatenated — one call per action. A reversible
 * edit like a merge; 409 `stale_result_rev` means reload first.
 */
export function reassignTurns(
  id: string,
  params: { resultRev: number; segmentIndices: number[]; to: string | null },
): Promise<ReassignResult> {
  return api<ReassignResult>("asr", `/asr/jobs/${id}/speakers/reassign`, {
    method: "POST",
    json: { result_rev: params.resultRev, segment_indices: params.segmentIndices, to: params.to },
  });
}

/** Undo every live speaker edit (merges and moved turns) of the current labelling. Idempotent. */
export function resetSpeakerEdits(id: string): Promise<void> {
  return api<void>("asr", `/asr/jobs/${id}/speakers/edits/reset`, { method: "POST" });
}

/** Merge one diarized speaker into another (a reversible overlay on the job). */
export function mergeSpeakers(id: string, from: string, into: string): Promise<SpeakerEditResult> {
  return api<SpeakerEditResult>("asr", `/asr/jobs/${id}/speakers/merge`, {
    method: "POST",
    json: { from, into },
  });
}

/** Undo a job's latest speaker edit (409 `edit_not_latest` for an older one). */
export function undoSpeakerEdit(id: string, editId: string): Promise<void> {
  return api<void>("asr", `/asr/jobs/${id}/speakers/edits/${editId}`, { method: "DELETE" });
}

/**
 * Re-label a finished transcript's speakers, optionally with the number of
 * people who spoke (null lets the diarizer decide). Runs in the background:
 * poll `getJob` while `diarization_status` is queued/running. Replaces any
 * speaker merges, which belong to the old labelling.
 */
export function rediarize(id: string, speakersExpected: number | null): Promise<RediarizeAccepted> {
  return api<RediarizeAccepted>("asr", `/asr/jobs/${id}/rediarize`, {
    method: "POST",
    json: { speakers_expected: speakersExpected },
  });
}

/** Put back the labelling before the last re-run (one step; 409 `nothing_to_undo` after). */
export function undoRediarize(id: string): Promise<RediarizeAccepted> {
  return api<RediarizeAccepted>("asr", `/asr/jobs/${id}/rediarize/undo`, { method: "POST" });
}
