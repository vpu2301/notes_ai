import Foundation
import Security

/// The signed-in session, as this Mac keeps it.
///
/// Everything here is a credential or names one, which is why it lives in
/// the Keychain and not in UserDefaults beside the backend URLs. The
/// access token is deliberately absent: it lives fifteen minutes, it is
/// re-mintable from the refresh token, and writing it to disk would be
/// storing a secret with none of the benefits of storing it.
struct StoredSession: Codable, Equatable, Sendable {
    var refreshToken: String
    var refreshExpiresAt: Date
    var identityId: String
    var email: String
    var lastTenantId: String?

    enum CodingKeys: String, CodingKey {
        case refreshToken = "refresh_token"
        case refreshExpiresAt = "refresh_expires_at"
        case identityId = "identity_id"
        case email
        case lastTenantId = "last_tenant_id"
    }

    var isExpired: Bool { refreshExpiresAt <= Date() }
}

enum SessionStoreError: LocalizedError {
    /// The Keychain refused the write (`OSStatus`).
    case writeFailed(OSStatus)

    var errorDescription: String? {
        switch self {
        case .writeFailed(let status):
            let detail = SecCopyErrorMessageString(status, nil) as String? ?? "OSStatus \(status)"
            return "This Mac's Keychain would not store the sign-in (\(detail))."
        }
    }
}

/// Where the session bytes actually go. One implementation in the app
/// (the Keychain), another in the tests — the session logic is worth
/// exercising without a login keychain to depend on.
protocol SessionStorage: Sendable {
    func read() -> Data?
    func write(_ data: Data) -> OSStatus
    func delete()
}

struct KeychainSessionStorage: SessionStorage {
    /// One item, one session: this app signs one identity in at a time.
    static let account = "session"

    func read() -> Data? {
        Keychain.read(account: Self.account, service: Keychain.sessionService)
    }

    func write(_ data: Data) -> OSStatus {
        Keychain.write(account: Self.account, secret: data, service: Keychain.sessionService)
    }

    func delete() {
        Keychain.delete(account: Self.account, service: Keychain.sessionService)
    }
}

/// The session's one home, serialised.
///
/// An actor because the refresh path both reads and writes it while other
/// requests are in flight, and the ordering there is the whole point:
/// `APIClient` persists a rotated refresh token **before** it publishes
/// the new access token, so a crash in between leaves the newest token on
/// disk rather than a token the server has already retired — which, after
/// the grace window, the server would treat as a replay and sign the
/// person out for security.
actor SessionStore {
    private let storage: SessionStorage
    /// Read once, then kept: every authorised request that needs a refresh
    /// would otherwise go to the Keychain first.
    private var cached: StoredSession?
    private var loaded = false

    init(storage: SessionStorage = KeychainSessionStorage()) {
        self.storage = storage
    }

    func load() -> StoredSession? {
        if loaded { return cached }
        loaded = true
        guard let data = storage.read() else { return nil }
        cached = try? JSONDecoder.session.decode(StoredSession.self, from: data)
        if cached == nil {
            // Unreadable (an older shape, a truncated write): treat it as no
            // session rather than leaving a value nothing can use.
            storage.delete()
        }
        return cached
    }

    func save(_ session: StoredSession) throws {
        let data = try JSONEncoder.session.encode(session)
        let status = storage.write(data)
        guard status == errSecSuccess else { throw SessionStoreError.writeFailed(status) }
        cached = session
        loaded = true
    }

    /// Update the token half in place, keeping who it belongs to.
    func rotate(refreshToken: String, expiresAt: Date, tenantId: String?) throws {
        guard var session = load() else { return }
        session.refreshToken = refreshToken
        session.refreshExpiresAt = expiresAt
        if let tenantId { session.lastTenantId = tenantId }
        try save(session)
    }

    /// Remember the workspace the person switched to, so the next launch
    /// opens where they left off rather than where they signed in.
    func setTenant(_ tenantId: String) throws {
        guard var session = load(), session.lastTenantId != tenantId else { return }
        session.lastTenantId = tenantId
        try save(session)
    }

    func clear() {
        storage.delete()
        cached = nil
        loaded = true
    }
}

extension JSONEncoder {
    /// ISO-8601 dates so the item stays readable by eye when something
    /// goes wrong (`security find-generic-password -s ai.notes.capture.session -w`).
    static let session: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }()
}

extension JSONDecoder {
    static let session: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()
}

// MARK: - The cookie this app used to sign in with

enum LegacyCookies {
    /// The Keycloak-era refresh cookie.
    static let name = "mdx_rt"

    /// Delete any `mdx_rt` cookie left in the shared store.
    ///
    /// Before IDX-M1 the refresh token lived here — on disk, protected by
    /// nothing but FileVault, and attached automatically to every request
    /// to the auth host. The app no longer uses cookie storage at all
    /// (`URLSession` is built with none), so a cookie left behind would
    /// be a credential nothing reads and nobody rotates. Returns how many
    /// were removed, which is what the test asserts on.
    @discardableResult
    static func purge(from storage: HTTPCookieStorage = .shared) -> Int {
        let stale = (storage.cookies ?? []).filter { $0.name == name }
        for cookie in stale { storage.deleteCookie(cookie) }
        return stale.count
    }
}
