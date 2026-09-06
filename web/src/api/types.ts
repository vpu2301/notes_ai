// DTOs verified against docs/api/*-openapi.json snapshots — except the
// auth-service block below. `docs/api/auth-service-openapi.json` predates
// IDX-A3/A5/B1b (no /auth/email/*, no /auth/reauth*, no /auth/oauth/token),
// so those DTOs are verified against the routers and
// `services/auth-service/src/auth_service/domain/transport.py` instead.
// Re-verify when the snapshot is regenerated (IDX-W1 debt).

// ── auth-service ───────────────────────────────────────────────────────

/**
 * The pre-IDX login body, and the subset every old reader still parses.
 * `POST /auth/login`, `/auth/refresh` answer exactly this today (both are
 * still Keycloak-backed in both `MDX_IDP_MODE`s).
 */
export interface LoginResponse {
  access_token: string;
  expires_in: number;
  token_type?: string;
  /** Native sessions add these two; web responses omit them. */
  tenant_id?: string;
  roles?: string[];
}

/** `IdentitySummary` — the global principal, independent of workspace. */
export interface Identity {
  id: string;
  email: string;
  display_name: string;
  mfa_enabled: boolean;
  has_password: boolean;
  status: string;
}

/** `MembershipSummary` — one workspace this identity belongs to. */
export interface Membership {
  tenant_id: string;
  name: string;
  kind: "personal" | "team" | string;
  role: string;
  status: string;
}

/**
 * What a sign-in attempt returns (`domain/transport.py::AuthResult`).
 *
 * Discriminated on `status`, NOT on a `kind` field. `mfa_required` is a
 * real 200 carrying an empty `access_token`: the first factor passed and
 * the session has not started. Branch on `status` before reading a token.
 *
 * `refresh_token` is deliberately absent from this type. Native clients
 * get one in the body; a web client must never see or read it — the
 * HttpOnly `mdx_rt` cookie is its only refresh channel, and
 * `tests/no-refresh-token.test.ts` holds that line.
 */
export interface AuthResult {
  status: "authenticated" | "mfa_required";
  access_token: string;
  expires_in: number;
  token_type?: string;
  tenant_id: string;
  roles: string[];
  is_new_identity: boolean;
  identity: Identity | null;
  memberships: Membership[];
  default_tenant_id: string | null;
  /** mfa_required only. */
  challenge_id: string | null;
  methods: string[] | null;
  /** Set only when the sign-in spent a recovery code. Zero is the case that matters. */
  recovery_codes_left: number | null;
  recovery_codes_exhausted: boolean | null;
}

/**
 * `POST /auth/signup` and `/auth/signup/resend` — the uniform 202.
 *
 * Identical for a new address, an address that already has an account, and
 * one with nothing to resend. Nothing in this body varies by branch, so no
 * UI built on it can imply the server recognised the address.
 */
export interface SignupAccepted {
  status: "verification_sent";
  /** Seconds before `/auth/signup/resend` will send another code. */
  resend_after: number;
}

/** `POST /auth/email/start` — identical in shape for every address. */
export interface EmailChallenge {
  challenge_id: string;
  expires_in: number;
  resend_after: number;
}

export type MfaMethod = "totp" | "recovery_code";

/** `POST /auth/reauth/start` — the server decides which methods are offered. */
export interface ReauthOptions {
  /** "totp" + "recovery_code" for an MFA account, else "email_code". */
  methods: string[];
  /** Present only for the email-code path. */
  challenge_id: string | null;
  expires_in: number;
}

/** `POST /auth/security/lockdown` — "this wasn't me". */
export interface LockdownResult {
  reset_token: string;
  expires_in: number;
  sessions_revoked: boolean;
}

/** `GET /auth/password/policy`. */
export interface PasswordPolicy {
  min_length: number;
  max_length: number;
}

export interface MeResponse {
  claims: {
    sub: string;
    tid: string;
    roles: string[];
    scope?: string;
    mfa?: boolean;
    iss?: string;
  };
  /**
   * The per-tenant `users` row. IDX-B2 deletes it; `AuthContext` derives an
   * `Identity` from it only when `identity` is null (keycloak mode), and
   * nothing outside `AuthContext` reads it.
   */
  db_user: {
    sub: string;
    tenant_id: string;
    email: string;
    display_name: string | null;
    role: string;
    status: string;
    mfa_enrolled_at: string | null;
    last_login_at: string | null;
  } | null;
  /**
   * The global principal, and every workspace it holds (IDX-B3).
   *
   * Optional in the type rather than required because both are null/empty
   * in keycloak mode — and because this is what a page load hydrates from,
   * so a client older than the server must not break on their absence.
   */
  identity?: Identity | null;
  memberships?: Membership[];
}

