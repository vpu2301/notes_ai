// DTOs verified against docs/api/*-openapi.json snapshots.

// ── auth-service ───────────────────────────────────────────────────────

export interface LoginResponse {
  access_token: string;
  expires_in: number;
  token_type?: string;
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
  content?: NoteContent | null;
  section_labels?: SectionLabel[] | null;
}

// ── note-service: sharing (0016) ────────────────────────────────────────

export type NoteVisibility = "private" | "workspace";

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
export type AsrLanguage = "auto" | "en" | "uk";

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
  /** As requested: "auto", "en", "uk". */
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

export interface TranscriptResult {
  job_id: string;
  /** The language the transcript is in (never "auto"). */
  language: string;
  language_detected?: boolean;
  language_probability?: number | null;
  segments: TranscriptSegment[];
  speakers?: string[];
  nlp_applied?: boolean;
}

// ── note-service: transcript ↔ note links ──────────────────────────────

export interface SourceJobLink {
  asr_job_id: string;
  note_id: string;
  code: string;
  status: string;
}
