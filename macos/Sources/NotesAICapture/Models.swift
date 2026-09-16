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

/// Who is signed in. `GET /auth/me` and every `AuthResult` return it.
struct IdentitySummary: Codable, Equatable, Sendable {
    let id: String
    let email: String
    var displayName: String = ""
    var mfaEnabled: Bool = false
    var hasPassword: Bool = false
    var status: String = "active"

    enum CodingKeys: String, CodingKey {
        case id, email, status
        case displayName = "display_name"
        case mfaEnabled = "mfa_enabled"
        case hasPassword = "has_password"
    }
}

/// One workspace this identity can reach. Read but not yet acted on: the
/// switcher is IDX-M2's, and `POST /auth/token` does not exist yet.
struct MembershipSummary: Codable, Equatable, Sendable {
    let tenantId: String
    let name: String
    let kind: String
    let role: String
    let status: String

    enum CodingKeys: String, CodingKey {
        case name, kind, role, status
        case tenantId = "tenant_id"
    }
}

/// A started session, as the server hands it over.
///
/// `refreshToken` is nil when the server put it in a cookie instead —
/// which means it thinks it is talking to a browser, and this app has no
/// cookie store to keep it in. The sign-in path treats that as an error
/// rather than pretending to be signed in for fifteen minutes.
struct AuthSession: Equatable, Sendable {
    let accessToken: String
    let expiresIn: Int
    let tenantId: String
    let roles: [String]
    let refreshToken: String?
    let refreshExpiresIn: Int?
    let identity: IdentitySummary?
    let memberships: [MembershipSummary]
    let isNewIdentity: Bool
}

/// What a sign-in attempt answers: a session, or a second factor owed.
///
/// The server discriminates on `status` — not on `kind`, whatever the
/// sprint pack says — and an `mfa_required` result is a real 200 whose
/// token fields are empty on purpose (IDX-A5: nothing about the account
/// is disclosed on the near side of the second factor).
enum AuthResult: Sendable {
    case authenticated(AuthSession)
    case mfaRequired(challengeId: String, methods: [String], expiresIn: Int)
}

/// The wire shape of `AuthResult`, and the `LoginResponse` before it —
/// `/auth/login` (Keycloak) answers the three token fields and nothing
/// else, and every field below is optional so one decoder reads both.
struct AuthResultDTO: Decodable, Sendable {
    var status: String = "authenticated"
    var accessToken: String = ""
    var expiresIn: Int = 0
    var tenantId: String = ""
    var roles: [String] = []
    var refreshToken: String?
    var refreshExpiresIn: Int?
    var isNewIdentity = false
    var identity: IdentitySummary?
    var memberships: [MembershipSummary] = []
    var defaultTenantId: String?
    var challengeId: String?
    var methods: [String]?
    var recoveryCodesLeft: Int?

    enum CodingKeys: String, CodingKey {
        case status, roles, identity, memberships, methods
        case accessToken = "access_token"
        case expiresIn = "expires_in"
        case tenantId = "tenant_id"
        case refreshToken = "refresh_token"
        case refreshExpiresIn = "refresh_expires_in"
        case isNewIdentity = "is_new_identity"
        case defaultTenantId = "default_tenant_id"
        case challengeId = "challenge_id"
        case recoveryCodesLeft = "recovery_codes_left"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "authenticated"
        accessToken = try c.decodeIfPresent(String.self, forKey: .accessToken) ?? ""
        expiresIn = try c.decodeIfPresent(Int.self, forKey: .expiresIn) ?? 0
        tenantId = try c.decodeIfPresent(String.self, forKey: .tenantId) ?? ""
        roles = try c.decodeIfPresent([String].self, forKey: .roles) ?? []
        refreshToken = try c.decodeIfPresent(String.self, forKey: .refreshToken)
        refreshExpiresIn = try c.decodeIfPresent(Int.self, forKey: .refreshExpiresIn)
        isNewIdentity = try c.decodeIfPresent(Bool.self, forKey: .isNewIdentity) ?? false
        identity = try c.decodeIfPresent(IdentitySummary.self, forKey: .identity)
        memberships = try c.decodeIfPresent([MembershipSummary].self, forKey: .memberships) ?? []
        defaultTenantId = try c.decodeIfPresent(String.self, forKey: .defaultTenantId)
        challengeId = try c.decodeIfPresent(String.self, forKey: .challengeId)
        methods = try c.decodeIfPresent([String].self, forKey: .methods)
        recoveryCodesLeft = try c.decodeIfPresent(Int.self, forKey: .recoveryCodesLeft)
    }