// ── auth-service: account & security (IDX-A5, W2) ─────────────────────

/** One live session on this account (`GET /auth/sessions`). */
export interface SessionInfo {
  sid: string;
  client_type: string;
  device_name: string;
  user_agent: string;
  ip_last: string;
  created_at: string;
  last_used_at: string;
  last_authenticated_at: string;
  /** The browser reading this. Never offered for revocation — that is "sign out". */
  current: boolean;
}

/** `POST /auth/mfa/totp/enroll` — the one response that carries the secret. */
export interface TotpEnrolment {
  enrollment_id: string;
  /** Base32, for typing in by hand when a camera is not an option. */
  secret: string;
  /** What the QR encodes. Never leaves the page. */
  otpauth_uri: string;
  expires_in: number;
}

/** `POST /auth/mfa/totp/confirm` and `POST /auth/mfa/recovery-codes`. */
export interface RecoveryCodes {
  recovery_codes: string[];
}

/** `POST /auth/email/change/start`. */
export interface EmailChangeChallenge {
  challenge_id: string;
  expires_in: number;
}

/** `POST /auth/account/delete`. */
export interface AccountDeletion {
  purge_after: string;
  workspaces_dissolved: number;
}

/** `POST /auth/sessions/revoke-others`. */
export interface RevokedCount {
  revoked: number;
}

// ── auth-service: room devices (IDX-B1b) ──────────────────────────────

/** A secret's public half — enough to recognise it, never to use it. */
export interface CredentialSecret {
  prefix: string;
  expires_at: string | null;
  created_at: string;
}

/** A non-human principal: a meeting-room capture device, or a service. */
export interface Credential {
  id: string;
  kind: string;
  tenant_id: string | null;
  name: string;
  roles: string[];
  status: string;
  last_used_at: string | null;
  created_at: string;
  secrets: CredentialSecret[];
}

/** `POST /tenants/{id}/devices` — the only response that ever carries a secret. */
export interface CreatedCredential {
  credential: Credential;
  secret: string;
}

/** `POST /tenants/{id}/devices/{id}/rotate`. */
export interface RotatedCredential {
  secret: string;
  old_expires_at: string;
}

// ── auth-service: tenants (pre-IDX routes) ────────────────────────────

/** One row of `GET /tenants` — the workspaces the caller belongs to. */
export interface TenantSummary {
  id: string;
  name: string;
  display_name: string;
  slug: string | null;
  status: string;
  is_active: boolean;
  logo_url: string;
  my_role: string;
}

// ── note-service: templates ────────────────────────────────────────────

export type FieldType =
  | "free_text"
  | "date"
  | "date_with_note"
  | "numeric_with_unit"
  | "choice"
  | "multi_choice";

export interface ChoiceOption {
  value: string;
  label: string;
  voice_aliases?: string[];
}

export interface TemplateSection {
  id: string; // section identity — becomes NoteSection.section_key
  name: string;
  field_type?: FieldType;
  required?: boolean;
  min_chars?: number;
  options?: ChoiceOption[];
  order?: number;
  default_content?: string;
}

export interface TemplateDefinition {
  code: string;
  name: string;
  language: string;
  category: string;
  schema_version?: number;
  sections: TemplateSection[];
}

