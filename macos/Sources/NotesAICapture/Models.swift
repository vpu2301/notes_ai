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

    /// Sprint 21: when the account came to exist; absent on an older server.
    let createdAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, email, status
        case displayName = "display_name"
        case mfaEnabled = "mfa_enabled"
        case hasPassword = "has_password"
        case createdAt = "created_at"
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
    /// Sprint 29 — speaker re-labelling. All optional: an older server
    /// sends none of them and the job still decodes.
    /// Bumped by every re-label and undo.
    var diarizationRev: Int? = nil
    /// nil (never re-labelled) | "queued" | "running" | "complete" | "failed".
    /// The job's `status` stays `complete` meanwhile: the transcript is
    /// readable the whole time.
    var diarizationStatus: String? = nil
    var diarizationError: String? = nil
    var diarizationRuns: Int? = nil
    var canUndoRediarize: Bool? = nil
    /// Submit response only: true = the speaker-count hint was used, false =
    /// sent but ignored (diarize off), nil = none sent.
    var hintsApplied: Bool? = nil

    enum CodingKeys: String, CodingKey {
        case id, status
        case detectedLanguage = "detected_language"
        case errorMessage = "error_message"
        case errorKind = "error_kind"
        case diarizationRev = "diarization_rev"
        case diarizationStatus = "diarization_status"
        case diarizationError = "diarization_error"
        case diarizationRuns = "diarization_runs"
        case canUndoRediarize = "can_undo_rediarize"
        case hintsApplied = "hints_applied"
    }

    /// A speaker re-label is queued or running.
    var isRelabelling: Bool { diarizationStatus == "queued" || diarizationStatus == "running" }

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
    /// `finalized` / `amended` are legacy values a note no longer takes
    /// (finalize retired, ADR-0051); kept so old rows decode.
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
    /// The transcription job the note was made from, if any.
    let sourceJobId: String?

    enum CodingKeys: String, CodingKey {
        case id, code, status, title, content, visibility
        case sourceJobId = "source_job_id"
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
    /// Every live link, newest first (Sprint 19). Absent on an older server.
    let links: [LinkView]
    /// Sprint 23: the workspace's effective sharing rules. Absent on an older server.
    let constraints: SharingConstraints?

    enum CodingKeys: String, CodingKey {
        case visibility, links, constraints
        case noteId = "note_id"
        case canManage = "can_manage"
        case canDelete = "can_delete"
        case sharedWith = "shared_with"
        case publicLink = "public_link"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        noteId = try c.decode(String.self, forKey: .noteId)
        visibility = try c.decode(String.self, forKey: .visibility)
        canManage = try c.decode(Bool.self, forKey: .canManage)
        canDelete = try c.decode(Bool.self, forKey: .canDelete)
        sharedWith = try c.decode([SharedMember].self, forKey: .sharedWith)
        publicLink = try c.decodeIfPresent(PublicLink.self, forKey: .publicLink)
        links = try c.decodeIfPresent([LinkView].self, forKey: .links) ?? []
        constraints = try? c.decodeIfPresent(SharingConstraints.self, forKey: .constraints)
    }

    /// The client-facing links only.
    var recipientLinks: [LinkView] { links.filter { $0.kind == .recipient } }
}

// MARK: - Per-recipient links (Sprint 19, 0035)

enum ShareLinkKind: String, Decodable, Sendable {
    case `public`, recipient
}

/// One share link: the public one or a per-recipient one. Decoded from
/// `LinkView`; the token is only ever returned to people who may manage
/// the note.
struct LinkView: Decodable, Sendable, Identifiable {
    let id: String
    let kind: ShareLinkKind
    let label: String
    let recipientEmail: String?
    let token: String
    /// SPA path; prefix with the web app origin for a full URL.
    let path: String
    let refCode: String?
    let createdAt: Date
    let expiresAt: Date?
    let viewCount: Int
    let firstViewedAt: Date?
    let lastViewedAt: Date?
    let ctaClickedAt: Date?
    /// Sprint 20: live responses from this link. Absent on an older server.
    let responseCount: Int?
    /// Sprint 22: the product mailed the link. Raw so an unknown value
    /// from a newer server decodes rather than failing the whole sheet.
    let deliveryStatusRaw: String?
    let sentAt: Date?
    let sendCount: Int?
    let lastSendError: String?

