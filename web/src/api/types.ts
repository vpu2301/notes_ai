// ── auth-service ───────────────────────────────────────────────────────

/** `POST /auth/login` and `/auth/refresh` body. */
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
  /** Drives first-run hints. */
  created_at?: string | null;
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
 * Sign-in result. Discriminated on `status`: `mfa_required` is a 200 with an
 * empty `access_token`. `refresh_token` is deliberately absent — the web client
 * must never read it (HttpOnly `mdx_rt` cookie only; tests enforce this).
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

/** `GET /auth/signup/config` — `/join` picks its form by it. */
export interface SignupConfig {
  enabled: boolean;
  min_password_length: number;
  disposable_domains_blocked: true;
}

/** `POST /auth/signup` and `/resend` 202 — identical whether or not the address exists. */
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
  /** Per-tenant `users` row; only `AuthContext` reads it (keycloak mode fallback). */
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
  /** Optional: null/empty in keycloak mode and on older servers. */
  identity?: Identity | null;
  memberships?: Membership[];
}

// ── auth-service: account & security ──────────────────────────────────

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

// ── auth-service: room devices ────────────────────────────────────────

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

// ── auth-service: tenants ─────────────────────────────────────────────

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

/** `POST /auth/token` — an access token for another of my workspaces. */
export interface WorkspaceToken {
  access_token: string;
  expires_in: number;
  tenant_id: string;
  roles: string[];
}

