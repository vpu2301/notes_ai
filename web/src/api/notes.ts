import { api, apiBlob } from "./http";
import type {
  AmendResponse,
  FinalizeResponse,
  FromTranscriptResponse,
  NoteAmendmentType,
  NoteContent,
  NoteCreatedResponse,
  NoteEnvelope,
  NoteVersionDetail,
  NoteVersionSummary,
  NoteVisibility,
  SearchResponse,
  SharedNoteView,
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

export function getNote(id: string): Promise<NoteEnvelope> {
  return api<NoteEnvelope>("note", `/v1/notes/${id}`, {
    query: { include_content: true },
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

export function listVersions(id: string): Promise<NoteVersionSummary[]> {
  return api<NoteVersionSummary[]>("note", `/v1/notes/${id}/versions`);
}

export function getVersion(id: string, versionNumber: number): Promise<NoteVersionDetail> {
  return api<NoteVersionDetail>("note", `/v1/notes/${id}/versions/${versionNumber}`);
}

export function downloadPdf(id: string): Promise<Blob> {
  return apiBlob("note", `/v1/notes/${id}/pdf`);
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
