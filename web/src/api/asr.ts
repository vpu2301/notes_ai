import { ApiError, api } from "./http";
import type {
  AsrJob,
  AsrLanguage,
  CaptureSource,
  ChannelLayout,
  CorrectionsView,
  NameSource,
  ReassignResult,
  RediarizeAccepted,
  SpeakerEditResult,
  TranscriptResult,
} from "./types";

export interface SubmitJobParams {
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
  /**
   * Sprint I3: `mic_system` declares a 2-channel file (L = microphone,
   * R = tab/system audio). Only sent when set to that; mono is the default.
   */
  channelLayout?: ChannelLayout;
  /** The author's name for their own channel's speaker (≤ 400 chars; the server trims). */
  localSpeakerName?: string;
  /** Sprint F1: when Record was clicked (ISO 8601); omitted for uploaded files. */
  recordPressedAt?: string;
  /** Sprint F1: ms from the click to the first frame written (0–600 000). */
  firstFrameOffsetMs?: number;
}

export function submitJob(params: SubmitJobParams): Promise<AsrJob> {
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
  if (params.channelLayout === "mic_system") {
    form.append("channel_layout", "mic_system");
  }
  if (params.localSpeakerName && params.localSpeakerName.trim()) {
    form.append("local_speaker_name", params.localSpeakerName.trim().slice(0, 400));
  }
  if (params.recordPressedAt) {
    form.append("record_pressed_at", params.recordPressedAt);
  }
  if (params.firstFrameOffsetMs != null && Number.isFinite(params.firstFrameOffsetMs)) {
    const offset = Math.min(600_000, Math.max(0, Math.round(params.firstFrameOffsetMs)));
    form.append("first_frame_offset_ms", String(offset));
  }
  return api<AsrJob>("asr", "/asr/jobs", { method: "POST", form });
}

/** The server says the file does not have the channel layout the upload declared. */
export function refusedLayout(err: unknown): boolean {
  return err instanceof ApiError && err.code === "channel_layout_mismatch";
}

/**
 * Submit, and if a `mic_system` upload is refused as `channel_layout_mismatch`
 * (the browser wrote one channel after all), post the same file once more as
 * mono: the recording is worth more than the channel split. Mirrors the
 * macOS app's fallback. `send` is injectable so a page can hand in its own
 * (mocked) `submitJob`.
 */
export async function submitWithLayoutFallback(
  send: (params: SubmitJobParams) => Promise<AsrJob>,
  params: SubmitJobParams,
): Promise<{ job: AsrJob; fellBackToMono: boolean }> {
  try {
    return { job: await send(params), fellBackToMono: false };
  } catch (err) {
    if (params.channelLayout !== "mic_system" || !refusedLayout(err)) throw err;
    const { channelLayout: _layout, localSpeakerName: _name, ...mono } = params;
    return { job: await send(mono), fellBackToMono: true };
  }
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

/** Sprint TQ3: the spellings unified (or proposed) for this transcript. */
export function listCorrections(id: string): Promise<CorrectionsView> {
  return api<CorrectionsView>("asr", `/asr/jobs/${id}/corrections`);
}

/**
 * Accept or reject one unified spelling. `to_text` edits the spelling on
 * accept. `corrections_rev` is the one the view showed; a stale one is a 409.
 */
export function decideCorrection(
  id: string,
  correctionId: string,
  body: { status: "accepted" | "rejected"; to_text?: string; corrections_rev: number },
): Promise<CorrectionsView> {
  return api<CorrectionsView>("asr", `/asr/jobs/${id}/corrections/${correctionId}`, {
    method: "PUT",
    json: body,
  });
}