    /// The DTO as the two cases the app actually branches on.
    func result() throws -> AuthResult {
        if status == "mfa_required" {
            guard let challengeId else { throw APIError.malformedResponse }
            return .mfaRequired(challengeId: challengeId,
                                methods: methods ?? ["totp"],
                                expiresIn: expiresIn)
        }
        guard !accessToken.isEmpty else { throw APIError.malformedResponse }
        return .authenticated(AuthSession(
            accessToken: accessToken,
            expiresIn: expiresIn,
            tenantId: tenantId,
            roles: roles,
            refreshToken: refreshToken,
            refreshExpiresIn: refreshExpiresIn,
            identity: identity,
            memberships: memberships,
            isNewIdentity: isNewIdentity))
    }
}

/// `POST /auth/email/start` — the code is in the mail, never in the reply.
struct EmailChallenge: Decodable, Sendable {
    let challengeId: String
    let expiresIn: Int
    let resendAfter: Int

    enum CodingKeys: String, CodingKey {
        case challengeId = "challenge_id"
        case expiresIn = "expires_in"
        case resendAfter = "resend_after"
    }
}

/// `POST /auth/reauth/start` — the server decides how you may prove it is
/// you (an authenticator if you have one, a mailed code otherwise).
struct ReauthOptions: Decodable, Sendable {
    let methods: [String]
    let challengeId: String?
    let expiresIn: Int

    enum CodingKeys: String, CodingKey {
        case methods
        case challengeId = "challenge_id"
        case expiresIn = "expires_in"
    }
}

/// `GET /auth/me`. `identity` arrives once `routers/me.py` grows it
/// (IDX-B2 debt); until then the app keeps the summary from sign-in.
struct MeResponse: Decodable, Sendable {
    let identity: IdentitySummary?
    let memberships: [MembershipSummary]?
}

/// A step-up the app is waiting on: which methods the server will accept,
/// the challenge id when it mailed a code, and the way back to whatever
/// asked. Not `Sendable` — it is a piece of main-actor UI state, and the
/// continuation it closes over belongs to exactly one request.
@MainActor
struct ReauthPrompt: Identifiable {
    let id = UUID()
    let methods: [String]
    let challengeId: String?
    let answer: (Bool) -> Void

    var offersTOTP: Bool { methods.contains("totp") }
    var offersRecoveryCode: Bool { methods.contains("recovery_code") }
    var offersEmailCode: Bool { methods.contains("email_code") }
}

extension Locale {
    /// The language the server should write its mail in, when this Mac's
    /// is one it has copy for. Anything else is left to the server's own
    /// default — sending `fr` would be refused outright (the field is a
    /// closed enum), which is a poor reason to fail a sign-in.
    static var preferredLanguageCode: String? {
        let supported: Set<String> = ["en", "de", "uk"]
        for identifier in Locale.preferredLanguages {
            let code = Locale(identifier: identifier).language.languageCode?.identifier ?? ""
            if supported.contains(code) { return code }
        }
        return nil
    }
}

/// Why the app dropped to the sign-in screen. The wording differs, and
/// so does what the person should do about it.
enum SessionLostReason: Equatable, Sendable {
    /// The session ended: idle timeout, an explicit revoke, a server that
    /// no longer knows the token.
    case expired
    /// A rotated refresh token was presented twice. The server revoked
    /// every session and denylisted the account's access tokens.
    case securityRevoked
    /// The identity is disabled, or has no workspace left.
    case accountUnavailable(String)