export interface TemplateSummary {
  id: string;
  tenant_id: string | null;
  parent_template_id: string | null;
  code: string;
  name: string;
  language: string;
  category: string;
  schema_version: number;
  is_system: boolean;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface TemplateDetail extends TemplateSummary {
  schema_jsonb: TemplateDefinition;
}

// ── note-service: notes ────────────────────────────────────────────────

export type NoteStatus = "draft" | "finalized" | "amended" | "cancelled";

/**
 * field_specific_metadata contract (libs/note_models/field_metadata.py):
 *  - empty dict = no value;
 *  - user-entered values carry source:"manual" (and must OMIT confidence);
 *  - choice: {selected: value}; multi_choice: {selected: [values]} (≥1);
 *  - date/date_with_note: {date: "YYYY-MM-DD"};
 *  - numeric_with_unit: {value: number, unit: string}.
 */
export type FieldMetadata = Record<string, unknown>;

export interface NoteSection {
  section_key: string;
  text?: string;
  field_specific_metadata?: FieldMetadata;
  transcript_segment_ids?: string[];
}

export interface NoteContent {
  template_id: string;
  template_schema_version: number;
  title?: string;
  sections?: NoteSection[];
}

export interface SectionLabel {
  section_key: string;
  name: { uk: string; en: string };
}

export interface NoteEnvelope {
  id: string;
  code: string;
  status: NoteStatus;
  current_version_id: string;
  current_version_number: number;
  primary_author_id: string;
  co_author_ids: string[];
  title: string;
  created_at: string;
  updated_at: string;
  finalized_at: string | null;
  cancelled_at: string | null;
  /** Who may read it beyond the author team. */
  visibility?: NoteVisibility;
  shared_with_ids?: string[];
  /**
   * Set only when the reader is not on the author team and was not shared
   * the note (an oversight read, sent with `?purpose=`): whose note this
   * is, so the page can say so.
   */
  primary_author_name?: string | null;
  content?: NoteContent | null;
  section_labels?: SectionLabel[] | null;
}

// ── note-service: sharing (0016) ────────────────────────────────────────

export type NoteVisibility = "private" | "workspace";

/**
 * Why someone who is not the note's author is reading it. The server
 * refuses a non-author read without one (422 `missing-read-purpose`) and
 * records the value in the audit trail.
 */
export type ReadPurpose = "review" | "audit" | "legal" | "export" | "collaboration";

export interface SharedMember {
  sub: string;
  email: string;
  display_name: string;
}

export interface PublicLink {
  token: string;
  /** SPA path; prefix with the current origin to get a full URL. */
  path: string;
  created_at: string;
  expires_at: string | null;
  view_count: number;
  last_viewed_at: string | null;
}

export interface SharingView {
  note_id: string;
  visibility: NoteVisibility;
  can_manage: boolean;
  can_delete: boolean;
  shared_with: SharedMember[];
  public_link: PublicLink | null;
}

/** What an anonymous reader gets from a public link. */
export interface SharedNoteView {
  code: string;
  title: string;
  status: string;
  updated_at: string;
  sections: { section_key: string; name: string; text: string }[];
  issuer_name: string;
}

export interface NoteCreatedResponse {
  id: string;
  code: string;
  version_id: string;
  version_number: number;
  status: string;
}

export interface UpdateDraftResponse {
  version_id: string;
  version_number: number;
  status: string;
  diff_summary: Record<string, string[]>;
  idempotent_replay?: boolean;
}

export interface FinalizeResponse {
  id: string;
  status: string;
}

export type NoteAmendmentType = "correction" | "addition" | "clarification";

export interface AmendResponse {
  version_id: string;
  version_number: number;
  parent_version_id: string;
  is_amendment: boolean;
  amendment_type: NoteAmendmentType;
  note_status: string;
  diff_summary: Record<string, string[]>;
}

export interface NoteVersionSummary {
  id: string;
  version_number: number;
  parent_version_id: string | null;
  created_by: string;
  created_at: string;
  is_amendment: boolean;
  amendment_type: NoteAmendmentType | null;
  amendment_reason: string | null;
}

export interface NoteVersionDetail extends NoteVersionSummary {
  content: NoteContent;
  rendered_text: string;
}

export interface SearchHit {
  note_id: string;
  code: string;
  title: string;
  status: string;
  template_id: string;
  primary_author_id: string;
  co_author_ids: string[];
  snippet: string;
  updated_at: string;
}

export interface SearchResponse {
  hits: SearchHit[];
  next_cursor: string | null;
  total_estimated: number | null;
  total_exact?: number | null;
  expanded_terms?: string[];
}

export interface FromTranscriptResponse {
  id: string;
  code: string;
  version_id: string;
  version_number: number;
  status: string;
  template_id: string;
  template_name: string;
  template_selection: "explicit" | "auto" | "fallback";
  template_score?: number | null;
}

// ── asr-service ────────────────────────────────────────────────────────

export type AsrJobStatus = "queued" | "running" | "complete" | "failed" | "cancelled";

/** What a job may be submitted as: detect from the audio, or a pinned language. */
export type AsrLanguage = "auto" | "en" | "uk" | "de";

/** Human name for an ISO 639-1 code, in the viewer's locale; the code itself if unknown. */
export function languageName(code: string | null | undefined): string {
  if (!code || code === "auto") return "";
  try {
    return new Intl.DisplayNames(undefined, { type: "language" }).of(code) ?? code;
  } catch {
    return code;
  }
}

export interface AsrJob {
  id: string;
  tenant_id: string;
  audio_id: string;
  requester_sub: string;
  /** As requested: "auto", "en", "uk", "de". */
  language: string;
  /** What the recording turned out to be in (ISO 639-1); set once complete. */
  detected_language?: string | null;
  model: string;
  status: AsrJobStatus;
  diarize?: boolean;
  queued_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  attempts?: number;
  cancel_requested?: boolean;
  /** Names people gave the diarized speakers (label → name). */
  speaker_names?: Record<string, string>;
  result_url?: string | null;
  error_kind?: string | null;
  /** Safe-to-show explanation built from the kind alone (ADR-0031). */
  error_message: string | null;
  error_stage: string | null;
  error_retryable: boolean | null;
}

// ── notification-service ───────────────────────────────────────────────

export interface NotificationItem {
  id: string;
  category: string;
  title: string;
  body_text: string;
  deep_link: string;
  resource_type: string;
  resource_id: string | null;
  severity: string;
  read_at: string | null;
  created_at: string;
}

export interface FeedPage {
  items: NotificationItem[];
  next_cursor?: string | null;
  unread_count: number;
}

export interface UnreadCount {
  unread_count: number;
}

export interface ReadResult {
  updated: number;
  unread_count: number;
}

// ── asr-service: transcript result ─────────────────────────────────────

export interface TranscriptSegment {
  text: string;
  raw_text: string;
  start_ms: number;
  end_ms: number;
  avg_confidence: number;
  speaker?: string | null;
}

/**
 * One speaker turn, as structured by asr-service: consecutive segments by
 * one speaker, broken into paragraphs at pauses and sentence ends.
 * `speaker` is the neutral label ("SPEAKER_2"), `name` what to show for it
 * (a person's naming, else "Speaker 2"); both null for unattributed speech.
 */
export interface TranscriptTurn {
  speaker: string | null;
  name: string | null;
  start_ms: number;
  end_ms: number;
  paragraphs: string[];
  segment_indices?: number[];
}

export interface TranscriptResult {
  job_id: string;
  /** The language the transcript is in (never "auto"). */
  language: string;
  language_detected?: boolean;
  language_probability?: number | null;
  segments: TranscriptSegment[];
  /** Neutral labels in first-appearance order (diarized jobs). */
  speakers?: string[];
  /** Label → display name for every roster label. */
  speaker_names?: Record<string, string>;
  /** The transcript as speaker turns — what the UI renders. */
  turns?: TranscriptTurn[];
  nlp_applied?: boolean;
}

/** `SPEAKER_2` → `Speaker 2`; anything else unchanged. */
export function defaultSpeakerName(label: string): string {
  return /^SPEAKER_\d+$/.test(label) ? `Speaker ${label.slice(8)}` : label;
}

// ── note-service: transcript ↔ note links ──────────────────────────────

export interface SourceJobLink {
  asr_job_id: string;
  note_id: string;
  code: string;
  status: string;
}

// ── note-service: calendar connections (0019) ──────────────────────────

export interface CalendarConnection {
  id: string;
  /** "google": an OAuth account; "ics": a calendar link (private iCal address, 0020). */
  provider: "google" | "ics";
  account_email: string;
  connected_at: string;
  hidden_calendar_ids: string[];
  needs_reauth: boolean;
  last_synced_at: string | null;
  last_error: string | null;
}

export interface CalendarConnectionsResponse {
  /** False when the server has no Google client configured. */
  available: boolean;
  /** True when the server accepts calendar links (0020); absent on older servers. */
  link_available?: boolean;
  connections: CalendarConnection[];
}

export interface CalendarEntry {
  id: string;
  name: string;
  color: string | null;
  primary: boolean;
  shown: boolean;
}

export interface CalendarListResponse {
  connection_id: string;
  calendars: CalendarEntry[];
}

export interface UpcomingEvent {
  id: string;
  connection_id: string;
  account_email: string;
  calendar_id: string;
  calendar_name: string;
  color: string | null;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  location: string | null;
  meeting_url: string | null;
  html_link: string | null;
  attendee_count: number;
  attendees: string[];
  organizer: string | null;
  response_status: string | null;
}

export interface CalendarProblem {
  connection_id: string;
  account_email: string;
  code: string;
  message: string;
  needs_reauth: boolean;
}

export interface UpcomingEventsResponse {
  available: boolean;
  connected: boolean;
  events: UpcomingEvent[];
  problems: CalendarProblem[];
  fetched_at: string;
}

// ── spaces (note-service, 0021) ───────────────────────────────────────

/** A personal folder of notes, the same on every device. */
export interface Space {
  id: string;
  name: string;
  created_at: string;
  /** The notes filed here, newest filing last. */
  note_ids: string[];
}

export interface SpacesResponse {
  spaces: Space[];
}