    enum CodingKeys: String, CodingKey {
        case id, kind, label, token, path
        case recipientEmail = "recipient_email"
        case refCode = "ref_code"
        case createdAt = "created_at"
        case expiresAt = "expires_at"
        case viewCount = "view_count"
        case firstViewedAt = "first_viewed_at"
        case lastViewedAt = "last_viewed_at"
        case ctaClickedAt = "cta_clicked_at"
        case responseCount = "response_count"
        case deliveryStatusRaw = "delivery_status"
        case sentAt = "sent_at"
        case sendCount = "send_count"
        case lastSendError = "last_send_error"
    }

    enum DeliveryStatus: String { case notSent = "not_sent", sent, failed, suppressed }

    var deliveryStatus: DeliveryStatus { DeliveryStatus(rawValue: deliveryStatusRaw ?? "") ?? .notSent }

    /// "Sent 12:31 · Opened 17 Sep · Responded (2)"
    var statusLine: String {
        var parts: [String] = []
        switch deliveryStatus {
        case .sent:
            if let sentAt { parts.append("Sent " + sentAt.formatted(date: .omitted, time: .shortened)) } else { parts.append("Sent") }
        case .failed: parts.append("Failed")
        case .suppressed: parts.append("Opted out")
        case .notSent: parts.append("Not sent")
        }
        parts.append(opened)
        if let n = responseCount, n > 0 { parts.append("Responded (\(n))") }
        return parts.joined(separator: " · ")
    }

    /// The product may mail it (again): an address, not opted out, under the cap.
    var canSend: Bool {
        recipientEmail != nil && deliveryStatus != .suppressed && (sendCount ?? 0) < 3
    }

