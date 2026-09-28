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

    /// The dev stack on one machine: every service on its usual port of
    /// `host` (a name or address, optionally with a scheme). Returns nil
    /// for an empty or unusable host — see `hostProblem` for the reason.
    static func forHost(_ raw: String) -> BackendSettings? {
        guard hostProblem(raw) == nil, let (scheme, host) = parseHost(raw) else { return nil }
        return BackendSettings(
            authBaseURL: "\(scheme)://\(host):8000",
            asrBaseURL: "\(scheme)://\(host):8001",
            noteBaseURL: "\(scheme)://\(host):8006",
            webAppURL: "\(scheme)://\(host):5173"
        )
    }

    /// Why `raw` is not a usable host, in the user's terms; nil when it is.
    static func hostProblem(_ raw: String) -> String? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return nil }
        // Six hex pairs: the Wi‑Fi hardware (MAC) address, which sits right
        // next to the IP address in the phone's and the Mac's Wi‑Fi details.
        let hexPairs = trimmed.split(whereSeparator: { $0 == ":" || $0 == "-" })
        if hexPairs.count == 6, hexPairs.allSatisfy({ $0.count == 2 && $0.allSatisfy(\.isHexDigit) }) {
            return "That is the Wi‑Fi hardware (MAC) address. Enter the IP address instead — it looks like 192.168.x.x and is listed as “IP address” in the Mac's Wi‑Fi details."
        }
        guard let (scheme, host) = parseHost(trimmed) else {
            return "Enter the Mac's address, like 192.168.1.20 or my-mac.local."
        }
        _ = scheme
        if host.hasPrefix("[") { return nil }  // IPv6 literal; the URL check below covers it
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: ".-"))
        guard host.unicodeScalars.allSatisfy(allowed.contains), !host.hasPrefix("."), !host.hasSuffix("."),
              URL(string: "http://\(host):8000/") != nil
        else { return "Enter the Mac's address, like 192.168.1.20 or my-mac.local." }
        return nil
    }

    /// (scheme, host) out of "host", "host:port", "scheme://host[:port]/…".
    private static func parseHost(_ raw: String) -> (String, String)? {
        var host = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        var scheme = "http"
        if let range = host.range(of: "://") {
            scheme = String(host[..<range.lowerBound]).lowercased()
            host = String(host[range.upperBound...])
        }
        if let slash = host.firstIndex(of: "/") { host = String(host[..<slash]) }
        if host.hasPrefix("[") {
            // [v6]:port
            if let close = host.firstIndex(of: "]") { host = String(host[...close]) }
        } else if host.filter({ $0 == ":" }).count == 1, let colon = host.lastIndex(of: ":") {
            host = String(host[..<colon])
        }
        guard !host.isEmpty, !host.contains(" "), ["http", "https"].contains(scheme) else { return nil }
        return (scheme, host)
    }

    /// The host every address points at, when they agree; nil otherwise.
    var commonHost: String? {
        let hosts = [authBaseURL, asrBaseURL, noteBaseURL, webAppURL]
            .map { URL(string: $0.trimmingCharacters(in: .whitespaces))?.host() }
        guard let first = hosts.first ?? nil, hosts.allSatisfy({ $0 == first }) else { return nil }
        return first
    }

    /// True when the addresses point at this device itself — right on the
    /// simulator, useless on a phone.
    var pointsAtLocalhost: Bool {
        let host = (URL(string: authBaseURL.trimmingCharacters(in: .whitespaces))?.host() ?? "").lowercased()
        return host == "localhost" || host == "127.0.0.1" || host == "::1"
    }
}

/// True on a real phone (not the simulator).
let isPhysicalDevice: Bool = {
    #if targetEnvironment(simulator)
    return false
    #else
    return true
    #endif
}()

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
/// switcher is IDX-I2's, and `POST /auth/token` does not exist yet.
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
/// The server discriminates on `status`, and an `mfa_required` result is a
/// real 200 whose token fields are empty on purpose (IDX-A5: nothing about
/// the account is disclosed on the near side of the second factor).
enum AuthResult: Sendable {
    case authenticated(AuthSession)
    case mfaRequired(challengeId: String, methods: [String], expiresIn: Int)
}

/// The wire shape of `AuthResult`, and the Keycloak-era login response
/// before it — `/auth/login` answers the three token fields and nothing
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