    var message: String {
        switch self {
        case .expired:
            return "Your session ended. Sign in again."
        case .securityRevoked:
            return "You were signed out for security. Sign in again."
        case .accountUnavailable(let detail):
            return detail
        }
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

/// RFC 9457 problem body, plus the two things that arrive beside it.
///
/// `code` is the member clients branch on (`docs/api/error-codes.md`);
/// `detail` is for people and may change. `requestId` and `retryAfter`
/// come from headers rather than the body — they are here because
/// everything that has to say something useful about a failure needs all
/// three in one place.
struct Problem: Decodable, Sendable {
    /// The RFC 9457 `type` URI — how a client tells one 422 from another.
    var type: String? = nil
    let title: String?
    let detail: String?
    let status: Int?
    let code: String?
    /// Extras the auth service attaches: how many tries are left on a code.
    var attemptsLeft: Int?
    /// Filled from `X-Request-Id`, so an unrecognised failure still gives
    /// the person something to quote and the logs something to match.
    var requestId: String?
    /// Filled from `Retry-After`, in seconds.
    var retryAfter: Int?

    enum CodingKeys: String, CodingKey {
        case type, title, detail, status, code
        case attemptsLeft = "attempts_left"
    }
}

enum APIError: LocalizedError {
    case badURL
    case http(status: Int, problem: Problem?)
    case notAuthenticated
    /// A rotated refresh token was replayed: the server revoked the
    /// session and every access token behind it.
    case sessionRevoked
    /// A step-up endpoint wants proof of identity inside the reauth
    /// window. `AppState` presents the sheet; the caller retries once.
    case reauthRequired
    /// The server answered 200 with something this app cannot read.
    case malformedResponse
    /// The sign-in worked, but the server kept the refresh token itself
    /// (it answered as if to a browser). There is nothing for this Mac to
    /// store, and a session that cannot be renewed is not one to claim.
    case noNativeSession

    var errorDescription: String? {
        switch self {
        case .badURL:
            return "Invalid backend URL — check Settings."
        case .notAuthenticated:
            return "Signed out — please sign in again."
        case .sessionRevoked:
            return SessionLostReason.securityRevoked.message
        case .reauthRequired:
            return "Confirm it is really you to continue."
        case .malformedResponse:
            return "Could not read the server's response."
        case .noNativeSession:
            return "This server cannot keep this Mac signed in. Ask for the new sign-in to be enabled, or use the web app."
        case .http:
            return AuthCopy.message(for: self)
        }
    }

    var problem: Problem? {
        if case .http(_, let problem) = self { return problem }
        return nil
    }

    var status: Int? {
        if case .http(let status, _) = self { return status }
        return nil
    }

    /// The machine-readable code, when the server sent one.
    var code: String? {
        guard let code = problem?.code, !code.isEmpty else { return nil }
        return code
    }

    /// `PUT /draft` answers 409 when someone saved a newer version first.
    var isConflict: Bool {
        if case .http(let status, _) = self { return status == 409 }
        return false
    }

    /// A read of somebody else's note came without `?purpose=`. The note
    /// is readable — the caller retries once with a `ReadPurpose` and says
    /// whose note it is showing.
    var needsReadPurpose: Bool {
        guard case .http(let status, let problem) = self, status == 422 else { return false }
        return problem?.type == "https://errors.notes-ai/missing-read-purpose"
    }

    /// The Keycloak-era login answers 401 with a problem hinting a
    /// one-time code is needed. Native sign-in says so in the body
    /// (`status: "mfa_required"`) instead, so this is only reached
    /// against a deployment that has not cut over yet.
    var isMFARequired: Bool {
        guard case .http(let status, let problem) = self, status == 401 else { return false }
        let haystack = [problem?.code, problem?.title, problem?.detail]
            .compactMap { $0?.lowercased() }
            .joined(separator: " ")
        return haystack.contains("mfa") || haystack.contains("otp") || haystack.contains("one-time")
    }

    /// A permission denial from `libs/auth`'s role gate — `403 deny:
    /// roles=[…] cannot 'note.read' on 'note'`. It carries no machine
    /// code, so the prefix of `detail` is the only marker there is.
    ///
    /// Worth telling apart from every other 403 because the roles a token
    /// carries are re-read from the workspace membership on every refresh:
    /// a token minted before a role was granted keeps denying until it
    /// rotates, and one refresh is the whole fix.
    var isRoleDenial: Bool {
        guard case .http(let status, let problem) = self, status == 403 else { return false }
        return problem?.detail?.hasPrefix("deny:") ?? false
    }

    /// The endpoint does not exist on this server — a deployment still
    /// running the old identity provider, or one that has not been given
    /// the native password grant (IDX-A4).
    var isNotFound: Bool { status == 404 }
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
    let primaryAuthorId: String?
    /// Only sent on an oversight read (not our note, not shared with us):
    /// whose note this is, so the screen can say so.
    let primaryAuthorName: String?
    let content: NoteContent?
    let sectionLabels: [SectionLabel]?

    enum CodingKeys: String, CodingKey {
        case id, code, status, title, content, visibility
        case currentVersionNumber = "current_version_number"
        case primaryAuthorId = "primary_author_id"
        case primaryAuthorName = "primary_author_name"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case sectionLabels = "section_labels"
    }
}

/// Why someone who is not the note's author is reading it. The server
/// refuses a non-author read without one and records the value.
enum ReadPurpose: String, Sendable {
    case review, audit, legal, export, collaboration
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

/// One recipient of a server-sent share mail, and what became of it.
struct ShareEmailOutcome: Decodable, Sendable, Identifiable {
    let email: String
    /// `member` — granted access, mailed an app link. `link` — mailed the public link.
    let access: String
    /// `rejected` is a relay refusing the mailbox: a typo the sender can fix.
    let status: String

    var id: String { email }
    var sent: Bool { status == "sent" }
}

struct ShareEmailResponse: Decodable, Sendable {
    let sharing: SharingView
    let results: [ShareEmailOutcome]
    /// True when this send minted the public link, so the sheet can say so.
    let publicLinkCreated: Bool

    enum CodingKeys: String, CodingKey {
        case sharing, results
        case publicLinkCreated = "public_link_created"
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

// MARK: - Ask this note (POST /v1/notes/{id}/ask)

/// One line of the conversation under a note. The client keeps the thread;
/// the server gets it back as context with every question.
struct AskTurn: Codable, Equatable, Sendable {
    enum Role: String, Codable, Sendable { case user, assistant }
    let role: Role
    let text: String
}

struct AskNoteRequest: Encodable, Sendable {
    let question: String
    let history: [AskTurn]
}

struct AskNoteResponse: Decodable, Sendable {
    let answer: String
    let backend: String
    let modelId: String

    enum CodingKeys: String, CodingKey {
        case answer, backend
        case modelId = "model_id"
    }
}

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
    /// Who can open it (0016). Nil from a server that predates the badge.
    let access: NoteAccess?

    var id: String { noteId }

    enum CodingKeys: String, CodingKey {
        case noteId = "note_id"
        case code, title, status, snippet, visibility
        case updatedAt = "updated_at"
        case sharedWithCount = "shared_with_count"
        case hasPublicLink = "has_public_link"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        noteId = try c.decode(String.self, forKey: .noteId)
        code = try c.decode(String.self, forKey: .code)
        title = try c.decode(String.self, forKey: .title)
        status = NoteStatus(rawValue: try c.decode(String.self, forKey: .status))
        snippet = (try? c.decode(String.self, forKey: .snippet)) ?? ""
        updatedAt = try c.decode(Date.self, forKey: .updatedAt)
        if let visibility = try? c.decodeIfPresent(String.self, forKey: .visibility) {
            let link = (try? c.decodeIfPresent(Bool.self, forKey: .hasPublicLink)) ?? false
            let shared = (try? c.decodeIfPresent(Int.self, forKey: .sharedWithCount)) ?? 0
            access = NoteAccess(visibility: visibility, sharedWithCount: shared, hasPublicLink: link)
        } else {
            access = nil
        }
    }
}

/// The widest audience a note reaches — what the list's badge says.
enum NoteAccess: Equatable, Sendable {
    /// Only the author team.
    case privateNote
    /// Private, plus named workspace members.
    case shared(Int)
    /// Everyone in the workspace.
    case workspace
    /// Anyone with the public link, signed in or not.
    case publicLink

    init(visibility: String, sharedWithCount: Int, hasPublicLink: Bool) {
        if hasPublicLink {
            self = .publicLink
        } else if visibility == "workspace" {
            self = .workspace
        } else if sharedWithCount > 0 {
            self = .shared(sharedWithCount)
        } else {
            self = .privateNote
        }
    }

    var isPublic: Bool { self == .publicLink }

    var label: String {
        switch self {
        case .privateNote: return "Private"
        case .shared(let n): return n == 1 ? "Shared with 1" : "Shared with \(n)"
        case .workspace: return "Workspace"
        case .publicLink: return "Public"
        }
    }

    var symbol: String {
        switch self {
        case .privateNote: return "lock"
        case .shared: return "lock"
        case .workspace: return "person.2"
        case .publicLink: return "globe"
        }
    }

    var help: String {
        switch self {
        case .privateNote: return "Private — only the note's authors can open it"
        case .shared(let n): return "Private — shared with \(n) \(n == 1 ? "person" : "people") in the workspace"
        case .workspace: return "Visible to everyone in the workspace"
        case .publicLink: return "Public — anyone with the link can open it"
        }
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

// MARK: - Spaces (note-service, 0021)

/// A folder for notes — the user's own, the same on every device. The
/// server keeps the list and which note is filed where; `noteIds` are
/// the notes this user put in it.
struct Space: Decodable, Identifiable, Equatable, Sendable {
    let id: String
    var name: String
    let createdAt: Date
    var noteIds: [String]

    enum CodingKeys: String, CodingKey {
        case id, name
        case createdAt = "created_at"
        case noteIds = "note_ids"
    }
}

struct SpacesResponse: Decodable, Sendable {
    let spaces: [Space]
}

/// The pre-0021 shape, as this device kept it in UserDefaults; read once
/// to move those spaces to the server, then forgotten.
struct LegacySpace: Codable, Sendable {
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

// MARK: - Calendar connections (note-service, 0019)

/// One calendar connected on the server — a Google account (`google`) or
/// a calendar link (`ics`, a private iCal address; 0020). Shared by every
/// client: connect once in the web app or here, the events show up in both.
struct CalendarConnection: Decodable, Identifiable, Equatable, Sendable {
    let id: String
    let provider: String
    let accountEmail: String
    let connectedAt: Date
    let hiddenCalendarIds: [String]
    let needsReauth: Bool
    let lastSyncedAt: Date?
    let lastError: String?

    enum CodingKeys: String, CodingKey {
        case id, provider
        case accountEmail = "account_email"
        case connectedAt = "connected_at"
        case hiddenCalendarIds = "hidden_calendar_ids"
        case needsReauth = "needs_reauth"
        case lastSyncedAt = "last_synced_at"
        case lastError = "last_error"
    }

    /// A calendar link rather than an OAuth account: `accountEmail` is its label.
    var isLink: Bool { provider == "ics" }
}

struct CalendarConnectionsResponse: Decodable, Sendable {
    /// False when the server has no Google client configured.
    let available: Bool
    /// True when the server takes calendar links (0020); nil on older servers.
    let linkAvailable: Bool?
    let connections: [CalendarConnection]

    enum CodingKeys: String, CodingKey {
        case available, connections
        case linkAvailable = "link_available"
    }
}

struct CalendarConnectResponse: Decodable, Sendable {
    let authorizeUrl: String

    enum CodingKeys: String, CodingKey {
        case authorizeUrl = "authorize_url"
    }
}

/// One calendar of a connected account, with whether it feeds the list.
struct RemoteCalendar: Decodable, Identifiable, Equatable, Sendable {
    let id: String
    let name: String
    let color: String?
    let primary: Bool
    let shown: Bool
}

struct RemoteCalendarsResponse: Decodable, Sendable {
    let connectionId: String
    let calendars: [RemoteCalendar]

    enum CodingKeys: String, CodingKey {
        case connectionId = "connection_id"
        case calendars
    }
}

struct UpcomingEvent: Decodable, Identifiable, Equatable, Sendable {
    let id: String
    let connectionId: String
    let accountEmail: String
    let calendarId: String
    let calendarName: String
    let color: String?
    let title: String
    let start: Date
    let end: Date
    let allDay: Bool
    let location: String?
    let meetingUrl: String?
    let htmlLink: String?
    let attendeeCount: Int
    let attendees: [String]
    let organizer: String?
    let responseStatus: String?

    enum CodingKeys: String, CodingKey {
        case id, color, title, start, end, location, attendees, organizer
        case connectionId = "connection_id"
        case accountEmail = "account_email"
        case calendarId = "calendar_id"
        case calendarName = "calendar_name"
        case allDay = "all_day"
        case meetingUrl = "meeting_url"
        case htmlLink = "html_link"
        case attendeeCount = "attendee_count"
        case responseStatus = "response_status"
    }
}

struct CalendarProblem: Decodable, Equatable, Sendable {
    let connectionId: String
    let accountEmail: String
    let code: String
    let message: String
    let needsReauth: Bool

    enum CodingKeys: String, CodingKey {
        case code, message
        case connectionId = "connection_id"
        case accountEmail = "account_email"
        case needsReauth = "needs_reauth"
    }
}

struct UpcomingEventsResponse: Decodable, Sendable {
    let available: Bool
    let connected: Bool
    let events: [UpcomingEvent]
    let problems: [CalendarProblem]
}

// MARK: - Workspace membership (auth-service /tenants)

/// The workspace the session is signed into (`GET /tenants/current`).
/// Only the fields the invite sheet needs are decoded.
struct Tenant: Decodable, Sendable {
    let id: String
    let name: String
    let displayName: String
    /// The caller's membership role: owner, admin, member, assistant, viewer.
    let myRole: String?

    enum CodingKeys: String, CodingKey {
        case id, name
        case displayName = "display_name"
        case myRole = "my_role"
    }

    var title: String { displayName.isEmpty ? name : displayName }

    /// Only owners and admins may add members; the rest can send the link.
    var canManageMembers: Bool { myRole == "owner" || myRole == "admin" }
}

/// `GET /auth/sessions` — where this account is signed in.
///
/// The IP is masked to a /24 by the server, and the device name is a
/// label ("Mac", "iPhone"), not a check: this screen exists so somebody
/// can recognise a session that is not theirs, not to identify machines.
struct AuthSessionSummary: Decodable, Sendable, Identifiable {
    let sid: String
    let clientType: String
    let deviceName: String
    let userAgent: String
    let ipLast: String
    let createdAt: Date
    let lastUsedAt: Date
    let current: Bool

    var id: String { sid }

    enum CodingKeys: String, CodingKey {
        case sid, current
        case clientType = "client_type"
        case deviceName = "device_name"
        case userAgent = "user_agent"
        case ipLast = "ip_last"
        case createdAt = "created_at"
        case lastUsedAt = "last_used_at"
    }

    var title: String {
        let device = deviceName.isEmpty ? clientType.capitalized : deviceName
        return current ? "\(device) · this Mac" : device
    }
}

/// `POST /auth/sessions/revoke-others`
struct RevokedOthersResponse: Decodable, Sendable {
    let revoked: Int
}

/// `GET /tenants` — every workspace this identity can reach, with the
/// caller's role in each. The switcher's list.
struct TenantListResponse: Decodable, Sendable {
    let items: [Tenant]
}

/// `POST /auth/token` — an access token scoped to one workspace.
///
/// No refresh token: switching rotates nothing, so the session's one
/// credential is still the one already in the Keychain.
struct WorkspaceToken: Decodable, Sendable {
    let accessToken: String
    let expiresIn: Int
    let tenantId: String
    let roles: [String]

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case expiresIn = "expires_in"
        case tenantId = "tenant_id"
        case roles
    }
}

/// Why a workspace stopped being reachable. Each is a different sentence,
/// and only one of them means "ask someone to let you back in".
enum WorkspaceLoss: Equatable, Sendable {
    case notAMember
    case suspended
    case dissolved

    init?(code: String?) {
        switch code {
        case "not_a_member": self = .notAMember
        case "membership_suspended": self = .suspended
        case "tenant_dissolved": self = .dissolved
        default: return nil
        }
    }

    func message(workspace: String) -> String {
        switch self {
        case .notAMember:
            return "You are no longer a member of \(workspace)."
        case .suspended:
            return "Your membership of \(workspace) is suspended."
        case .dissolved:
            return "\(workspace) has been closed."
        }
    }
}

struct TenantMember: Decodable, Sendable, Identifiable {
    let userSub: String
    let role: String
    let status: String
    let email: String?
    let displayName: String?

    var id: String { userSub }
    var title: String {
        let name = displayName?.trimmingCharacters(in: .whitespaces) ?? ""
        if !name.isEmpty { return name }
        return email ?? "Member"
    }

    enum CodingKeys: String, CodingKey {
        case role, status, email
        case userSub = "user_sub"
        case displayName = "display_name"
    }
}

struct TenantMembersResponse: Decodable, Sendable {
    let items: [TenantMember]
}
