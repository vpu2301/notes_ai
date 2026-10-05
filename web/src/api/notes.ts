import { api, apiBlob, ApiError, buildUrl } from "./http";
import { ASK_HISTORY_LIMIT } from "./types";
import type {
  AskResponse,
  AskTurn,
  AttachTranscriptResponse,
  CarriedItem,
  CarriedView,
  ClientVersion,
  ClientVersionCheck,
  CorrectionResponse,
  DismissReason,
  FromTranscriptResponse,
  LineTime,
  MeetingView,
  NoteContent,
  NoteCreatedResponse,
  NoteEnvelope,
  NoteVersionDetail,
  NoteVersionSummary,
  NoteVisibility,
  ReadPurpose,
  SearchResponse,
  CreateLinkRequest,
  ItemStatus,
  ItemView,
  LinkView,
  ResponseView,
  SharedNoteView,
  ShareEmailResponse,
  SharingView,
  SourceJobLink,
  StartMeetingRequest,
  StartMeetingResponse,
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

// ── series, carry-over and the client version (Sprint 36) ─────────────

/** What is still open from the previous meeting in this series. */
export function getCarried(id: string): Promise<CarriedView> {
  return api<CarriedView>("note", `/v1/notes/${id}/carried`);
}

/** Tick a carried item off, re-open it, or drop it. */
export function setCarriedState(
  id: string,
  itemKey: string,
  state: "open" | "done_marked" | "dropped",
): Promise<CarriedItem> {
  return api<CarriedItem>("note", `/v1/notes/${id}/carried/${itemKey}`, {
    method: "POST",
    json: { state },
  });
}

/** "This continues…" — link this meeting to an earlier one by hand. */
export function setPreviousNote(id: string, previousNoteId: string): Promise<CarriedView> {
  return api<CarriedView>("note", `/v1/notes/${id}/meeting/previous`, {
    method: "POST",
    json: { note_id: previousNoteId },
  });
}

/** Exactly what a client would see. 409 for a 1:1 or an interview. */
export function getClientVersion(id: string): Promise<ClientVersion> {
  return api<ClientVersion>("note", `/v1/notes/${id}/client-version`);
}

export function getClientVersionCheck(id: string): Promise<ClientVersionCheck> {
  return api<ClientVersionCheck>("note", `/v1/notes/${id}/client-version/check`);
}

// ── corrections (Sprint 35) ───────────────────────────────────────────
//
// All three address a line by its `item_key` — the hash of its body with
// the owner and the due date stripped. That is what lets an owner or a
// date be fixed without detaching the line from the recipient's
// confirmation on the shared page, or from its correction history.

/** Take a line out of the note, and say why. */
export function dismissItem(
  id: string,
  itemKey: string,
  reason: DismissReason,
  expectedVersion: number,
): Promise<CorrectionResponse> {
  return api<CorrectionResponse>("note", `/v1/notes/${id}/items/${itemKey}/dismiss`, {
    method: "POST",
    json: { reason, expected_version: expectedVersion },
  });
}

/** Put a dismissed line back, exactly as it read. */
export function restoreItem(
  id: string,
  itemKey: string,
  expectedVersion: number,
): Promise<CorrectionResponse> {
  return api<CorrectionResponse>("note", `/v1/notes/${id}/items/${itemKey}/restore`, {
    method: "POST",
    json: { expected_version: expectedVersion },
  });
}

/**
 * Fix a line's owner or due date in place. The key does not change, which
 * is the whole point of the route.
 *
 * Addressed under `/items/by-key/` because `PATCH /items/{item_id}` was
 * already taken by the Sprint 20 status route, which uses the row UUID.
 */
export function patchItem(
  id: string,
  itemKey: string,
  changes: {
    owner_label?: string;
    due_text?: string;
    clear_owner?: boolean;
    clear_due?: boolean;
  },
  expectedVersion: number,
): Promise<CorrectionResponse> {
  return api<CorrectionResponse>("note", `/v1/notes/${id}/items/by-key/${itemKey}`, {
    method: "PATCH",
    json: { ...changes, expected_version: expectedVersion },
  });
}

// ── the live meeting note (Sprint 34) ─────────────────────────────────

/**
 * Open the note as Record is pressed. Idempotent on `client_capture_id`:
 * a retry, a double click and a second device all get the same note.
 *
 * The caller must NOT wait for this and must never let it stop a
 * recording — a note we failed to create is recoverable, a meeting we
 * failed to record is not.
 */
export function startMeeting(body: StartMeetingRequest): Promise<StartMeetingResponse> {
  return api<StartMeetingResponse>("note", "/v1/notes/meeting", { method: "POST", json: body });
}

/** When each typed line was first touched. First report per key wins. */
export function putLineTimes(id: string, lines: LineTime[]): Promise<void> {
  return api<void>("note", `/v1/notes/${id}/my-notes/timing`, {
    method: "PUT",
    json: { lines },
  });
}

/** The recording reached asr-service: bind the job to the note. */
export function attachJob(id: string, asrJobId: string): Promise<MeetingView> {
  return api<MeetingView>("note", `/v1/notes/${id}/meeting/job`, {
    method: "POST",
    json: { asr_job_id: asrJobId },
  });
}

/** The transcription finished: put it in the note. Safe from any device. */
export function attachTranscript(id: string): Promise<AttachTranscriptResponse> {
  return api<AttachTranscriptResponse>("note", `/v1/notes/${id}/transcript`, { method: "POST" });
}

/** The recording was discarded or never happened. The note stays. */
export function markNoAudio(id: string): Promise<MeetingView> {
  return api<MeetingView>("note", `/v1/notes/${id}/meeting/no-audio`, { method: "POST" });
}

/** 404 when the note is not a live capture (an upload, or typed by hand). */
export function getMeeting(id: string): Promise<MeetingView> {
  return api<MeetingView>("note", `/v1/notes/${id}/meeting`);
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
 * and pointed at the note, everyone else gets their own link.
 */
export function shareByEmail(
  id: string,
  body: { recipients: string[]; message?: string; lang?: string; expires_in_days?: number },
): Promise<ShareEmailResponse> {
  return api<ShareEmailResponse>("note", `/v1/notes/${id}/share/email`, {
    method: "POST",
    json: {
      recipients: body.recipients,
      message: body.message ?? "",
      expires_in_days: body.expires_in_days,
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
/** `expiresInDays` undefined → the link never expires. */
export function createPublicLink(id: string, expiresInDays?: number): Promise<SharingView> {
  return api<SharingView>("note", `/v1/notes/${id}/public-link`, {
    method: "POST",
    json: expiresInDays ? { expires_in_days: expiresInDays } : {},
  });
}

export function revokePublicLink(id: string): Promise<SharingView> {
  return api<SharingView>("note", `/v1/notes/${id}/public-link`, { method: "DELETE" });
}

/** Anonymous — no bearer, no session. */
// ── Sprint 19: per-recipient links ────────────────────────────────

/** 201 with the new link, or 200 with the existing one for that e-mail. */
export function createLink(id: string, body: CreateLinkRequest): Promise<LinkView> {
  return api<LinkView>("note", `/v1/notes/${id}/links`, { method: "POST", json: body });
}

/** Sprint 22: mail the link from the product. 422 `no_recipient_email`, 409 `recipient_opted_out`, 429 on a cap. */
export function sendLink(
  id: string,
  linkId: string,
  body: { personal_message?: string; lang?: string } = {},
): Promise<LinkView> {
  return api<LinkView>("note", `/v1/notes/${id}/links/${linkId}/send`, { method: "POST", json: body });
}

export function listLinks(id: string): Promise<LinkView[]> {
  return api<LinkView[]>("note", `/v1/notes/${id}/links`);
}

export function revokeLink(id: string, linkId: string): Promise<void> {
  return api<void>("note", `/v1/notes/${id}/links/${linkId}`, { method: "DELETE" });
}

export function revokeAllLinks(id: string): Promise<void> {
  return api<void>("note", `/v1/notes/${id}/links`, { method: "DELETE" });
}

/** The sender's logo, for an `<img src>` on the shared page. */
export function sharedLogoUrl(token: string): string {
  return buildUrl("note", `/v1/shared/${encodeURIComponent(token)}/logo`);
}

/** The CTA `<a href>`: a server-side redirect, so the click counts without JavaScript. */
export function sharedCtaUrl(token: string): string {
  return buildUrl("note", `/v1/shared/${encodeURIComponent(token)}/cta`);
}

// ── Sprint 20: action items + recipient responses ────────────────

export function getItems(id: string): Promise<ItemView[]> {
  return api<ItemView[]>("note", `/v1/notes/${id}/items`);
}

export function setItemStatus(id: string, itemId: string, status: ItemStatus): Promise<ItemView> {
  return api<ItemView>("note", `/v1/notes/${id}/items/${itemId}`, { method: "PATCH", json: { status } });
}

export function getResponses(id: string, includeCleared = false): Promise<ResponseView[]> {
  return api<ResponseView[]>("note", `/v1/notes/${id}/responses`, {
    query: { include_cleared: includeCleared },
  });
}

export function clearResponse(id: string, responseId: string): Promise<ResponseView> {
  return api<ResponseView>("note", `/v1/notes/${id}/responses/${responseId}/clear`, { method: "POST" });
}

/** Anonymous, token-scoped. 403 `link_kind_public` on a public link. */
export function respondToItem(
  token: string,
  itemKey: string,
  kind: "confirm" | "done" | "dispute",
  comment?: string,
): Promise<void> {
  return api<void>(
    "note",
    `/v1/shared/${encodeURIComponent(token)}/items/${encodeURIComponent(itemKey)}/response`,
    { method: "PUT", json: { kind, comment: comment || undefined }, auth: false },
  );
}

export function withdrawItemResponse(token: string, itemKey: string): Promise<void> {
  return api<void>(
    "note",
    `/v1/shared/${encodeURIComponent(token)}/items/${encodeURIComponent(itemKey)}/response`,
    { method: "DELETE", auth: false },
  );
}

export function flagSection(token: string, sectionKey: string, comment?: string): Promise<void> {
  return api<void>(
    "note",
    `/v1/shared/${encodeURIComponent(token)}/sections/${encodeURIComponent(sectionKey)}/flag`,
    { method: "PUT", json: { comment: comment || undefined }, auth: false },
  );
}

export function unflagSection(token: string, sectionKey: string): Promise<void> {
  return api<void>(
    "note",
    `/v1/shared/${encodeURIComponent(token)}/sections/${encodeURIComponent(sectionKey)}/flag`,
    { method: "DELETE", auth: false },
  );
}

// ── Sprint 23: verification + report ──────────────────────────────

export function requestSharedVerification(token: string): Promise<void> {
  return api<void>("note", `/v1/shared/${encodeURIComponent(token)}/verify/request`, { method: "POST", auth: false });
}

/** 400 `code_invalid` / `code_expired`, 429 `too_many_attempts`; success returns the page. */
export function verifyShared(token: string, code: string): Promise<SharedNoteView> {
  return api<SharedNoteView>("note", `/v1/shared/${encodeURIComponent(token)}/verify`, {
    method: "POST",
    json: { code },
    auth: false,
  });
}

export function reportShared(token: string, reason: string): Promise<void> {
  return api<void>("note", `/v1/shared/${encodeURIComponent(token)}/report`, {
    method: "POST",
    json: { reason },
    auth: false,
  });
}

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
