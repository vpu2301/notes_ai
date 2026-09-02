import Foundation

// MARK: - Backend configuration

struct BackendSettings: Codable, Equatable, Sendable {
    var authBaseURL: String
    var asrBaseURL: String
    var noteBaseURL: String
    var webAppURL: String

    static let `default` = BackendSettings(
        authBaseURL: "http://localhost:8000",
        asrBaseURL: "http://localhost:8001",
        noteBaseURL: "http://localhost:8006",
        webAppURL: "http://localhost:5173"
    )
}

// MARK: - Auth (auth-service)

struct LoginResponse: Decodable, Sendable {
    let accessToken: String
    let expiresIn: Int

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case expiresIn = "expires_in"
    }
}

// MARK: - Batch transcription (asr-service)

enum JobStatus: String, Codable, Sendable {
    case queued, running, complete, failed, cancelled

    var isTerminal: Bool {
        switch self {
        case .complete, .failed, .cancelled: return true
        case .queued, .running: return false
        }
    }

    var label: String {
        switch self {
        case .queued: return "Queued"
        case .running: return "Transcribing"
        case .complete: return "Done"
        case .failed: return "Failed"
        case .cancelled: return "Cancelled"
        }
    }
}

/// Subset of `TranscriptionJobView` this app needs.
struct TranscriptionJob: Decodable, Sendable {
    let id: String
    let status: JobStatus
    /// ISO 639-1 code of the language the recording turned out to be in.
    /// Set once the job completes; nil while it is still running.
    let detectedLanguage: String?
    let errorMessage: String?
    let errorKind: String?

    enum CodingKeys: String, CodingKey {
        case id, status
        case detectedLanguage = "detected_language"
        case errorMessage = "error_message"
        case errorKind = "error_kind"
    }

    /// Human-readable failure text (`error_message` is documented as safe to show).
    var failureText: String {
        var text = errorMessage ?? "Transcription failed."
        if let kind = errorKind, !kind.isEmpty {
            text += " (\(kind))"
        }
        return text
    }
}

// MARK: - Templates & notes (note-service)

struct TemplateSummary: Decodable, Sendable {
    let id: String
    let code: String
    let name: String
    let language: String
}

struct FromTranscriptRequest: Encodable, Sendable {
    let asrJobId: String
    let templateId: String?
    let title: String

    enum CodingKeys: String, CodingKey {
        case asrJobId = "asr_job_id"
        case templateId = "template_id"
        case title
    }
}

struct FromTranscriptResponse: Decodable, Sendable {
    let id: String
    let code: String

    enum CodingKeys: String, CodingKey {
        case id, code
    }
}

// MARK: - RFC 9457 problem body

struct Problem: Decodable, Sendable {
    let title: String?
    let detail: String?
    let status: Int?
    let code: String?
}

enum APIError: LocalizedError {
    case badURL
    case http(status: Int, problem: Problem?)
    case notAuthenticated

    var errorDescription: String? {
        switch self {
        case .badURL:
            return "Invalid backend URL — check Settings."
        case .notAuthenticated:
            return "Signed out — please sign in again."
        case .http(let status, let problem):
            var message = problem?.detail ?? problem?.title ?? "Request failed (HTTP \(status))."
            if let code = problem?.code, !code.isEmpty {
                message += " [\(code)]"
            }
            return message
        }
    }

    /// `PUT /draft` answers 409 when someone saved a newer version first.
    var isConflict: Bool {
        if case .http(let status, _) = self { return status == 409 }
        return false
    }

    /// The auth service answers 401 with a problem hinting a one-time code is needed.
    var isMFARequired: Bool {
        guard case .http(let status, let problem) = self, status == 401 else { return false }
        let haystack = [problem?.code, problem?.title, problem?.detail]
            .compactMap { $0?.lowercased() }
            .joined(separator: " ")
        return haystack.contains("mfa") || haystack.contains("otp") || haystack.contains("one-time")
    }
}

// MARK: - Recent captures (persisted locally)

struct RecentCapture: Codable, Identifiable, Equatable, Sendable {
    var jobId: String
    var title: String
    var createdAt: Date
    var status: JobStatus?
    var noteId: String?
    var errorMessage: String?

    var id: String { jobId }
}

// MARK: - Notes (note-service) — the document the Mac app opens natively

enum NoteStatus: String, Codable, Sendable {
    case draft, finalized, amended, cancelled

    var label: String {
        switch self {
        case .draft: return "Draft"
        case .finalized: return "Finalized"
        case .amended: return "Amended"
        case .cancelled: return "Cancelled"
        }
    }
}

