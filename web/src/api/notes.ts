import { api, apiBlob, ApiError, buildUrl } from "./http";
import { invite } from "./tenants";
import { ASK_HISTORY_LIMIT } from "./types";
import type {
  CollaboratorRole,
  CommentAnchorKind,
  NoteComment,
  PresenceViewer,
  ShareGranted,
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

/** Problem `type` for a non-author read without `?purpose=`; the page retries once with one. */
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

/** `mine` = I author it; `shared_with_me` = I can see it but did not author it (W3). */
export type SearchScope = "all" | "mine" | "shared_with_me";

export function searchNotes(params: {
  q?: string;
  status?: string[];
  cursor?: string;
  limit?: number;
  scope?: SearchScope;
  signal?: AbortSignal;
}): Promise<SearchResponse> {
  return api<SearchResponse>("note", "/v1/notes/search", {
    query: {
      q: params.q || undefined,
      // `all` is the server default: left off so an older server sees the same request.
      scope: params.scope && params.scope !== "all" ? params.scope : undefined,
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

// ── series, carry-over and the client version ─────────────────────────

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

// ── corrections ───────────────────────────────────────────────────────
// Lines are addressed by `item_key` (body hash, owner/due stripped), so an
// owner or date fix keeps the line's confirmations and history.

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

/** Fix a line's owner or due date in place; the key does not change. `/items/{item_id}` is the status route (row UUID). */
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

// ── the live meeting note ─────────────────────────────────────────────

/** Idempotent on `client_capture_id`. The caller must NOT await this or let it stop a recording. */
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

// ── delete, visibility, sharing ───────────────────────────────────────

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

/** What giving one address access did: a member got it now, anyone else got an invitation. */
export type ShareOutcome = { kind: "granted"; sharing: SharingView } | { kind: "invited" };

/**
 * Give one person a role on the note. A member is granted at once; a non-member
 * (404 `not_a_member` with `can_invite`) is invited as a guest of this workspace
 * through auth-service, which mails them — note-service never mails outsiders.
 */
export async function shareNote(
  id: string,
  tenantId: string | null,
  body: { email: string; role: CollaboratorRole; message?: string },
): Promise<ShareOutcome> {
  try {
    const granted = await api<ShareGranted>("note", `/v1/notes/${id}/share`, {
      method: "POST",
      json: { email: body.email, role: body.role, message: body.message || undefined },
    });
    return { kind: "granted", sharing: granted.sharing };
  } catch (err) {
    const invitable =
      err instanceof ApiError && err.code === "not_a_member" && err.extra<boolean>("can_invite") === true;
    if (!invitable || !tenantId) throw err;
    await invite(tenantId, {
      email: body.email,
      role: "guest",
      note_id: id,
      note_role: body.role,
      message: body.message || undefined,
    });
    return { kind: "invited" };
  }
}

/** Change a collaborator's role. 404 `not_a_member`, 409 `is_author`. */
export function setCollaborator(id: string, sub: string, role: CollaboratorRole): Promise<SharingView> {
  return api<SharingView>("note", `/v1/notes/${id}/collaborators/${sub}`, { method: "PUT", json: { role } });
}

export function removeCollaborator(id: string, sub: string): Promise<void> {
  return api<void>("note", `/v1/notes/${id}/collaborators/${sub}`, { method: "DELETE" });
}

/** "Include transcript" for view/comment collaborators and guests. */
export function setTranscriptSharing(id: string, shared: boolean): Promise<SharingView> {
  return api<SharingView>("note", `/v1/notes/${id}/transcript-sharing`, { method: "PUT", json: { shared } });
}

/** Server-sent mail. `mode: "link"` mails anyone who is not a member their own recipient link. */
export function shareByEmail(
  id: string,
  body: {
    recipients: string[];
    message?: string;
    lang?: string;
    expires_in_days?: number;
    role?: CollaboratorRole;
    mode?: "invite" | "link";
  },
): Promise<ShareEmailResponse> {
  return api<ShareEmailResponse>("note", `/v1/notes/${id}/share/email`, {
    method: "POST",
    json: {
      recipients: body.recipients,
      message: body.message ?? "",
      expires_in_days: body.expires_in_days,
      // The sender's UI language; the recipient's is unknowable.
      lang: body.lang ?? navigator.language,
      role: body.role,
      mode: body.mode,
    },
  });
}


/** Idempotent (returns the existing live link). `expiresInDays` undefined → never expires. */
export function createPublicLink(id: string, expiresInDays?: number): Promise<SharingView> {
  return api<SharingView>("note", `/v1/notes/${id}/public-link`, {
    method: "POST",
    json: expiresInDays ? { expires_in_days: expiresInDays } : {},
  });
}

export function revokePublicLink(id: string): Promise<SharingView> {
  return api<SharingView>("note", `/v1/notes/${id}/public-link`, { method: "DELETE" });
}

// ── per-recipient links ───────────────────────────────────────────

/** 201 with the new link, or 200 with the existing one for that e-mail. */
export function createLink(id: string, body: CreateLinkRequest): Promise<LinkView> {
  return api<LinkView>("note", `/v1/notes/${id}/links`, { method: "POST", json: body });
}

/** Mail the link from the product. 422 `no_recipient_email`, 409 `recipient_opted_out`, 429 on a cap. */
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

// ── action items + recipient responses ───────────────────────────

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

// ── verification + report ─────────────────────────────────────────

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

// ── comments ──────────────────────────────────────────────────────────
// 403 `insufficient_role` (extra `required`) when the level is too low; 429 `rate_limited`.

export function listComments(id: string): Promise<NoteComment[]> {
  return api<{ items: NoteComment[] }>("note", `/v1/notes/${id}/comments`).then((r) => r.items);
}

export function addComment(
  id: string,
  body: { anchor_kind: CommentAnchorKind; anchor_key?: string; body: string },
): Promise<NoteComment> {
  return api<NoteComment>("note", `/v1/notes/${id}/comments`, { method: "POST", json: body });
}

export function editComment(id: string, commentId: string, body: string): Promise<NoteComment> {
  return api<NoteComment>("note", `/v1/notes/${id}/comments/${commentId}`, { method: "PATCH", json: { body } });
}

export function setCommentResolved(id: string, commentId: string, resolved: boolean): Promise<NoteComment> {
  return api<NoteComment>("note", `/v1/notes/${id}/comments/${commentId}/${resolved ? "resolve" : "unresolve"}`, {
    method: "POST",
  });
}

export function deleteComment(id: string, commentId: string): Promise<void> {
  return api<void>("note", `/v1/notes/${id}/comments/${commentId}`, { method: "DELETE" });
}

// ── presence ──────────────────────────────────────────────────────────

/** "I have this note open"; repeated every 20 s, forgotten by the server after 45 s. */
export function heartbeatPresence(id: string): Promise<void> {
  return api<void>("note", `/v1/notes/${id}/presence`, { method: "POST" });
}

/** Who else has it open (the caller is left out). */
export function getPresence(id: string): Promise<PresenceViewer[]> {
  return api<{ viewers: PresenceViewer[] }>("note", `/v1/notes/${id}/presence`).then((r) => r.viewers);
}

// ── ask this note ─────────────────────────────────────────────────────

/** `history` is oldest first; the server takes at most `ASK_HISTORY_LIMIT` turns. */
export function askNote(id: string, question: string, history: AskTurn[]): Promise<AskResponse> {
  return api<AskResponse>("note", `/v1/notes/${id}/ask`, {
    method: "POST",
    json: { question, history: history.slice(-ASK_HISTORY_LIMIT) },
  });
}