    var opened: String {
        guard let firstViewedAt else { return "Not opened" }
        return "Opened " + firstViewedAt.formatted(date: .abbreviated, time: .omitted)
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
    /// Sprint 30: where this segment sits in the stored artifact — the
    /// space `TranscriptTurn.segmentIndices` is in. Nil from older servers.
    var artifactIndex: Int? = nil

    enum CodingKeys: String, CodingKey {
        case text, speaker
        case startMs = "start_ms"
        case endMs = "end_ms"
        case artifactIndex = "artifact_index"
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
    /// Sprint 30: the turn's segments in ARTIFACT index space. Opaque —
    /// sent back as-is to move the turn, never used to index `segments`.
    /// Nil from servers that cannot move turns.
    var segmentIndices: [Int]? = nil
    /// Sprint 30: people talked over each other here, or the label was
    /// smoothed — the attribution is a guess.
    var uncertain: Bool? = nil

    /// Turns are chronological and non-overlapping, so the start is unique.
    var id: Int { startMs }

    /// Whether this turn can be moved to another speaker.
    var isMovable: Bool { !(segmentIndices ?? []).isEmpty }
    var isUncertain: Bool { uncertain == true }

    enum CodingKeys: String, CodingKey {
        case speaker, name, paragraphs, uncertain
        case startMs = "start_ms"
        case endMs = "end_ms"
        case segmentIndices = "segment_indices"
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
    /// Talk time per roster label, after speaker edits.
    let speakerStats: [SpeakerStat]?
    /// Diarization run the edits apply to.
    let resultRev: Int?
    /// Live speaker edits, application order (latest last).
    let edits: [SpeakerEdit]?
    /// "high" | "low" | nil (not diarized, or a pre-Sprint-29 result).
    var countConfidence: String? = nil
    /// The exact speaker count a person asked for on this labelling.
    var speakersHint: Int? = nil
    /// Sprint 30: names offered when renaming a speaker (calendar invitees).
    var nameCandidates: [String]? = nil
    /// Sprint 31: label → "local" (heard on the recording Mac's microphone)
    /// or "remote" (came through the call audio). Empty for mono jobs;
    /// absent from older servers.
    var speakerSides: [String: String]? = nil
    /// Sprint 31: label → how the name was given ("typed", "picklist",
    /// "channel", "suggestion", "cleared"). "channel" = the server named
    /// the only speaker on the microphone after the account owner.
    var speakerNameSources: [String: String]? = nil
    /// Sprint 32: names the server heard people give themselves ("Hi, this
    /// is Anna"), offered with their evidence. Only sent while the server's
    /// suggestion switch is on — absent is the normal case.
    var nameSuggestions: [NameSuggestion]? = nil
    /// Sprint 32: labelled by an older engine and the audio is still there,
    /// so a re-label is worth offering. Absent from older servers.
    var relabelAvailable: Bool? = nil

    enum CodingKeys: String, CodingKey {
        case jobId = "job_id"
        case nameSuggestions = "name_suggestions"
        case relabelAvailable = "relabel_available"
        case segments, speakers, turns, edits
        case speakerSides = "speaker_sides"
        case speakerNameSources = "speaker_name_sources"
        case speakerNames = "speaker_names"
        case speakerStats = "speaker_stats"
        case resultRev = "result_rev"
        case countConfidence = "count_confidence"
        case speakersHint = "speakers_hint"
        case nameCandidates = "name_candidates"
    }
}

struct SpeakerStat: Decodable, Sendable, Equatable {
    let label: String
    let speechMs: Int
    let share: Double
    let turns: Int

    enum CodingKeys: String, CodingKey {
        case label, share, turns
        case speechMs = "speech_ms"
    }

    /// Probably someone else split off (or a cough): worth one question.
    var isSmall: Bool { share < 0.05 || speechMs < 15_000 }
}

struct SpeakerEdit: Decodable, Sendable, Equatable {
    let id: String
    let kind: String
    let fromLabel: String?
    let toLabel: String?

    enum CodingKeys: String, CodingKey {
        case id, kind
        case fromLabel = "from_label"
        case toLabel = "to_label"
    }
}

/// Sprint 32 — one name suggestion: the name (calendar spelling) the
/// server heard for `label`, and the words it heard it in, shown before
/// anything is accepted. Everything but the pair is optional so a server
/// that trims a field never costs the whole transcript.
struct NameSuggestion: Decodable, Equatable, Hashable, Identifiable, Sendable {
    let label: String
    let name: String
    var source: String? = nil
    /// The evidence, at most 160 characters.
    var quote: String? = nil
    var startMs: Int? = nil
    var endMs: Int? = nil
    /// Artifact index space, like `TranscriptTurn.segmentIndices`.
    var segmentIndices: [Int]? = nil

    /// A pair is dismissed once and never comes back, so it is the identity.
    var id: String { "\(label)|\(name)" }

    enum CodingKeys: String, CodingKey {
        case label, name, source, quote
        case startMs = "start_ms"
        case endMs = "end_ms"
        case segmentIndices = "segment_indices"
    }
}

/// `POST /asr/jobs/{id}/speakers/suggestions/dismiss` body.
struct NameSuggestionDismissRequest: Encodable, Sendable {
    let label: String
    let name: String
}

struct SpeakerMergeRequest: Encodable, Sendable {
    let from: String
    let into: String
}

/// `POST /asr/jobs/{id}/speakers/merge` response.
struct SpeakerEditResult: Decodable, Sendable {
    let editId: String
    let speakers: [String]
    let speakerNames: [String: String]
    let speakerStats: [SpeakerStat]

    enum CodingKeys: String, CodingKey {
        case speakers
        case editId = "edit_id"
        case speakerNames = "speaker_names"
        case speakerStats = "speaker_stats"
    }
}

/// Why a speaker merge or undo was refused, in words a person can act on.
enum SpeakerEditError: LocalizedError {
    case notComplete, unknownLabel, notLatest
    /// Sprint 30: the result changed since it was read (another device,
    /// the web app). The caller reloads and says so.
    case staleResultRev
    case badSegmentIndex, tooManySegments, tooManySpeakers
    case relabelInProgress
    /// 410: the transcript was erased.
    case erased

    var errorDescription: String? {
        switch self {
        case .notComplete: return "The transcript is not finished yet."
        case .unknownLabel: return "That speaker is no longer in the transcript. Reload and try again."
        case .notLatest: return "Only the last speaker change can be undone."
        case .staleResultRev: return "Speakers were updated elsewhere."
        case .badSegmentIndex: return "Those turns have changed. Reload and try again."
        case .tooManySegments: return "Too many turns at once. Move fewer turns at a time."
        case .tooManySpeakers: return "A transcript can have at most 8 speakers."
        case .relabelInProgress: return "Speakers are being re-labelled. Try again when it has finished."
        case .erased: return "This transcript was erased."
        }
    }

    static func from(_ error: Error) -> Error {
        guard case APIError.http(let status, let problem) = error else { return error }
        switch problem?.code {
        case "job_not_complete": return SpeakerEditError.notComplete
        case "unknown_label", "same_label": return SpeakerEditError.unknownLabel
        case "edit_not_latest": return SpeakerEditError.notLatest
        case "stale_result_rev": return SpeakerEditError.staleResultRev
        case "bad_segment_index": return SpeakerEditError.badSegmentIndex
        case "too_many_segments": return SpeakerEditError.tooManySegments
        case "too_many_speakers": return SpeakerEditError.tooManySpeakers
        case "rediarize_in_progress": return SpeakerEditError.relabelInProgress
        default: return status == 410 ? SpeakerEditError.erased : error
        }
    }
}

/// Where a moved turn goes: an existing speaker, a speaker the diarizer
/// missed ("new"), or nobody ("Unknown", sent as JSON null).
enum ReassignTarget: Equatable, Hashable, Sendable {
    case speaker(String)
    case new
    case unknown
}

/// `POST /asr/jobs/{id}/speakers/reassign` body. `to` is always present:
/// null is a meaning ("Unknown"), not an omission.
struct SpeakerReassignRequest: Encodable, Sendable {
    let resultRev: Int
    let segmentIndices: [Int]
    let to: ReassignTarget

    enum CodingKeys: String, CodingKey {
        case to
        case resultRev = "result_rev"
        case segmentIndices = "segment_indices"
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(resultRev, forKey: .resultRev)
        try container.encode(segmentIndices, forKey: .segmentIndices)
        switch to {
        case .speaker(let label): try container.encode(label, forKey: .to)
        case .new: try container.encode("new", forKey: .to)
        case .unknown: try container.encodeNil(forKey: .to)
        }
    }
}

/// The 200 of a reassign: the roster after the move, and the label made
/// for "New speaker" (nil otherwise).
struct SpeakerReassignResult: Decodable, Sendable {
    let editId: String
    let speakers: [String]
    let speakerNames: [String: String]
    let speakerStats: [SpeakerStat]
    var createdLabel: String? = nil

    enum CodingKeys: String, CodingKey {
        case speakers
        case editId = "edit_id"
        case speakerNames = "speaker_names"
        case speakerStats = "speaker_stats"
        case createdLabel = "created_label"
    }
}

/// Sprint 30 — how a speaker's new name was chosen (a metric only; the
/// server does not store it).
enum SpeakerNameSource: String, Encodable, Sendable {
    case picklist, typed
    /// Sprint 32: an accepted name suggestion.
    case suggestion
}

/// Sprint 31: which side of a call a speaker was heard on.
enum SpeakerSide: String, Sendable {
    case local, remote

    var symbol: String { self == .local ? "mic.fill" : "headphones" }
    var accessibilityLabel: String { self == .local ? "On your microphone" : "On the call audio" }
}

/// Sprint 31 roster markers: the side glyph, and the "from your
/// microphone" marker on a name the server gave from the channel split.
enum SpeakerChannelMarkers {
    static let channelSource = "channel"
    static let fromMicrophone = "· from your microphone"
    static let removeLabel = "Remove this name"
    /// Sprint 32: the marker on a name that came from an accepted
    /// suggestion, until the person edits it.
    static let suggestionSource = "suggestion"
    static let suggested = "suggested"

    /// The side glyph for `label`; nil for mono jobs, unknown labels, or a
    /// value this build does not know.
    static func side(of label: String, in sides: [String: String]) -> SpeakerSide? {
        sides[label].flatMap(SpeakerSide.init(rawValue:))
    }

    /// Whether `label`'s name came from the channel split (and so gets the
    /// marker and the ✕ that clears it).
    static func isChannelNamed(_ label: String, sources: [String: String]) -> Bool {
        sources[label] == channelSource
    }

    /// Whether `label`'s name is an accepted suggestion (the "suggested" marker).
    static func isSuggested(_ label: String, sources: [String: String]) -> Bool {
        sources[label] == suggestionSource
    }

    /// `speaker_name_sources` after a successful rename of `label`: the
    /// source sent, or "cleared" when the name was removed — so the marker
    /// never outlives the name it described.
    static func sources(_ sources: [String: String], afterRenaming label: String,
                        sent: SpeakerNameSource?) -> [String: String] {
        var updated = sources
        updated[label] = sent?.rawValue ?? "cleared"
        return updated
    }
}

/// `POST /asr/jobs/{id}/rediarize` body. `speakers_expected` is always
/// sent — `null` means "let the diarizer decide".
struct RediarizeRequest: Encodable, Sendable {
    let speakersExpected: Int?

    enum CodingKeys: String, CodingKey {
        case speakersExpected = "speakers_expected"
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(speakersExpected, forKey: .speakersExpected)
    }
}

/// The 202 of a re-label and the 200 of its undo.
struct RediarizeResponse: Decodable, Sendable {
    let jobId: String
    let diarizationStatus: String?
    let diarizationRev: Int?

    enum CodingKeys: String, CodingKey {
        case jobId = "job_id"
        case diarizationStatus = "diarization_status"
        case diarizationRev = "diarization_rev"
    }
}

/// Why a speaker re-label or its undo was refused.
enum RediarizeError: LocalizedError, Equatable {
    case notComplete, inProgress, audioUnavailable, limitReached, rateLimited, enqueueFailed, nothingToUndo

    var errorDescription: String? {
        switch self {
        case .notComplete: return "The transcript is not finished yet."
        case .inProgress: return "Speakers are already being re-labelled."
        case .audioUnavailable: return "The recording is no longer stored, so speakers can't be re-labelled."
        case .limitReached: return "Speakers can be re-labelled 5 times per recording, and that's been used up."
        case .rateLimited: return "Too many re-labels in the last hour. Try again later."
        case .enqueueFailed: return "Couldn't start re-labelling. Nothing changed — try again."
        case .nothingToUndo: return "There is nothing to undo."
        }
    }

    static func from(_ error: Error) -> Error {
        guard case APIError.http(_, let problem) = error else { return error }
        switch problem?.code {
        case "job_not_complete": return RediarizeError.notComplete
        case "rediarize_in_progress": return RediarizeError.inProgress
        case "audio_unavailable": return RediarizeError.audioUnavailable
        case "rediarize_limit": return RediarizeError.limitReached
        case "rate_limited": return RediarizeError.rateLimited
        case "enqueue_failed": return RediarizeError.enqueueFailed
        case "nothing_to_undo": return RediarizeError.nothingToUndo
        default: return error
        }
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
    /// Label → how its name was chosen; omitted when nil.
    var sources: [String: SpeakerNameSource]? = nil
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
    /// Mutable so a change made from the list shows without a reload.
    var access: NoteAccess?
    /// Sprint 20 — live recipient disputes, for the "1 disputed" marker.
    var openDisputes: Int = 0

    var id: String { noteId }

    enum CodingKeys: String, CodingKey {
        case noteId = "note_id"
        case code, title, status, snippet, visibility
        case updatedAt = "updated_at"
        case sharedWithCount = "shared_with_count"
        case hasPublicLink = "has_public_link"
        case openDisputes = "open_disputes"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        noteId = try c.decode(String.self, forKey: .noteId)
        code = try c.decode(String.self, forKey: .code)
        title = try c.decode(String.self, forKey: .title)
        status = NoteStatus(rawValue: try c.decode(String.self, forKey: .status))
        snippet = (try? c.decode(String.self, forKey: .snippet)) ?? ""
        updatedAt = try c.decode(Date.self, forKey: .updatedAt)
        openDisputes = (try? c.decodeIfPresent(Int.self, forKey: .openDisputes)) ?? 0
        if let visibility = try? c.decodeIfPresent(String.self, forKey: .visibility) {
            let link = (try? c.decodeIfPresent(Bool.self, forKey: .hasPublicLink)) ?? false
            let shared = (try? c.decodeIfPresent(Int.self, forKey: .sharedWithCount)) ?? 0
            access = NoteAccess(visibility: visibility, sharedWithCount: shared, hasPublicLink: link)
        } else {
            access = nil
        }
    }
}

/// Who can open a note — what the list's pill says, and what its menu
/// changes.
struct NoteAccess: Equatable, Sendable {
    /// "private" or "workspace".
    var visibility: String
    var sharedWithCount: Int
    var hasPublicLink: Bool

    init(visibility: String, sharedWithCount: Int, hasPublicLink: Bool) {
        self.visibility = visibility
        self.sharedWithCount = sharedWithCount
        self.hasPublicLink = hasPublicLink
    }

    init(_ sharing: SharingView) {
        self.init(visibility: sharing.visibility, sharedWithCount: sharing.sharedWith.count,
                  hasPublicLink: sharing.publicLink != nil)
    }

    var isWorkspace: Bool { visibility == "workspace" }

    /// A live public link: the pill is tinted and carries a globe, but the
    /// word stays the workspace visibility — the two are separate facts,
    /// and "Public" next to a checked "Private" read as a contradiction.
    var isPublic: Bool { hasPublicLink }

    var label: String {
        if isWorkspace { return "Workspace" }
        if sharedWithCount > 0 { return "Shared with \(sharedWithCount)" }
        return "Private"
    }

    var symbol: String {
        if isWorkspace { return "person.2.fill" }
        return "lock.fill"
    }

    var help: String {
        let base: String
        if isWorkspace {
            base = "Visible to everyone in the workspace"
        } else if sharedWithCount > 0 {
            base = "Private — shared with \(sharedWithCount) \(sharedWithCount == 1 ? "person" : "people") in the workspace"
        } else {
            base = "Private — only the note's authors can open it"
        }
        return hasPublicLink ? base + ". A public link is on: anyone with it can open the note" : base
    }

    /// The menu's line about the link, under its own header.
    var publicLinkHint: String {
        hasPublicLink ? "On — anyone with the link can open the note" : "Off"
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

// MARK: - Action items + recipient responses (Sprint 20, 0037)

enum ActionItemStatus: String, Codable, Sendable {
    case open, done, dropped
}

enum ResponseKind: String, Decodable, Sendable {
    case confirm, done, dispute, flag
}

/// What a recipient did on the shared page. `comment` is theirs and is
/// only ever shown as text.
struct ItemResponse: Decodable, Sendable, Identifiable {
    let id: String
    let linkId: String
    let linkLabel: String
    let kind: ResponseKind
    let itemKey: String?
    let sectionKey: String?
    let comment: String?
    let createdAt: Date
    let clearedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, kind, comment
        case linkId = "link_id"
        case linkLabel = "link_label"
        case itemKey = "item_key"
        case sectionKey = "section_key"
        case createdAt = "created_at"
        case clearedAt = "cleared_at"
    }
}

struct ItemCounts: Decodable, Sendable {
    let confirms: Int
    let dones: Int
    let disputes: Int
}

/// One action item of the note's current version, with the responses on it.
struct ActionItem: Decodable, Sendable, Identifiable {
    let id: String
    let itemKey: String
    let position: Int
    let text: String
    let ownerLabel: String?
    let ownerConfidence: Double?
    let dueDate: String?
    let dueText: String?
    var status: ActionItemStatus
    var counts: ItemCounts
    var responses: [ItemResponse]

    enum CodingKeys: String, CodingKey {
        case id, position, text, status, counts, responses
        case itemKey = "item_key"
        case ownerLabel = "owner_label"
        case ownerConfidence = "owner_confidence"
        case dueDate = "due_date"
        case dueText = "due_text"
    }

    /// "Owner inferred — check it" when the parser only guessed.
    var ownerNeedsCheck: Bool { ownerLabel != nil && (ownerConfidence ?? 1) < 1 }

    var summary: String {
        var parts: [String] = []
        if counts.confirms > 0 { parts.append("\(counts.confirms) confirmed") }
        if counts.dones > 0 { parts.append("\(counts.dones) done") }
        if counts.disputes > 0 { parts.append("\(counts.disputes) disputed") }
        return parts.isEmpty ? "No responses yet" : parts.joined(separator: " · ")
    }
}

// MARK: - Sharing constraints (Sprint 23)

/// What the workspace admin allows. Read from `GET /v1/notes/sharing/constraints`
/// and carried on every `SharingView`; the clients hide what the server
/// would refuse.
struct SharingConstraints: Decodable, Sendable, Equatable {
    let externalLinksEnabled: Bool
    let publicLinksEnabled: Bool
    let maxLinkDays: Int
    let productEmailEnabled: Bool
    let verifiedRecipientsRequired: Bool

    enum CodingKeys: String, CodingKey {
        case externalLinksEnabled = "external_links_enabled"
        case publicLinksEnabled = "public_links_enabled"
        case maxLinkDays = "max_link_days"
        case productEmailEnabled = "product_email_enabled"
        case verifiedRecipientsRequired = "verified_recipients_required"
    }

    static let permissive = SharingConstraints(
        externalLinksEnabled: true, publicLinksEnabled: true,
        maxLinkDays: 180, productEmailEnabled: true, verifiedRecipientsRequired: false)
}


// MARK: - Transcript-shaped text

/// "Anna: we ship Friday" — a paragraph that opens with a short speaker
/// label. The same rule note-service and the web use, so a section reads
/// as the transcript on every surface or on none.
enum TranscriptText {
    struct Turn: Identifiable, Equatable {
        let id: Int
        let speaker: String?
        let text: String
    }

    private static let lead = try! NSRegularExpression(  // swiftlint:disable:this force_try
        pattern: "^(?!https?:)([^\\s*_`:][^*_`:]{0,39}?):\\s+(?=\\S)")

    static func paragraphs(_ text: String) -> [String] {
        text.replacingOccurrences(of: "\r\n", with: "\n")
            .components(separatedBy: "\n")
            .split(whereSeparator: { $0.trimmingCharacters(in: .whitespaces).isEmpty })
            .map { $0.map { $0.trimmingCharacters(in: .whitespaces) }.joined(separator: " ") }
            .filter { !$0.isEmpty }
    }

    /// (speaker, rest) when the paragraph is a turn.
    static func split(_ paragraph: String) -> (String, String)? {
        let range = NSRange(paragraph.startIndex..., in: paragraph)
        guard let m = lead.firstMatch(in: paragraph, range: range),
              let nameRange = Range(m.range(at: 1), in: paragraph),
              let whole = Range(m.range, in: paragraph) else { return nil }
        let name = String(paragraph[nameRange])
        guard name.split(whereSeparator: \.isWhitespace).count <= 4 else { return nil }
        return (name, String(paragraph[whole.upperBound...]))
    }

    /// Mostly turns (≥ 60 % of at least two paragraphs) → the transcript.
    static func isTranscript(_ text: String) -> Bool {
        let paras = paragraphs(text)
        guard paras.count >= 2 else { return false }
        let turns = paras.filter { split($0) != nil }.count
        return turns * 10 >= paras.count * 6
    }

    static func turns(_ text: String) -> [Turn] {
        paragraphs(text).enumerated().map { i, p in
            if let (name, rest) = split(p) { return Turn(id: i, speaker: name, text: rest) }
            return Turn(id: i, speaker: nil, text: p)
        }
    }
}

/// What one upload may be (`GET /asr/limits`), read before a recording
/// starts so the app can warn before the cap rather than fail after it.
struct AsrLimits: Decodable, Sendable {
    let maxDurationSeconds: Int
    let maxUploadMb: Int

    enum CodingKeys: String, CodingKey {
        case maxDurationSeconds = "max_duration_seconds"
        case maxUploadMb = "max_upload_mb"
    }
}