/** `GET /tenants/{id}/members` row (`MemberOut`). */
export interface TenantMember {
  user_sub: string;
  role: string;
  status: string;
  email: string | null;
  display_name: string | null;
  platform_role: string | null;
  created_at: string;
  updated_at: string;
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
  id: string; // becomes NoteSection.section_key
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

/** `finalized` / `amended` no longer occur (ADR-0051). */
export type NoteStatus = "draft" | "finalized" | "amended" | "cancelled";

/**
 * field_specific_metadata: {} = no value; manual values carry source:"manual" and
 * omit confidence; choice {selected}; multi_choice {selected: []}; date {date:
 * "YYYY-MM-DD"}; numeric_with_unit {value, unit}.
 */
export type FieldMetadata = Record<string, unknown>;

export interface NoteSection {
  section_key: string;
  text?: string;
  field_specific_metadata?: FieldMetadata;
  transcript_segment_ids?: string[];
  /** Engine-made heading; absent/null = the block is the note itself. */
  title?: string | null;
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
  /** The transcription job the note was made from, if any. */
  source_job_id?: string | null;
  cancelled_at: string | null;
  /** Who may read it beyond the author team. */
  visibility?: NoteVisibility;
  shared_with_ids?: string[];
  /** Set only on an oversight read (`?purpose=`), so the page can say whose note it is. */
  primary_author_name?: string | null;
  content?: NoteContent | null;
  section_labels?: SectionLabel[] | null;
}

// ── note-service: sharing ───────────────────────────────────────────────

export type NoteVisibility = "private" | "workspace";

/** Required on a non-author read (422 `missing-read-purpose` otherwise); audited. */
export type ReadPurpose = "review" | "audit" | "legal" | "export" | "collaboration";

export interface SharedMember {
  sub: string;
  email: string;
  display_name: string;
}

export type ShareLinkKind = "public" | "recipient";

/** One share link — public or per-recipient. */
export interface LinkView {
  id: string;
  kind: ShareLinkKind;
  /** The sender's own name for the recipient; empty for public links. */
  label: string;
  recipient_email: string | null;
  token: string;
  /** SPA path; prefix with the current origin to get a full URL. */
  path: string;
  /** Opaque referral code the CTA carries into `/join?ref=`. */
  ref_code: string | null;
  created_at: string;
  expires_at: string | null;
  view_count: number;
  first_viewed_at: string | null;
  last_viewed_at: string | null;
  cta_clicked_at: string | null;
  /** Live responses from this link. */
  response_count?: number;
  /** Set when the product mailed the link. */
  delivery_status?: DeliveryStatus;
  sent_at?: string | null;
  send_count?: number;
  /** The error class of the last failed send, never a message. */
  last_send_error?: string;
}

export type DeliveryStatus = "not_sent" | "sent" | "failed" | "suppressed";

/** `GET /v1/admin/sharing/stats` — counts only. */
export interface SharingStats {
  days: 30 | 90;
  links_created: number;
  links_sent: number;
  links_opened: number;
  links_responded: number;
  cta_clicks: number;
  item_responses: number;
  disputes: number;
  opted_out: number;
  dispute_rate: number;
  top_senders: { display_name: string; links: number }[];
}

/** @deprecated name kept for older call sites; the shape is `LinkView`. */
export type PublicLink = LinkView;

export interface CreateLinkRequest {
  kind?: "recipient";
  label: string;
  recipient_email?: string;
  expires_in_days?: number;
  /** Create and mail in one call. */
  send?: boolean;
  personal_message?: string;
  lang?: string;
  source?: "dialog" | "nudge" | "native";
}

export interface SharingView {
  note_id: string;
  visibility: NoteVisibility;
  can_manage: boolean;
  can_delete: boolean;
  shared_with: SharedMember[];
  public_link: LinkView | null;
  /** Every live link, newest first. Empty for readers who may not manage the note. */
  links: LinkView[];
  /** The workspace's effective sharing rules. */
  constraints: SharingConstraints;
}

export interface SharingConstraints {
  external_links_enabled: boolean;
  public_links_enabled: boolean;
  max_link_days: number;
  product_email_enabled: boolean;
  verified_recipients_required: boolean;
}

/** `GET/PUT /v1/admin/sharing/policy` — the whole policy, every time. */
export interface SharingPolicy {
  external_links_enabled: boolean;
  public_links_enabled: boolean;
  max_link_days: number;
  verified_recipients_required: boolean;
  product_email_enabled: boolean;
  cta_enabled: boolean;
  auto_disabled_reason: "abuse_reports" | null;
}

/** `GET /tenants/{id}` (auth-service) — the branding half the settings page edits. */
export interface TenantProfile {
  id: string;
  name: string;
  display_name: string;
  legal_name: string;
  locale: string;
  timezone: string;
  logo_url: string;
  has_logo?: boolean;
  contact_email: string;
  plan?: string;
}

/** One recipient of a server-sent share mail, and what became of it. */
export interface ShareEmailOutcome {
  email: string;
  /** `member` — granted access, mailed an app link. `link` — mailed the public link. */
  access: "member" | "link";
  /** `rejected` is a relay refusing the mailbox: a typo the sender can fix. */
  status: "sent" | "rejected" | "failed";
}

export interface ShareEmailResponse {
  sharing: SharingView;
  results: ShareEmailOutcome[];
  /** True when this send minted the public link, so the sheet can say so. */
  public_link_created: boolean;
}

/** What an anonymous reader gets from a public link. */
export type SharedSectionRole = "decisions" | "action_items" | "attendees" | "transcript" | "other";

export interface SharedSection {
  section_key: string;
  name: string;
  text: string;
  /** Drives the page's fixed hierarchy; `other` collapses below the fold. */
  role: SharedSectionRole;
}

export interface SharedNoteView {
  code: string;
  title: string;
  status: string;
  updated_at: string;
  sections: SharedSection[];
  issuer_name: string;
  sender: {
    issuer_name: string;
    has_logo: boolean;
    logo_path: string | null;
    shared_by_display: string;
  };
  product: {
    brand_name: string;
    header_text: string;
    cta_path: string;
    /** A paid workspace may turn the product line off. */
    cta_enabled?: boolean;
  };
  expires_at: string | null;
  /** Prove the mailbox before acting; reading is still allowed. */
  requires_verification?: boolean;
  /** Nothing shareable yet; the writer is still working. */
  preparing?: boolean;
  lang?: "en" | "de" | "uk";
  changes?: {
    since_version: number;
    sections_changed: string[];
    items_added: string[];
    items_removed: string[];
    items_changed: string[];
  } | null;
  /** Action items, and what this link already did. */
  items: SharedItem[];
  my_flags: string[];
  /** False on a public link: anyone may read it, so nobody can sign it. */
  can_respond: boolean;
}

// ── action items + recipient responses ───────────────────────────────

export type ItemStatus = "open" | "done" | "dropped";
export type ResponseKind = "confirm" | "done" | "dispute" | "flag";

export interface ResponseView {
  id: string;
  link_id: string;
  /** The sender's own label for the recipient ("Tom @ Client"). */
  link_label: string;
  kind: ResponseKind;
  item_key: string | null;
  section_key: string | null;
  /** Recipient-authored. Render as text, never as markup. */
  comment: string | null;
  created_at: string;
  cleared_at: string | null;
}

export interface ItemCounts {
  confirms: number;
  dones: number;
  disputes: number;
}

export interface ItemView {
  id: string;
  item_key: string;
  position: number;
  text: string;
  owner_label: string | null;
  /** 1 when the line said `Name:`; 0.5 when inferred — show "check owner". */
  owner_confidence: number | null;
  due_date: string | null;
  due_text: string | null;
  due_confidence: number | null;
  status: ItemStatus;
  counts: ItemCounts;
  responses: ResponseView[];
}

export interface SharedItem {
  item_key: string;
  text: string;
  owner_label: string | null;
  due_date: string | null;
  due_text: string | null;
  status: ItemStatus;
  my_response: "confirm" | "done" | "dispute" | null;
  my_comment: string | null;
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

/** History only; amendments were retired (ADR-0051). */
export type NoteAmendmentType = "correction" | "addition" | "clarification";

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
  /** Sharing state for the list badge. Absent from an older server. */
  visibility?: NoteVisibility | null;
  shared_with_count?: number | null;
  has_public_link?: boolean | null;
  /** Live recipient disputes, for the "1 disputed" marker. */
  open_disputes?: number;
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
  /** Present when the engine is writing this note. */
  generation?: { id: string; status: string } | null;
  /** Why there is no generation, when there is none. */
  generation_blocked?:
    | "generation_disabled"
    | "budget_exceeded"
    | "processor_unacknowledged"
    | null;
}

// ── series, carry-over and the client version ─────────────────────────

/** An item brought forward from the previous meeting in this series. */
export interface CarriedItem {
  item_key: string;
  text: string;
  owner_label: string | null;
  due_text: string | null;
  /** `done_mentioned` = the recording says so (engine only, with a quote); `done_marked` = the author ticked it. */
  state: "open" | "done_mentioned" | "done_marked" | "dropped";
  done_quote?: string | null;
  done_speaker?: string | null;
}

export interface CarriedView {
  items: CarriedItem[];
  from_note_id: string | null;
  from_note_code: string | null;
  from_date: string | null;
}

export interface ClientSection {
  section_key: string;
  role: string;
  name: string;
  text: string;
}

/** What an external surface renders; preview and shared page use the same builder. */
export interface ClientVersion {
  available: boolean;
  reason: string | null;
  title: string;
  sections: ClientSection[];
  hidden_lines: number;
  hidden_sections: string[];
}

export interface ChecklistItem {
  code: string;
  detail: string;
  count: number;
}

export interface ClientVersionCheck {
  available: boolean;
  /** Warnings, never blockers: the author decides. */
  warnings: ChecklistItem[];
  is_empty: boolean;
}

// ── the workspace glossary + corrections ──────────────────────────────

export type GlossaryKind = "person" | "company" | "product" | "term";

export interface GlossaryTerm {
  id: string;
  term: string;
  kind: GlossaryKind;
  /** How it has been misheard or misspelled before. */
  heard_as: string[];
  created_at: string;
  /** Whether this viewer may remove it (its creator, or an admin). */
  can_delete: boolean;
  /** Still sent to the transcriber; false = stored role label; absent on older servers. */
  in_hint?: boolean;
  /** The note the rename that added it happened in, when known. */
  source_note_id?: string | null;
}

export interface GlossaryHint {
  hint: string;
  terms: number;
}

/** Why a generated line was taken out — closed vocabulary, never free text. */
export type DismissReason =
  | "not_said"
  | "not_a_decision"
  | "not_a_task"
  | "wrong_owner"
  | "wrong_date"
  | "duplicate"
  | "not_relevant";

export interface CorrectionResponse {
  id: string;
  item_key: string;
  section_key: string;
  version_number: number;
  /** The line as it now reads, or null when it was removed. */
  line: string | null;
}

// ── the live meeting note ─────────────────────────────────────────────

/** Capture state; lives on `note_meetings`, not on the note's status (ADR-0051). */
export type MeetingState =
  | "recording"
  | "uploading"
  | "transcribing"
  | "generating"
  | "ready"
  | "no_audio"
  | "failed";

export type MeetingType = "auto" | "client" | "team" | "sales" | "one_on_one" | "interview";

/** What the invite knew. `description` is never stored server-side. */
export interface MeetingCalendarContext {
  source: "google" | "ics" | "eventkit";
  title?: string;
  ical_uid?: string;
  attendee_names?: string[];
  agenda_lines?: string[];
  description?: string;
}

export interface StartMeetingRequest {
  client_capture_id: string;
  title?: string;
  started_at: string;
  language?: AsrLanguage;
  meeting_type?: MeetingType;
  template_id?: string;
  calendar?: MeetingCalendarContext;
}

export interface StartMeetingResponse {
  id: string;
  code: string;
  version_number: number;
  template_id: string;
  state: MeetingState;
}

export interface MeetingView {
  state: MeetingState;
  asr_job_id: string | null;
  meeting_type: MeetingType;
  started_at: string;
}

export interface AttachTranscriptResponse {
  id: string;
  version_number: number;
  state: MeetingState;
}

/** When a typed line was first touched, relative to the recording's t=0. */
export interface LineTime {
  line_key: string;
  offset_ms: number;
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
  /** Bumped by every re-labelling of the speakers (and its undo). */
  diarization_rev?: number;
  /** A speaker re-run; null = never re-labelled (the first pass rides `status`). */
  diarization_status?: DiarizationStatus | null;
  /** Why the last re-run failed, e.g. "stranded", "audio_missing". */
  diarization_error?: string | null;
  /** Re-runs requested so far (the server allows 5). */
  diarization_runs?: number;
  /** A previous labelling can be restored. */
  can_undo_rediarize?: boolean;
  /** Submit response only: the speaker-count hint was used (true), ignored (false), or not sent (null). */
  hints_applied?: boolean | null;
  /** Transcribed share of the speech; null on older jobs. */
  coverage_share?: number | null;
}

export type DiarizationStatus = "queued" | "running" | "complete" | "failed";

/** `POST /asr/jobs/{id}/rediarize` (202) and its `/undo` (200). */
export interface RediarizeAccepted {
  job_id: string;
  diarization_status: DiarizationStatus;
  diarization_rev: number;
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
  /** Index of this segment in the stored artifact (the space `segment_indices` live in). */
  artifact_index?: number;
  /** Set only when this passage is in ANOTHER language than the recording. */
  language?: string | null;
}

/** One speaker turn. `speaker` is the neutral label, `name` the display name; both null when unattributed. */
export interface TranscriptTurn {
  speaker: string | null;
  name: string | null;
  start_ms: number;
  end_ms: number;
  paragraphs: string[];
  /** Opaque artifact indices: send back as-is on a reassign, never index `segments` with them. */
  segment_indices?: number[];
  /** People talked over each other here, or the label was smoothed. */
  uncertain?: boolean;
  /** Set only when the turn is in ANOTHER language than the recording. A turn is never mixed. */
  language?: string | null;
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
  /** Talk time per roster label, after speaker edits. */
  speaker_stats?: SpeakerStat[];
  /** Diarization run the edits apply to. */
  result_rev?: number;
  /** Live speaker edits, application order (latest last). */
  edits?: SpeakerEdit[];
  /** How sure the diarizer is about the number of speakers; null = not diarized / older result. */
  count_confidence?: "high" | "low" | null;
  /** The exact speaker count a person asked for on this labelling. */
  speakers_hint?: number | null;
  /** Names offered for renaming speakers (calendar invitees). */
  name_candidates?: string[];
  /** `local` = microphone, `remote` = call audio. `{}` for mono jobs. */
  speaker_sides?: Record<string, SpeakerSide>;
  /** How each label's name was chosen; `channel` = named after the owner from the microphone. */
  speaker_name_sources?: Record<string, SpeakerNameSource>;
  /** Absent unless the server turns suggestions on — render nothing then. */
  name_suggestions?: NameSuggestion[];
  /** Older labelling with audio still kept: offer a re-label. Absent on older servers. */
  relabel_available?: boolean;
  nlp_applied?: boolean;
  /** Prompt-echo passages dropped and other-language chunks. Absent on older results. */
  diagnostics?: TranscriptDiagnostics;
  /** Transcribed share of the speech and the gaps. Absent/null on older results. */
  coverage?: TranscriptCoverage | null;
  /** When Record was pressed and how long until audio flowed. */
  capture?: CaptureTiming | null;
  /** Stretches ≥ 5 s with no speech. Absent on older results; unknown `kind` renders as noise. */
  noise?: TranscriptNoise[];
  /** `accepted` are already applied in segments/turns; `proposed` await review. Absent on older servers. */
  entity_corrections?: EntityCorrection[];
  /** A correction decision must name this; stale = 409. */
  corrections_rev?: number;
  /** Why nothing was unified: "skipped_budget" | "error" | "disabled"; null = ran. */
  entity_unify?: string | null;
}

export interface EntityCorrection {
  id: string;
  kind: "entity";
  from_forms: string[];
  to_text: string;
  occurrences_count: number;
  source: "glossary" | "calendar" | "hint" | "majority" | "user";
  confidence: number;
  status: "proposed" | "accepted" | "rejected";
  /** A person accepted, edited or rejected it (older servers omit it). */
  decided?: boolean;
}

export interface CorrectionsView {
  job_id: string;
  corrections_rev: number;
  corrections: EntityCorrection[];
}

export interface TranscriptNoise {
  start_ms: number;
  end_ms: number;
  kind: "music" | "silence" | "noise" | (string & {});
}

export type CoverageGapCause =
  | "no_audio"
  | "no_speech_detected"
  | "decoder_empty"
  | "prompt_echo"
  | "other_language"
  | "backend_error"
  | "unknown";

export interface CoverageGap {
  /** For `no_audio`: 0 → the offset, the time BEFORE the file began (not seekable). */
  start_ms: number;
  end_ms: number;
  cause: CoverageGapCause;
}

export interface TranscriptCoverage {
  speech_ms: number;
  transcribed_ms: number;
  first_speech_ms: number | null;
  first_segment_ms: number | null;
  /** transcribed_ms / speech_ms, 0..1. */
  share: number;
  vad: "silero" | "stub";
  gaps: CoverageGap[];
}

export interface CaptureTiming {
  record_pressed_at: string | null;
  first_frame_offset_ms: number | null;
}

export interface PromptEcho {
  start_ms: number;
  end_ms: number;
  words: number;
}

export interface TranscriptDiagnostics {
  prompt_echo: PromptEcho[];
  prompt_echo_segments_dropped: number;
  other_language_chunks: number;
}

/** "SPEAKER_2 is probably Anna Keller" — and the quote that says so. */
export interface NameSuggestion {
  label: string;
  /** Calendar spelling. */
  name: string;
  /** Why, e.g. `self_introduction`. */
  source: string;
  /** ≤ 160 chars; shown before anyone accepts (the evidence). */
  quote: string;
  start_ms: number;
  end_ms: number;
  /** Artifact index space, like `TranscriptTurn.segment_indices`. */
  segment_indices: number[];
}

export type SpeakerSide = "local" | "remote";
export type SpeakerNameSource = "typed" | "picklist" | "channel" | "suggestion" | "cleared";

export interface SpeakerStat {
  label: string;
  speech_ms: number;
  share: number;
  turns: number;
}

export interface SpeakerEdit {
  id: string;
  kind: "merge" | "reassign";
  from_label: string | null;
  to_label: string | null;
  created_at: string;
}

/** `POST /asr/jobs/{id}/speakers/merge` response. */
export interface SpeakerEditResult {
  job_id: string;
  edit_id: string;
  speakers: string[];
  speaker_names: Record<string, string>;
  speaker_stats: SpeakerStat[];
}

/** `POST /asr/jobs/{id}/speakers/reassign` response. */
export interface ReassignResult extends SpeakerEditResult {
  /** The label a `to: "new"` reassign created; null otherwise. */
  created_label: string | null;
}

/** Where a capture came from — a metric, sent with the upload. */
export type CaptureSource = "calendar_event" | "manual" | "upload";

/** `mic_system`: 2-channel file, left = microphone, right = system audio. */
export type ChannelLayout = "mono" | "mic_system";

/** `sources` on a rename: picked from `name_candidates`, typed, or an accepted suggestion. */
export type NameSource = "picklist" | "typed" | "suggestion";

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

// ── note-service: calendar connections ─────────────────────────────────

export interface CalendarConnection {
  id: string;
  /** "google": an OAuth account; "ics": a private iCal address. */
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
  /** True when the server accepts calendar links; absent on older servers. */
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
  /** Stable across the copies an invite makes in several calendars. */
  ical_uid: string;
  /** Derived from the invite's description, which never leaves the server. */
  agenda_lines: string[];
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

// ── spaces (note-service) ─────────────────────────────────────────────

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

// ── ask this note (POST /v1/notes/{id}/ask) ───────────────────────────

/** One line of the thread; the client keeps it and sends it back as context. */
export interface AskTurn {
  role: "user" | "assistant";
  text: string;
}

/** The server refuses more than this many turns of history. */
export const ASK_HISTORY_LIMIT = 12;

export interface AskResponse {
  answer: string;
  backend: string;
  model_id: string;
}

// ── model tiers, processors, budget ────────────────────────────────

/** One company in the data path, as the registry itself reports it. */
export interface AiProcessor {
  name: string;
  region: string;
  /** What it does with the data — "writing your meeting notes", … */
  purpose: string;
  /** Which tiers route to it. */
  tiers: string[];
  acknowledged: boolean;
}

/** The backend writing notes; `reason` set when the fallback is in use. */
export interface AiWriter {
  backend: string;
  model_id: string | null;
  processor: string | null;
  region: string | null;
  primary: string;
  fallback: string | null;
  /** null while the primary is in use; else missing_env | forced | probe_failed. */
  reason: string | null;
}

export interface AiSettings {
  provider: string;
  tier: string;
  generation_enabled: boolean;
  /** Differs from `tier` when routing gained an unacknowledged processor. */
  effective_provider: string;
  effective_tier: string;
  processors: AiProcessor[];
  needs_acknowledgement: AiProcessor[];
  month_to_date_cents: number;
  budget_cents: number;
  may_choose_premium: boolean;
  can_edit: boolean;
  /** Who writes notes right now (null where nothing is routed). */
  writer?: AiWriter | null;
  small_writer?: AiWriter | null;
}

export interface AiSettingsUpdate {
  provider?: string;
  tier?: string;
  generation_enabled?: boolean;
  monthly_budget_cents?: number;
  acknowledge?: { name: string; region: string }[];
}

// ── The document engine, as the client sees it ─────────────────────

export interface GenerationView {
  id: string;
  status: "queued" | "running" | "partial" | "complete" | "failed" | "superseded";
  step: string | null;
  windows_total: number | null;
  windows_done: number | null;
  windows_failed: number | null;
  /** `[[start_ms, end_ms]]` of the missing minutes. */
  failed_ranges: number[][];
  prompt_version: string;
  model_id: string | null;
  /** Closed vocabulary; the client turns it into a sentence. */
  error_kind: string | null;
  created_at: string;
  finished_at: string | null;
  /** Sections the engine skipped because the author had already written there. */
  suggested_sections: string[];
  /** 0 on a finished run = nothing passed the verifier. */
  sections_written?: number | null;
  /** Stretches left out of the notes; empty for older generations. */
  excluded_ranges?: ExcludedRange[];
  /** How the facts spread over the recording; null for older generations. */
  coverage?: GenerationCoverage | null;
  /** What the recording was taken to be, and who decided. */
  recording_type?: string | null;
  recording_type_source?: "user" | "classifier" | "rule" | "template" | null;
  /** The spoken language the run wrote in. */
  language?: string | null;
}

export type ExcludedReason =
  | "background"
  | "other_language"
  | "artifact"
  | "duplicate"
  | "unrelated";

export interface ExcludedRange {
  start_ms: number;
  end_ms: number;
  reason: ExcludedReason | string;
}

export interface GenerationCoverage {
  /** Facts found in the first, middle and last third of the recording. */
  facts_by_third: number[];
  speech_ms: number;
  excluded_ms: number;
}

export interface GeneratedItem {
  item_key: string;
  kind: string;
  section_key: string;
  text: string;
  owner_label: string | null;
  due_text: string | null;
  due_date: string | null;
  explicit: boolean;
  confidence: number;
  flags: string[];
  quote: string;
  start_ms: number;
  end_ms: number;
  speaker_label: string | null;
  speaker_name: string | null;
  placement: string;
  /** Item keys of the facts this line rests on. */
  cites?: string[];
  certainty?: "fact" | "estimate" | "prediction" | "opinion" | "proposal" | "allegation" | null;
  /** Whose position it is. */
  attributed_to?: string | null;
  /** For a sub-point, the row key of the bullet it sits under. */
  parent_key?: string | null;
  /** A figure row's verified fields (every word in its quote). */
  figure?: { name: string; value: string; unit: string; qualifier: string } | null;
  /** Names respelled in this line; the quote keeps what was heard. */
  corrections?: { surface: string; canonical: string; source: string }[];
  /** Dates the line names, resolved against the recording day. */
  mentions?: { text: string; date: string; time: string | null; direction: string }[];
}

// ─── Billing ─────────────────────────────────────────────────────────────

export interface BillingPlan {
  code: string;
  name: string;
  summary: string;
  /** Whole cents per member per month; null = "talk to us". */
  price_cents: number | null;
  currency: string;
  /** Per member per year when paid yearly; null = monthly only. */
  yearly_price_cents: number | null;
  limits: Record<string, number | null>;
  features: string[];
  self_serve: boolean;
}

export interface UsageMeter {
  key: "notes" | "recording_minutes" | "members" | "ai";
  used: number;
  /** null = no limit on this plan. */
  limit: number | null;
}

export interface BillingSubscription {
  provider: string;
  status: "active" | "trialing" | "past_due" | "canceled";
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  interval: BillingInterval;
}

export type BillingInterval = "monthly" | "yearly";

export interface Billing {
  plan: BillingPlan;
  plans: BillingPlan[];
  usage: UsageMeter[];
  period_start: string;
  subscription: BillingSubscription | null;
  payments_connected: boolean;
  can_edit: boolean;
}

export interface ChangePlanResult {
  action: "applied" | "redirect";
  redirect_url: string | null;
  billing: Billing;
}