/// Arbitrary JSON, so `field_specific_metadata` round-trips untouched.
enum JSONValue: Codable, Equatable, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case null
    case array([JSONValue])
    case object([String: JSONValue])

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null; return }
        if let value = try? container.decode(Bool.self) { self = .bool(value); return }
        if let value = try? container.decode(Double.self) { self = .number(value); return }
        if let value = try? container.decode(String.self) { self = .string(value); return }
        if let value = try? container.decode([JSONValue].self) { self = .array(value); return }
        self = .object(try container.decode([String: JSONValue].self))
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .null: try container.encodeNil()
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        }
    }

    var stringValue: String? {
        if case .string(let value) = self { return value }
        return nil
    }
}

struct NoteSection: Codable, Equatable, Sendable {
    var sectionKey: String
    var text: String?
    var fieldSpecificMetadata: [String: JSONValue]?
    var transcriptSegmentIds: [String]?

    enum CodingKeys: String, CodingKey {
        case sectionKey = "section_key"
        case text
        case fieldSpecificMetadata = "field_specific_metadata"
        case transcriptSegmentIds = "transcript_segment_ids"
    }
}

struct NoteContent: Codable, Equatable, Sendable {
    var templateId: String
    var templateSchemaVersion: Int
    var title: String?
    var sections: [NoteSection]?

    enum CodingKeys: String, CodingKey {
        case templateId = "template_id"
        case templateSchemaVersion = "template_schema_version"
        case title, sections
    }

    func section(_ key: String) -> NoteSection {
        sections?.first { $0.sectionKey == key } ?? NoteSection(sectionKey: key)
    }

    mutating func upsert(_ section: NoteSection) {
        var list = sections ?? []
        if let index = list.firstIndex(where: { $0.sectionKey == section.sectionKey }) {
            list[index] = section
        } else {
            list.append(section)
        }
        sections = list
    }
}

struct SectionLabel: Decodable, Sendable {
    let sectionKey: String
    let name: [String: String]

    enum CodingKeys: String, CodingKey {
        case sectionKey = "section_key"
        case name
    }
}

struct NoteEnvelope: Decodable, Sendable {
    let id: String
    let code: String
    let status: NoteStatus
    let currentVersionNumber: Int
    let title: String
    let createdAt: Date
    let updatedAt: Date
    /// "private" or "workspace" (0016).
    let visibility: String?
    let content: NoteContent?
    let sectionLabels: [SectionLabel]?

    enum CodingKeys: String, CodingKey {
        case id, code, status, title, content, visibility
        case currentVersionNumber = "current_version_number"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case sectionLabels = "section_labels"
    }
}

// MARK: - Sharing (0016)

struct SharedMember: Decodable, Sendable, Identifiable {
    let sub: String
    let email: String
    let displayName: String
    var id: String { sub }

    enum CodingKeys: String, CodingKey {
        case sub, email
        case displayName = "display_name"
    }
}

struct PublicLink: Decodable, Sendable {
    let token: String
    /// SPA path; prefix with the web app origin for a full URL.
    let path: String
    let viewCount: Int

    enum CodingKeys: String, CodingKey {
        case token, path
        case viewCount = "view_count"
    }
}

struct SharingView: Decodable, Sendable {
    let noteId: String
    let visibility: String
    let canManage: Bool
    let canDelete: Bool
    let sharedWith: [SharedMember]
    let publicLink: PublicLink?

    enum CodingKeys: String, CodingKey {
        case visibility
        case noteId = "note_id"
        case canManage = "can_manage"
        case canDelete = "can_delete"
        case sharedWith = "shared_with"
        case publicLink = "public_link"
    }
}

struct UpdateDraftRequest: Encodable, Sendable {
    let content: NoteContent
    let expectedVersion: Int

    enum CodingKeys: String, CodingKey {
        case content
        case expectedVersion = "expected_version"
    }
}

struct UpdateDraftResponse: Decodable, Sendable {
    let versionNumber: Int

    enum CodingKeys: String, CodingKey {
        case versionNumber = "version_number"
    }
}

/// One section of a template definition (`schema_jsonb.sections[]`).
struct TemplateSectionDef: Decodable, Sendable, Identifiable {
    let id: String
    let name: String
    let fieldType: String?
    let required: Bool?
    let minChars: Int?
    let order: Int?

    enum CodingKeys: String, CodingKey {
        case id, name, required, order
        case fieldType = "field_type"
        case minChars = "min_chars"
    }

    var isFreeText: Bool { fieldType == nil || fieldType == "free_text" }
}

