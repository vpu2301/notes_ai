import { api, apiBlob, ApiError } from "./http";
import { ASK_HISTORY_LIMIT } from "./types";
import type {
  AmendResponse,
  AskResponse,
  AskTurn,
  FinalizeResponse,
  FromTranscriptResponse,
  NoteAmendmentType,
  NoteContent,
  NoteCreatedResponse,
  NoteEnvelope,
  NoteVersionDetail,
  NoteVersionSummary,
  NoteVisibility,
  ReadPurpose,
  SearchResponse,
  SharedNoteView,
  ShareEmailResponse,
  SharingView,
  SourceJobLink,
  TemplateDetail,
  TemplateSummary,
  UpdateDraftResponse,
} from "./types";

// ── templates ─────────────────────────────────────────────────────────

export function listTemplates(): Promise<TemplateSummary[]> {
  return api<TemplateSummary[]>("note", "/templates");
}

export function getTemplate(id: string): Promise<TemplateDetail> {
  return api<TemplateDetail>("note", `/templates/${id}`);
}

// ── notes ─────────────────────────────────────────────────────────────

export function createNote(content: NoteContent): Promise<NoteCreatedResponse> {
  return api<NoteCreatedResponse>("note", "/v1/notes", {
    method: "POST",
    json: { content },
  });
}

/**
 * The problem `type` the server answers a non-author read that came without
 * `?purpose=`. The page retries once with a purpose and says whose note it
 * is showing; see `ReadPurpose`.
 */
export const READ_PURPOSE_REQUIRED = "https://errors.notes-ai/missing-read-purpose";

export function needsReadPurpose(err: unknown): boolean {
  return err instanceof ApiError && err.status === 422 && err.type === READ_PURPOSE_REQUIRED;
}

export function getNote(id: string, purpose?: ReadPurpose): Promise<NoteEnvelope> {
  return api<NoteEnvelope>("note", `/v1/notes/${id}`, {
    query: { include_content: true, purpose },
  });
}

export function updateDraft(
  id: string,
  content: NoteContent,
  expectedVersion: number,
): Promise<UpdateDraftResponse> {
  return api<UpdateDraftResponse>("note", `/v1/notes/${id}/draft`, {
    method: "PUT",
    json: { content, expected_version: expectedVersion },
  });
}

export function finalizeNote(id: string, expectedVersion: number): Promise<FinalizeResponse> {
  return api<FinalizeResponse>("note", `/v1/notes/${id}/finalize`, {
    method: "POST",
    json: { expected_version: expectedVersion },
  });
}

export function revertToDraft(id: string): Promise<FinalizeResponse> {
  return api<FinalizeResponse>("note", `/v1/notes/${id}/revert-to-draft`, {
    method: "POST",
  });
}

export function amendNote(
  id: string,
  content: NoteContent,
  amendmentType: NoteAmendmentType,
  amendmentReason: string,
): Promise<AmendResponse> {
  return api<AmendResponse>("note", `/v1/notes/${id}/amend`, {
    method: "POST",
    json: {
      content,
      amendment_type: amendmentType,
      amendment_reason: amendmentReason,
    },
  });
}

export function searchNotes(params: {
  q?: string;
  status?: string[];
  cursor?: string;
  limit?: number;
  signal?: AbortSignal;
}): Promise<SearchResponse> {
  return api<SearchResponse>("note", "/v1/notes/search", {
    query: {
      q: params.q || undefined,
      status: params.status && params.status.length > 0 ? params.status : undefined,
      cursor: params.cursor,
      limit: params.limit ?? 25,
    },
    signal: params.signal,
  });
}

export function listVersions(id: string, purpose?: ReadPurpose): Promise<NoteVersionSummary[]> {
  return api<NoteVersionSummary[]>("note", `/v1/notes/${id}/versions`, { query: { purpose } });
}

export function getVersion(
  id: string,
  versionNumber: number,
  purpose?: ReadPurpose,
): Promise<NoteVersionDetail> {
  return api<NoteVersionDetail>("note", `/v1/notes/${id}/versions/${versionNumber}`, {
    query: { purpose },
  });
}