/// One workspace this identity belongs to (`GET /tenants`).
///
/// The switcher's row. `myRole` is the membership role, re-read by the
/// server on every listing — a role is worth what it is worth now, not
/// what it was worth when the session opened.
struct Workspace: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let name: String
    var displayName: String = ""
    var slug: String?
    var status: String = "active"
    var isActive: Bool = true
    var myRole: String = "member"

    enum CodingKeys: String, CodingKey {
        case id, name, slug, status
        case displayName = "display_name"
        case isActive = "is_active"
        case myRole = "my_role"
    }

    var title: String { displayName.isEmpty ? name : displayName }

    /// What the row says under the name.
    var roleLabel: String {
        switch myRole {
        case "owner": return "Owner"
        case "admin": return "Admin"
        case "assistant": return "Assistant"
        case "viewer": return "Viewer"
        default: return "Member"
        }
    }
}

struct WorkspaceList: Decodable, Sendable {
    let items: [Workspace]
}

/// `POST /auth/token` — an access token for another of my workspaces.
///
/// No refresh token and no rotation: the session's one credential is the
/// one the app already holds. With `activate` the session moves too, so
/// the next launch comes back to the same workspace.
struct SwitchedToken: Decodable, Sendable {
    let accessToken: String
    let expiresIn: Int
    let tenantId: String
    var roles: [String] = []

    enum CodingKeys: String, CodingKey {
        case roles
        case accessToken = "access_token"
        case expiresIn = "expires_in"
        case tenantId = "tenant_id"
    }
}

/// One place this account is signed in (`GET /auth/sessions`).
struct DeviceSession: Decodable, Equatable, Identifiable, Sendable {
    let sid: String
    var clientType: String = ""
    var deviceName: String = ""
    var userAgent: String = ""
    var ipLast: String = ""
    let createdAt: Date
    let lastUsedAt: Date
    var current: Bool = false

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

    /// "This iPhone", "A Mac", "A browser" — what the person will
    /// recognise. The server's `device_name` wins when it has one.
    var title: String {
        if !deviceName.isEmpty { return deviceName }
        switch clientType {
        case "ios": return "iPhone"
        case "macos": return "Mac"
        case "web", "": return "Browser"
        default: return clientType.capitalized
        }
    }

    var symbol: String {
        switch clientType {
        case "ios": return "iphone"
        case "macos": return "laptopcomputer"
        default: return "globe"
        }
    }
}

struct RevokedOthers: Decodable, Sendable {
    let revoked: Int
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
    /// The language the server should write its mail in, when this phone's
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
    /// The gate key is gone: Face ID or Touch ID was re-enrolled, or the
    /// passcode was removed. Nothing on this phone can read the session
    /// again, and that is the point of `.biometryCurrentSet`.
    case biometryChanged
    /// The identity is disabled, or has no workspace left.
    case accountUnavailable(String)