struct TemplateDetail: Decodable, Sendable {
    struct Definition: Decodable, Sendable {
        let sections: [TemplateSectionDef]
    }

    let id: String
    let name: String
    let schemaJsonb: Definition

    enum CodingKeys: String, CodingKey {
        case id, name
        case schemaJsonb = "schema_jsonb"
    }
}

// MARK: - Transcript (asr-service)

struct TranscriptSegment: Decodable, Sendable {
    let text: String
    let startMs: Int
    let endMs: Int
    let speaker: String?

    enum CodingKeys: String, CodingKey {
        case text, speaker
        case startMs = "start_ms"
        case endMs = "end_ms"
    }
}

/// One speaker turn as structured by asr-service: consecutive segments by
/// one speaker, broken into paragraphs at pauses and sentence ends.
/// `speaker` is the neutral label ("SPEAKER_2"); `name` is what to show
/// for it (a person's naming, else "Speaker 2"). Both nil for speech the
/// diarizer could not attribute.
struct TranscriptTurn: Decodable, Identifiable, Equatable, Sendable {
    let speaker: String?
    let name: String?
    let startMs: Int
    let endMs: Int
    let paragraphs: [String]

    /// Turns are chronological and non-overlapping, so the start is unique.
    var id: Int { startMs }

    enum CodingKeys: String, CodingKey {
        case speaker, name, paragraphs
        case startMs = "start_ms"
        case endMs = "end_ms"
    }
}

struct TranscriptResult: Decodable, Sendable {
    let jobId: String
    let segments: [TranscriptSegment]
    /// Neutral labels in first-appearance order (diarized jobs).
    let speakers: [String]?
    /// Label → display name for every roster label.
    let speakerNames: [String: String]?
    /// The transcript as speaker turns — what the Transcript tab renders.
    let turns: [TranscriptTurn]?

    enum CodingKeys: String, CodingKey {
        case jobId = "job_id"
        case segments, speakers, turns
        case speakerNames = "speaker_names"
    }
}

/// `SPEAKER_2` → `Speaker 2`; anything else unchanged.
func defaultSpeakerName(_ label: String) -> String {
    guard label.hasPrefix("SPEAKER_") else { return label }
    let digits = label.dropFirst("SPEAKER_".count)
    guard !digits.isEmpty, digits.allSatisfy(\.isNumber) else { return label }
    return "Speaker \(digits)"
}

/// What the transcript body shows for speech nobody was matched to.
let unknownSpeakerName = "Unknown speaker"

struct SpeakerNamesRequest: Encodable, Sendable {
    let names: [String: String]
}

struct SpeakerNamesResponse: Decodable, Sendable {
    let jobId: String
    let speakerNames: [String: String]

    enum CodingKeys: String, CodingKey {
        case jobId = "job_id"
        case speakerNames = "speaker_names"
    }
}

// MARK: - Note list (note-service search)

/// One row of `GET /v1/notes/search` — the home page's notes list.
struct NoteSummary: Decodable, Identifiable, Equatable, Sendable {
    let noteId: String
    let code: String
    let title: String
    let status: NoteStatus?
    let snippet: String
    let updatedAt: Date

    var id: String { noteId }

    enum CodingKeys: String, CodingKey {
        case noteId = "note_id"
        case code, title, status, snippet
        case updatedAt = "updated_at"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        noteId = try c.decode(String.self, forKey: .noteId)
        code = try c.decode(String.self, forKey: .code)
        title = try c.decode(String.self, forKey: .title)
        status = NoteStatus(rawValue: try c.decode(String.self, forKey: .status))
        snippet = (try? c.decode(String.self, forKey: .snippet)) ?? ""
        updatedAt = try c.decode(Date.self, forKey: .updatedAt)
    }
}

struct SearchResponse: Decodable, Sendable {
    let hits: [NoteSummary]
    let nextCursor: String?

    enum CodingKeys: String, CodingKey {
        case hits
        case nextCursor = "next_cursor"
    }
}

// MARK: - Spaces (local)

/// A folder for notes. Spaces are this Mac's own organisation, kept in
/// UserDefaults; the server has no such concept yet.
struct Space: Codable, Identifiable, Equatable, Sendable {
    var id: String
    var name: String
    var createdAt: Date
}

// MARK: - Selection

/// What the main window's detail pane shows.
enum Selection: Equatable {
    /// One of this Mac's captures (by ASR job id) — a note once it has one.
    case capture(jobId: String)
    /// Any note from the tenant, by note id.
    case note(noteId: String)
}