export function downloadPdf(id: string, purpose?: ReadPurpose): Promise<Blob> {
  return apiBlob("note", `/v1/notes/${id}/pdf`, { query: { purpose } });
}

export function createFromTranscript(params: {
  asr_job_id: string;
  template_id?: string;
  title?: string;
}): Promise<FromTranscriptResponse> {
  return api<FromTranscriptResponse>("note", "/v1/notes/from-transcript", {
    method: "POST",
    json: params,
  });
}

/** Which notes were created from which transcription jobs (≤200 ids). */
export function notesBySourceJob(jobIds: string[]): Promise<SourceJobLink[]> {
  if (jobIds.length === 0) return Promise.resolve([]);
  return api<SourceJobLink[]>("note", "/v1/notes/by-source-job", {
    query: { ids: jobIds.slice(0, 200).join(",") },
  });
}

// ── delete, visibility, sharing (0016) ────────────────────────────────

export function deleteNote(id: string): Promise<{ id: string; deleted_at: string }> {
  return api("note", `/v1/notes/${id}`, { method: "DELETE" });
}

export function getSharing(id: string): Promise<SharingView> {
  return api<SharingView>("note", `/v1/notes/${id}/sharing`);
}

export function setVisibility(id: string, visibility: NoteVisibility): Promise<SharingView> {
  return api<SharingView>("note", `/v1/notes/${id}/visibility`, {
    method: "PUT",
    json: { visibility },
  });
}

/** Give a workspace member read access; 404 `not_a_member` if the address is unknown. */
export function shareWithMember(id: string, email: string): Promise<SharingView> {
  return api<SharingView>("note", `/v1/notes/${id}/share`, { method: "POST", json: { email } });
}

/**
 * Mail the note to people, from the server.
 *
 * The old "Email link…" built a `mailto:` URL and let the browser hand it
 * to the desktop mail client, which produced an unstyled draft the sender
 * still had to send — and on macOS surfaced whatever Mail.app already had
 * open. This sends the real thing: workspace members are granted access
 * and pointed at the note, everyone else gets the public link.
 */
export function shareByEmail(
  id: string,
  body: { recipients: string[]; message?: string; lang?: string },
): Promise<ShareEmailResponse> {
  return api<ShareEmailResponse>("note", `/v1/notes/${id}/share/email`, {
    method: "POST",
    json: {
      recipients: body.recipients,
      message: body.message ?? "",
      // The sender's UI language. The recipient's is unknowable — half of
      // them have no account here — and people share within a team.
      lang: body.lang ?? navigator.language,
    },
  });
}

export function unshareMember(id: string, sub: string): Promise<SharingView> {
  return api<SharingView>("note", `/v1/notes/${id}/share/${sub}`, { method: "DELETE" });
}

/** Idempotent: returns the existing live link if there is one. */
export function createPublicLink(id: string): Promise<SharingView> {
  return api<SharingView>("note", `/v1/notes/${id}/public-link`, { method: "POST" });
}

export function revokePublicLink(id: string): Promise<SharingView> {
  return api<SharingView>("note", `/v1/notes/${id}/public-link`, { method: "DELETE" });
}

/** Anonymous — no bearer, no session. */
export function getSharedNote(token: string): Promise<SharedNoteView> {
  return api<SharedNoteView>("note", `/v1/shared/${encodeURIComponent(token)}`, { auth: false });
}

export function downloadSharedPdf(token: string): Promise<Blob> {
  return apiBlob("note", `/v1/shared/${encodeURIComponent(token)}/pdf`, { auth: false });
}

// ── ask this note ─────────────────────────────────────────────────────

/**
 * Ask a question about one note. The answer comes from the model the
 * workspace is configured for, over the note's text and its transcript;
 * `history` is the conversation so far, oldest first, and the server
 * takes at most `ASK_HISTORY_LIMIT` turns of it.
 */
export function askNote(id: string, question: string, history: AskTurn[]): Promise<AskResponse> {
  return api<AskResponse>("note", `/v1/notes/${id}/ask`, {
    method: "POST",
    json: { question, history: history.slice(-ASK_HISTORY_LIMIT) },
  });
}