    var message: String {
        switch self {
        case .expired:
            return "Your session ended. Sign in again."
        case .securityRevoked:
            return "You were signed out for security. Sign in again."
        case .biometryChanged:
            return "\(Biometrics.name ?? "The passcode") changed on this phone, so the saved sign-in was cleared. Sign in again."
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
    /// The refresh token is on this phone but behind the biometric gate,
    /// and the gate has not been opened in this launch.
    case sessionLocked
    /// A step-up endpoint wants proof of identity inside the reauth
    /// window. `AppState` presents the sheet; the caller retries once.
    case reauthRequired
    /// The server answered 200 with something this app cannot read.
    case malformedResponse
    /// The sign-in worked, but the server kept the refresh token itself
    /// (it answered as if to a browser). There is nothing for this phone
    /// to store, and a session that cannot be renewed is not one to claim.
    case noNativeSession

    var errorDescription: String? {
        switch self {
        case .badURL:
            return "Invalid backend URL — check Settings."
        case .notAuthenticated:
            return "Signed out — please sign in again."
        case .sessionRevoked:
            return SessionLostReason.securityRevoked.message
        case .sessionLocked:
            return "Unlock Notes AI to continue."
        case .reauthRequired:
            return "Confirm it is really you to continue."
        case .malformedResponse:
            return "Could not read the server's response."
        case .noNativeSession:
            return "This server cannot keep this phone signed in. Ask for the new sign-in to be enabled, or use the web app."
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

    /// `403 email_not_verified` — the account exists but the address has
    /// not been confirmed yet (BE-0 signs people up through the web app
    /// and mails them a link). Not a wrong password and not a disabled
    /// account: the way forward is the mail, so the sign-in screen offers
    /// to send it again rather than showing "wrong sign-in details".
    var isEmailNotVerified: Bool { status == 403 && code == "email_not_verified" }

    /// `409 use_password` — the address belongs to a Keycloak account, so
    /// the emailed code is not that person's way in during the dual-issuer
    /// period (ADR-0047, BE-3). The sign-in screen shows the password form
    /// instead; it is a redirection, not a failure, and it discloses only
    /// what the person just proved they know — their own address.
    var isUsePassword: Bool { status == 409 && code == "use_password" }

    /// `409 legacy_session` — switching workspace re-mints an access token
    /// for another `tid`, and auth-service cannot re-mint a Keycloak token
    /// without Keycloak's key. Recorded up front in ADR-0047 as the one
    /// capability `dual` splits by token origin.
    var isLegacySession: Bool { status == 409 && code == "legacy_session" }

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

// MARK: - Notes (note-service) — the document the app opens natively

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
    /// The heading of a section the template does not name (one the
    /// engine made from the conversation). nil: no heading — the block
    /// is read as the note itself. Round-tripped, never set here.
    var title: String?

    enum CodingKeys: String, CodingKey {
        case sectionKey = "section_key"
        case text
        case fieldSpecificMetadata = "field_specific_metadata"
        case transcriptSegmentIds = "transcript_segment_ids"
        case title
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

/// The document engine's status for one note (Sprint 33): the Notes
/// tab's status line, and whether *Generate Summary* is offered.
struct GenerationView: Decodable, Sendable {
    let id: String
    /// queued | running | partial | complete | failed | superseded
    let status: String
    let windowsTotal: Int?
    let windowsDone: Int?
    /// Why it ended without a document, from a closed vocabulary.
    let errorKind: String?
    /// How many sections the run wrote; 0 on a finished run means the
    /// recording yielded nothing the verifier let through.
    let sectionsWritten: Int?
    /// Q3 — what the recording was taken to be (`meeting`, `interview`,
    /// `podcast_broadcast`, …) and who decided (`user`, `classifier`,
    /// `rule`, `template`). Nil before Q3.
    let recordingType: String?
    let recordingTypeSource: String?
    /// Q2 — the passages the engine left out of the note. Nil or empty
    /// when nothing was, and on runs made before Q2.
    let excludedRanges: [ExcludedRange]?
    /// The spoken language the run wrote in (`en`/`de`/`uk`), so the
    /// exclusions are named in it. Nil before Q3.
    let language: String?

    var isLive: Bool { status == "queued" || status == "running" }
    var isFinished: Bool { status == "complete" || status == "partial" }
    /// Finished, and nothing to show for it: say so, offer another go.
    var wroteNothing: Bool { isFinished && sectionsWritten == 0 }

    var progressText: String {
        if let total = windowsTotal, total > 0 {
            return "Writing this note — \(min(windowsDone ?? 0, total)) of \(total) minutes read"
        }
        return "Writing this note…"
    }

    /// A sentence per reason. The API never sends prose.
    var failureText: String {
        switch errorKind {
        case "budget_exceeded":
            return "This workspace has used its AI budget for the month, so this note was not written up."
        case "generation_disabled":
            return "Automatic note writing is off for this workspace."
        case "processor_unacknowledged":
            return "A workspace admin has to agree to who processes your meetings before notes are written."
        case "no_snapshot", "snapshot_unreadable":
            return "The recording could not be read when the note was written."
        case "model_unavailable":
            return "The model was unavailable. Try writing the note again."
        default:
            return "This note could not be written automatically."
        }
    }

    static let nothingWrittenText =
        "Nothing could be written from this recording: no statement in it could be verified against the words that were said."

    enum CodingKeys: String, CodingKey {
        case id, status
        case windowsTotal = "windows_total"
        case windowsDone = "windows_done"
        case errorKind = "error_kind"
        case sectionsWritten = "sections_written"
        case recordingType = "recording_type"
        case recordingTypeSource = "recording_type_source"
        case excludedRanges = "excluded_ranges"
        case language
    }
}

/// One passage the engine left out of a note (Summary Engine v2, Q2):
/// background speech, another language, a duplicate. `reason` comes from a
/// closed vocabulary, but is kept a string so a reason this build does not
/// know yet still decodes — it is then called "a passage".
struct ExcludedRange: Decodable, Equatable, Sendable {
    let startMs: Int
    let endMs: Int
    let reason: String

    enum CodingKeys: String, CodingKey {
        case reason
        case startMs = "start_ms"
        case endMs = "end_ms"
    }
}

/// The words for what the engine did with a recording (Q3), as the web
/// client says them (`web/src/lib/generation.ts`). Pure, so the tests can
/// pin the wording.
extension GenerationView {
    /// What the recording was taken to be. `meeting` (and anything this
    /// build does not know) has no label: the template name says enough.
    static let recordingTypeLabels: [String: String] = [
        "client_call": "Client call",
        "sales_call": "Sales call",
        "interview": "Interview",
        "one_on_one": "One-on-one",
        "podcast_broadcast": "Podcast / broadcast",
        "lecture_webinar": "Lecture / webinar",
        "presentation_demo": "Presentation / demo",
        "voice_memo": "Voice memo",
    ]

    static func recordingTypeLabel(_ recordingType: String?) -> String? {
        guard let recordingType, recordingType != "meeting" else { return nil }
        return recordingTypeLabels[recordingType]
    }

    var recordingTypeLabel: String? { Self.recordingTypeLabel(recordingType) }

    /// Why a passage was left out, in the language that was spoken. The
    /// API never sends prose; `passage` is the word for a reason this
    /// build does not know.
    static let noiseLabels: [String: [String: String]] = [
        "en": [
            "background": "background speech",
            "other_language": "a passage in another language",
            "artifact": "a transcription artifact",
            "duplicate": "a duplicated passage",
            "unrelated": "an unrelated fragment",
            "advertisement": "an advertisement",
            "passage": "a passage",
        ],
        "de": [
            "background": "Hintergrundgespräch",
            "other_language": "eine Passage in einer anderen Sprache",
            "artifact": "ein Transkriptionsartefakt",
            "duplicate": "eine doppelte Passage",
            "unrelated": "ein unzusammenhängendes Fragment",
            "advertisement": "Werbung",
            "passage": "eine Passage",
        ],
        "uk": [
            "background": "фонова мова",
            "other_language": "уривок іншою мовою",
            "artifact": "артефакт транскрипції",
            "duplicate": "повторений уривок",
            "unrelated": "непов'язаний фрагмент",
            "advertisement": "реклама",
            "passage": "уривок",
        ],
    ]

    static func noiseLabel(_ reason: String, language: String?) -> String {
        let labels = noiseLabels[language ?? ""] ?? noiseLabels["en"] ?? [:]
        return labels[reason] ?? labels["passage"] ?? "a passage"
    }

    /// Ranges shown before "+N more".
    static let maxShownRanges = 4

    /// "00:45" — minutes are not wrapped into hours, as on the web.
    static func mmss(_ ms: Int) -> String {
        let total = max(0, ms / 1000)
        return String(format: "%02d:%02d", total / 60, total % 60)
    }

    struct ExcludedItem: Equatable, Sendable {
        let startMs: Int
        /// "00:45–00:52 (background speech)"
        let text: String
    }

    /// Every excluded passage, in time order, in the note's language.
    var excludedItems: [ExcludedItem] {
        (excludedRanges ?? [])
            .sorted { $0.startMs < $1.startMs }
            .map { range in
                ExcludedItem(
                    startMs: range.startMs,
                    text: "\(Self.mmss(range.startMs))–\(Self.mmss(range.endMs)) (\(Self.noiseLabel(range.reason, language: language)))"
                )
            }
    }

    /// The items the line shows, and how many more there are.
    var shownExcluded: (items: [ExcludedItem], more: Int) {
        let all = excludedItems
        let shown = Array(all.prefix(Self.maxShownRanges))
        return (shown, all.count - shown.count)
    }
}

struct GenerationStarted: Decodable, Sendable {
    let id: String
    let status: String
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
    /// Sprint F1: how much of the speech made it into the transcript, and
    /// the stretches that did not. Absent from older servers and results.
    var coverage: TranscriptCoverage? = nil
    /// Sprint F1: the capture timing the recording app sent.
    var capture: CaptureInfo? = nil

    enum CodingKeys: String, CodingKey {
        case jobId = "job_id"
        case coverage, capture
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

/// One page pushed on the navigation stack.
enum Selection: Hashable {
    /// One of this phone's captures (by ASR job id) — a note once it has one.
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
    /// Sprint 34 — stable across the copies an invite makes in several
    /// calendars, and the agenda the server read out of its description
    /// (the description itself never leaves the server).
    let icalUid: String
    let agendaLines: [String]

    enum CodingKeys: String, CodingKey {
        case id, color, title, start, end, location, attendees, organizer
        case icalUid = "ical_uid"
        case agendaLines = "agenda_lines"
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

// MARK: - The note that exists from the first second (Sprint 34, ADR-0055)

/// What a capture is doing right now. It lives on `note_meetings`, not on
/// the note's status — a note is a draft until it is cancelled (ADR-0051).
enum MeetingState: String, Codable, Sendable {
    case recording, uploading, transcribing, generating, ready
    case noAudio = "no_audio"
    case failed

    /// Whether the recording still has to reach the server. The sweeper
    /// reclaims these after 12 hours; a client that is still alive should
    /// not leave one behind.
    var isPreUpload: Bool { self == .recording || self == .uploading }
}

/// What kind of meeting this is — picks the template family the note is
/// written into. `auto` is the default and is always right enough.
enum MeetingType: String, Codable, CaseIterable, Sendable {
    case auto, client, team, sales
    case oneOnOne = "one_on_one"
    case interview

    var label: String {
        switch self {
        case .auto: return "Auto"
        case .client: return "Client"
        case .team: return "Team"
        case .sales: return "Sales"
        case .oneOnOne: return "1:1"
        case .interview: return "Interview"
        }
    }
}

/// What the invite knew, as `POST /v1/notes/meeting` takes it.
///
/// `description` is only ever sent for an EventKit event, whose notes field
/// the client has but the server has never seen; the server reads the
/// agenda out of it and discards the rest. For a server-owned calendar the
/// agenda arrives already extracted on `/v1/calendar/events`.
struct MeetingCalendarContext: Codable, Equatable, Sendable {
    var source: String
    var title: String?
    var icalUid: String?
    var attendeeNames: [String]?
    var agendaLines: [String]?
    var description: String?

    /// The server's cap on an EventKit notes field.
    static let maxDescription = 8192

    enum CodingKeys: String, CodingKey {
        case source, title, description
        case icalUid = "ical_uid"
        case attendeeNames = "attendee_names"
        case agendaLines = "agenda_lines"
    }
}

struct StartMeetingRequest: Encodable, Sendable {
    let clientCaptureId: String
    let title: String?
    /// ISO-8601, explicitly: the shared `JSONEncoder` has no date strategy
    /// and a Unix timestamp on the wire is a contract nobody can read.
    let startedAt: String
    let language: String?
    let meetingType: String
    let calendar: MeetingCalendarContext?

    enum CodingKeys: String, CodingKey {
        case title, language, calendar
        case clientCaptureId = "client_capture_id"
        case startedAt = "started_at"
        case meetingType = "meeting_type"
    }
}

struct StartMeetingResponse: Decodable, Sendable {
    let id: String
    let code: String
    let versionNumber: Int
    let templateId: String
    let state: MeetingState

    enum CodingKeys: String, CodingKey {
        case id, code, state
        case versionNumber = "version_number"
        case templateId = "template_id"
    }
}

/// `GET /v1/notes/{id}/meeting` — what a second device needs to show the
/// right status and to finish what the first one started.
struct MeetingInfo: Decodable, Sendable {
    let state: MeetingState
    let asrJobId: String?
    let meetingType: MeetingType
    let startedAt: Date

    enum CodingKeys: String, CodingKey {
        case state
        case asrJobId = "asr_job_id"
        case meetingType = "meeting_type"
        case startedAt = "started_at"
    }
}

struct AttachTranscriptResponse: Decodable, Sendable {
    let id: String
    let versionNumber: Int
    let state: MeetingState

    enum CodingKeys: String, CodingKey {
        case id, state
        case versionNumber = "version_number"
    }
}

/// When a typed line was first touched, relative to the recording's t=0.
struct UserLineTime: Codable, Equatable, Sendable {
    let lineKey: String
    let offsetMs: Int

    enum CodingKeys: String, CodingKey {
        case lineKey = "line_key"
        case offsetMs = "offset_ms"
    }
}

// MARK: - The workspace glossary (Sprint 35)

/// A name, company, product or term this workspace spells a particular way.
///
/// The point of the table is that a correction is made once. You fix "Jon
/// Meyer" to "John Mayer", the workspace remembers it, and the transcriber
/// is told the spelling before the next recording instead of guessing the
/// same way again.
struct GlossaryTerm: Decodable, Identifiable, Equatable, Sendable {
    let id: String
    let term: String
    let kind: GlossaryKind
    /// How it has been misheard or misspelled before.
    let heardAs: [String]
    let createdAt: Date
    /// Whether this person may remove it: its creator, or an admin.
    let canDelete: Bool
    /// Sprint I2 — whether the server still sends it to the transcriber.
    /// False for a role label ("Moderator II") that got in before the
    /// rule existed: kept so it can be seen and removed, never sent.
    let inHint: Bool
    /// The note it was remembered from, when it came from a correction.
    let sourceNoteId: String?

    enum CodingKeys: String, CodingKey {
        case id, term, kind
        case heardAs = "heard_as"
        case createdAt = "created_at"
        case canDelete = "can_delete"
        case inHint = "in_hint"
        case sourceNoteId = "source_note_id"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        term = try c.decode(String.self, forKey: .term)
        kind = try c.decode(GlossaryKind.self, forKey: .kind)
        heardAs = try c.decodeIfPresent([String].self, forKey: .heardAs) ?? []
        createdAt = try c.decode(Date.self, forKey: .createdAt)
        canDelete = try c.decode(Bool.self, forKey: .canDelete)
        // An older server does not say; everything it stores is sent.
        inHint = try c.decodeIfPresent(Bool.self, forKey: .inHint) ?? true
        sourceNoteId = try c.decodeIfPresent(String.self, forKey: .sourceNoteId)
    }
}

enum GlossaryKind: String, Codable, CaseIterable, Sendable {
    case person, company, product, term

    var label: String {
        switch self {
        case .person: return "Person"
        case .company: return "Company"
        case .product: return "Product"
        case .term: return "Term"
        }
    }
}

/// `GET /v1/glossary/hint` — the terms as the capture form's
/// `vocabulary_hint`, ready to send with the next upload.
struct GlossaryHint: Decodable, Equatable, Sendable {
    let hint: String
    let terms: Int
}

struct RememberTermRequest: Encodable, Sendable {
    let term: String
    let kind: String
    let heardAs: [String]
    /// The note the correction was made in, when there is one (Sprint I2).
    var noteId: String? = nil

    enum CodingKeys: String, CodingKey {
        case term, kind
        case heardAs = "heard_as"
        case noteId = "note_id"
    }
}

/// Whether a rename is worth offering to remember, and what the old
/// spelling should be recorded as.
///
/// Only a real correction counts: a name typed over a placeholder or over
/// a different name. A name cleared back to "Speaker 2", or one that only
/// changed case or spacing, teaches nothing — and an offer that appears
/// when nothing was learned trains people to dismiss it.
enum RememberableName {
    /// Characters a term may not contain — the same set the server
    /// refuses. Written as code-point RANGES rather than as a literal
    /// character class: half of them are invisible, and source that
    /// contains a bidi override in order to reject bidi overrides is
    /// source nobody can review.
    ///
    ///   0000–001F, 007F–009F  C0 / C1 controls
    ///   200B–200F             zero-width space, joiners, LRM/RLM
    ///   2028–202E             line/paragraph separators, bidi embedding
    ///   2066–2069             bidi isolates
    static let forbidden: [ClosedRange<UInt32>] = [
        0x0000...0x001F, 0x007F...0x009F, 0x200B...0x200F, 0x2028...0x202E, 0x2066...0x2069,
    ]

    /// Whitespace collapsed, exactly as the server stores it — so a
    /// rename that only changes the spacing compares as no change.
    static func normalised(_ name: String) -> String {
        name.split(whereSeparator: \.isWhitespace).joined(separator: " ")
    }

    static func isPlaceholder(_ name: String) -> Bool {
        let trimmed = normalised(name).lowercased()
        guard trimmed.hasPrefix("speaker") else { return false }
        let rest = trimmed.dropFirst("speaker".count).trimmingCharacters(in: .whitespaces)
        return !rest.isEmpty && rest.allSatisfy(\.isNumber)
    }

    // MARK: Role labels are not vocabulary (Sprint I2)

    /// Words a person uses to label a voice rather than name it, in the
    /// three languages the apps speak. The one list every client and the
    /// server share: `tests/fixtures/glossary/role_words.json`, and the
    /// test asserts this set equals it. A term made only of these (and
    /// ordinals) is "Moderator II", not a name — and once it reached the
    /// glossary it was read to the transcriber before every recording,
    /// which echoed it into a transcript (the 2026-09-25 incident).
    static let roleWords: Set<String> = [
        // en
        "speaker", "moderator", "host", "narrator", "guest", "interviewer", "interviewee",
        "presenter", "caller", "background", "unknown", "voice", "participant", "translator",
        "announcer",
        // de
        "sprecher", "sprecherin", "moderatorin", "gast", "gastgeber", "erzähler", "erzählerin",
        "hintergrund", "unbekannt", "stimme", "teilnehmer", "teilnehmerin", "übersetzer",
        // uk
        "спікер", "ведучий", "ведуча", "гість", "гостя", "оповідач", "фон", "невідомий", "голос",
        "учасник", "учасниця", "перекладач",
    ]

    static let ordinals: Set<String> = [
        "i", "ii", "iii", "iv", "v", "1", "2", "3", "4", "5", "one", "two", "three", "eins", "zwei",
        "drei", "один", "два", "три", "first", "second", "erste", "zweite", "перший", "другий",
    ]

    /// Whether a term belongs in the transcriber's vocabulary — the same
    /// rule as the server's `is_vocabulary`.
    ///
    /// No: every token is a role word or an ordinal; a person with no
    /// capital letter anywhere ("moderatorin"). Yes: anything else — the
    /// rule only has to keep labels out, not judge names.
    static func isVocabulary(_ term: String, kind: GlossaryKind) -> Bool {
        let tokens = term.split { !($0.isLetter || $0.isNumber) }.map { $0.lowercased() }
        guard !tokens.isEmpty else { return false }
        if tokens.allSatisfy({ roleWords.contains($0) || ordinals.contains($0) }) { return false }
        if kind == .person {
            let anyCapital = term.split(whereSeparator: \.isWhitespace).contains { part in
                part.unicodeScalars.first?.properties.isUppercase == true
            }
            if !anyCapital { return false }
        }
        return true
    }

    static func worthRemembering(from: String, to: String) -> Bool {
        let term = normalised(to)
        guard term.count >= 2, term.count <= 80, !isPlaceholder(term) else { return false }
        guard normalised(from).lowercased() != term.lowercased() else { return false }
        guard isVocabulary(term, kind: .person) else { return false }
        return !term.unicodeScalars.contains { scalar in
            forbidden.contains { $0.contains(scalar.value) }
        }
    }

    /// The previous spelling, or "" when it was only a placeholder.
    static func heardAs(_ from: String) -> String {
        let previous = normalised(from)
        return isPlaceholder(previous) || previous.count < 2 ? "" : previous
    }
}

// MARK: - Who processes this workspace's meetings (Sprint 37)

/// One company in the data path, as the server's registry reports it.
struct AIProcessor: Decodable, Identifiable, Equatable, Sendable {
    let name: String
    let region: String
    /// What it does with the data — "writing your meeting notes", …
    let purpose: String
    /// Which tiers route to it.
    let tiers: [String]
    let acknowledged: Bool

    var id: String { "\(name)/\(region)" }
}

/// `GET /v1/ai/settings`. Read-only here on purpose: changing who
/// processes a workspace's meetings is an admin decision with an
/// acknowledgement dialog, and it belongs on one surface — the web page.
struct AISettings: Decodable, Equatable, Sendable {
    let provider: String
    let tier: String
    let generationEnabled: Bool
    let effectiveProvider: String
    let effectiveTier: String
    let processors: [AIProcessor]
    let needsAcknowledgement: [AIProcessor]
    let monthToDateCents: Int
    let budgetCents: Int
    let mayChoosePremium: Bool
    let canEdit: Bool

    enum CodingKeys: String, CodingKey {
        case provider, tier, processors
        case generationEnabled = "generation_enabled"
        case effectiveProvider = "effective_provider"
        case effectiveTier = "effective_tier"
        case needsAcknowledgement = "needs_acknowledgement"
        case monthToDateCents = "month_to_date_cents"
        case budgetCents = "budget_cents"
        case mayChoosePremium = "may_choose_premium"
        case canEdit = "can_edit"
    }
}
