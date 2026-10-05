import CryptoKit
import Foundation
import LocalAuthentication
import Security

/// Which issuer minted the session (ADR-0047). The discriminator is the
/// refresh token's prefix, the same one the server routes on.
enum SessionKind: String, Codable, Equatable, Sendable {
    /// auth-service's own session (`nrt_…`), owned by `session_native`.
    case native
    /// A Keycloak refresh token, proxied by `routers/login.py`.
    case keycloak

    /// `native_refresh_token`, the prefix `session_native` mints with.
    static let nativePrefix = "nrt_"

    init(refreshToken: String) {
        self = refreshToken.hasPrefix(Self.nativePrefix) ? .native : .keycloak
    }

    /// Keycloak tokens idle out after ~30 minutes, native ones after 30 days;
    /// only the first needs a background keepalive.
    var needsKeepAlive: Bool { self == .keycloak }

    /// Only a Keycloak user has a password to save.
    var canSavePassword: Bool { self == .keycloak }

    /// The gate is native-only: a Keycloak session already sits behind the saved password's biometry.
    var canGate: Bool { self == .native }
}

/// The signed-in session, kept in the Keychain. The access token is
/// deliberately absent (short-lived, re-mintable). Either issuer's refresh
/// token lives here; `kind` tells them apart. Keycloak users' passwords are
/// still kept separately (`CredentialStore`) during `dual`.
struct StoredSession: Equatable, Sendable {
    var refreshToken: String
    var refreshExpiresAt: Date
    var identityId: String
    var email: String
    var lastTenantId: String?

    var isExpired: Bool { refreshExpiresAt <= Date() }

    /// Read off the token itself, so record and token can never disagree.
    var kind: SessionKind { SessionKind(refreshToken: refreshToken) }
}

/// What the Keychain item holds. `token` is in the clear with the gate off,
/// an AES-GCM sealed box when on; the other fields stay readable so boot can
/// decide before any Face ID prompt.
struct SessionRecord: Codable, Equatable, Sendable {
    var token: String
    var gated: Bool = false
    /// Which issuer minted the token; in the clear so the keepalive decision
    /// precedes any prompt. Defaults to `.native` for older items.
    var kind: SessionKind = .native
    var refreshExpiresAt: Date
    var identityId: String
    var email: String
    var lastTenantId: String?

    enum CodingKeys: String, CodingKey {
        case token, gated, kind
        case refreshExpiresAt = "refresh_expires_at"
        case identityId = "identity_id"
        case email
        case lastTenantId = "last_tenant_id"
    }

    var isExpired: Bool { refreshExpiresAt <= Date() }
}

/// The part of a stored session that can be read without unlocking it.
struct SessionSummary: Equatable, Sendable {
    let identityId: String
    let email: String
    let lastTenantId: String?
    let refreshExpiresAt: Date
    let gated: Bool
    let kind: SessionKind

    var isExpired: Bool { refreshExpiresAt <= Date() }
}

enum SessionStoreError: LocalizedError, Equatable {
    /// The Keychain refused the write (`OSStatus`).
    case writeFailed(OSStatus)
    /// The gate is on and the key has not been unlocked in this launch.
    case locked
    /// The gate item is gone (biometry re-enrolled or passcode removed); the session is unreadable for good.
    case gateLost
    /// Item and key present but the bytes will not open: wrong key or tampered item.
    case undecipherable
    /// The gate was asked for on a Keycloak session, which cannot carry one.
    case gateUnavailable

    var errorDescription: String? {
        switch self {
        case .writeFailed(let status):
            let detail = SecCopyErrorMessageString(status, nil) as String? ?? "OSStatus \(status)"
            return "This phone's Keychain would not store the sign-in (\(detail))."
        case .locked:
            return "Unlock Notes AI to continue."
        case .gateLost:
            return SessionLostReason.biometryChanged.message
        case .undecipherable:
            return "The saved sign-in could not be opened. Sign in again."
        case .gateUnavailable:
            return "This sign-in cannot be locked with \(Biometrics.name ?? "the passcode") yet. Sign in with an emailed code instead."
        }
    }
}

// MARK: - Storage seams

/// Where the session bytes go: the Keychain in the app, a fake in the tests.
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

/// The optional biometric gate: a random 32-byte key in its own Keychain item
/// (`.biometryCurrentSet`, so re-enrolling destroys it). Separate from the
/// session item because the two need different accessibility classes.
protocol SessionGateKeyring: Sendable {
    /// Whether a gate key exists, without showing any UI.
    func exists() -> Bool
    /// Create (or replace) the key.
    func create() throws -> SymmetricKey
    /// Show the biometric prompt and hand back the key.
    func unlock(reason: String) async throws -> SymmetricKey
    func destroy()
}

struct KeychainSessionGate: SessionGateKeyring {
    static let service = "ai.notes.capture.session.gate"
    static let account = "gate-key"

    private var baseQuery: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: Self.service,
            kSecAttrAccount as String: Self.account,
        ]
    }

    func exists() -> Bool {
        // Told to fail rather than show UI: "would need UI" means "exists".
        let context = LAContext()
        context.interactionNotAllowed = true
        var query = baseQuery
        query[kSecUseAuthenticationContext as String] = context
        let status = SecItemCopyMatching(query as CFDictionary, nil)
        return status == errSecSuccess || status == errSecInteractionNotAllowed
    }

    func create() throws -> SymmetricKey {
        destroy()
        var error: Unmanaged<CFError>?
        // `.biometryCurrentSet` is the point of the gate; with no biometry
        // enrolled such an item cannot exist, so fall back to `.userPresence` (passcode).
        let flags: SecAccessControlCreateFlags =
            Biometrics.name == nil ? .userPresence : .biometryCurrentSet
        guard let access = SecAccessControlCreateWithFlags(
            nil, kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly, flags, &error)
        else { throw SessionStoreError.writeFailed(errSecParam) }
        let key = SymmetricKey(size: .bits256)
        var attributes = baseQuery
        attributes[kSecAttrAccessControl as String] = access
        attributes[kSecValueData as String] = key.rawBytes
        attributes[kSecAttrSynchronizable as String] = false
        let status = SecItemAdd(attributes as CFDictionary, nil)
        guard status == errSecSuccess else { throw SessionStoreError.writeFailed(status) }
        return key
    }

    func unlock(reason: String) async throws -> SymmetricKey {
        // `SecItemCopyMatching` blocks its thread while the prompt is up.
        try await Task.detached(priority: .userInitiated) { () -> SymmetricKey in
            let context = LAContext()
            context.localizedReason = reason
            let query: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: Self.service,
                kSecAttrAccount as String: Self.account,
                kSecReturnData as String: true,
                kSecMatchLimit as String: kSecMatchLimitOne,
                kSecUseAuthenticationContext as String: context,
            ]
            var result: AnyObject?
            let status = SecItemCopyMatching(query as CFDictionary, &result)
            switch status {
            case errSecSuccess:
                guard let data = result as? Data, data.count == 32 else {
                    throw SessionStoreError.gateLost
                }
                return SymmetricKey(data: data)
            case errSecItemNotFound:
                // `.biometryCurrentSet` invalidated the item: biometry re-enrolled.
                throw SessionStoreError.gateLost
            case errSecUserCanceled, errSecAuthFailed, errSecInteractionNotAllowed:
                throw SessionStoreError.locked
            default:
                throw SessionStoreError.writeFailed(status)
            }
        }.value
    }

    func destroy() {
        SecItemDelete(baseQuery as CFDictionary)
    }
}

private extension SymmetricKey {
    var rawBytes: Data { withUnsafeBytes { Data($0) } }
}

// MARK: - The store

/// The session's one home. An actor: `APIClient` persists a rotated refresh
/// token BEFORE publishing the new access token, so a crash never leaves a
/// retired (replayable) token on disk.
actor SessionStore {
    private let storage: SessionStorage
    private let gate: SessionGateKeyring
    /// Read once, then kept.
    private var cached: SessionRecord?
    private var loaded = false
    /// The gate key, once this launch has been unlocked. Memory only.
    private var gateKey: SymmetricKey?

    init(storage: SessionStorage = KeychainSessionStorage(),
         gate: SessionGateKeyring = KeychainSessionGate()) {
        self.storage = storage
        self.gate = gate
    }

    // ── what can be read without a face ──────────────────────────────

    /// Who the stored session belongs to and whether it is gated. Never prompts.
    func summary() -> SessionSummary? {
        guard let record = record() else { return nil }
        return SessionSummary(identityId: record.identityId,
                              email: record.email,
                              lastTenantId: record.lastTenantId,
                              refreshExpiresAt: record.refreshExpiresAt,
                              gated: record.gated,
                              kind: record.kind)
    }

    var isGateOn: Bool { record()?.gated ?? gate.exists() }

    /// Which issuer minted the stored session; nil when none. Never prompts.
    var kind: SessionKind? { record()?.kind }

    /// True when the refresh token can be read right now.
    var isUnlocked: Bool {
        guard let record = record() else { return false }
        return !record.gated || gateKey != nil
    }

    // ── the token itself ─────────────────────────────────────────────

    /// The session, decrypted. Throws `.locked` while gated, `.gateLost` when the key is gone.
    func load() throws -> StoredSession? {
        guard let record = record() else { return nil }
        let token = try open(record)
        return StoredSession(refreshToken: token,
                             refreshExpiresAt: record.refreshExpiresAt,
                             identityId: record.identityId,
                             email: record.email,
                             lastTenantId: record.lastTenantId)
    }

    /// Show the biometric prompt and keep the key for this launch. `.gateLost` wipes the session.
    func unlock(reason: String) async throws {
        guard let record = record(), record.gated else { return }
        do {
            gateKey = try await gate.unlock(reason: reason)
        } catch SessionStoreError.gateLost {
            clear()
            throw SessionStoreError.gateLost
        }
    }

    func save(_ session: StoredSession) throws {
        // Signing in again must not silently turn the gate off: with a gate item
        // but no key this launch, mint a fresh key rather than prompt. A Keycloak
        // session cannot be gated, so its gate key is left untouched for the next native sign-in.
        if session.kind.canGate, gateKey == nil, gate.exists() {
            gateKey = try gate.create()
        }
        let gated = session.kind.canGate && gateKey != nil
        try write(SessionRecord(
            token: try seal(session.refreshToken, gated: gated),
            gated: gated,
            kind: session.kind,
            refreshExpiresAt: session.refreshExpiresAt,
            identityId: session.identityId,
            email: session.email,
            lastTenantId: session.lastTenantId))
    }

    /// Update the token half in place, keeping who it belongs to.
    func rotate(refreshToken: String, expiresAt: Date, tenantId: String?) throws {
        guard var record = record() else { return }
        if record.gated, gateKey == nil { throw SessionStoreError.locked }
        // The issuer follows the token actually held, not the record it replaces.
        record.kind = SessionKind(refreshToken: refreshToken)
        record.token = try seal(refreshToken, gated: record.gated)
        record.refreshExpiresAt = expiresAt
        if let tenantId { record.lastTenantId = tenantId }
        try write(record)
    }

    /// Remember which workspace the session is in, without touching the token.
    func rotateTenant(tenantId: String) throws {
        guard var record = record(), record.lastTenantId != tenantId else { return }
        record.lastTenantId = tenantId
        try write(record)
    }

    func clear() {
        storage.delete()
        cached = nil
        loaded = true
        gateKey = nil
    }

    // ── the gate ─────────────────────────────────────────────────────

    /// Turn the gate on or off, re-writing the session item. On needs the
    /// token in the clear (signed in, unlocked); off destroys the key first.
    func setGate(enabled: Bool) async throws {
        guard var record = record() else {
            // Not signed in: still honour the switch for the next session.
            if enabled {
                gateKey = try gate.create()
            } else {
                gate.destroy()
                gateKey = nil
            }
            return
        }
        guard record.kind.canGate else {
            // A Keycloak session cannot be gated: turning *on* is reported,
            // turning *off* is honoured (de-escalation is never refused).
            guard enabled else {
                gate.destroy()
                gateKey = nil
                return
            }
            throw SessionStoreError.gateUnavailable
        }
        let token = try open(record)
        if enabled {
            gateKey = try gate.create()
            record.token = try seal(token, gated: true)
            record.gated = true
        } else {
            gate.destroy()
            gateKey = nil
            record.token = token
            record.gated = false
        }
        try write(record)
    }

    // ── internals ────────────────────────────────────────────────────

    private func record() -> SessionRecord? {
        if loaded { return cached }
        loaded = true
        guard let data = storage.read() else { return nil }
        cached = try? JSONDecoder.session.decode(SessionRecord.self, from: data)
        if cached == nil {
            // Unreadable (older shape, truncated write): treat as no session.
            storage.delete()
        }
        return cached
    }

    private func write(_ record: SessionRecord) throws {
        let data = try JSONEncoder.session.encode(record)
        let status = storage.write(data)
        guard status == errSecSuccess else { throw SessionStoreError.writeFailed(status) }
        cached = record
        loaded = true
    }

    private func seal(_ token: String, gated: Bool) throws -> String {
        guard gated else { return token }
        guard let key = gateKey else { throw SessionStoreError.locked }
        guard let sealed = try? AES.GCM.seal(Data(token.utf8), using: key).combined else {
            throw SessionStoreError.undecipherable
        }
        return sealed.base64EncodedString()
    }

    private func open(_ record: SessionRecord) throws -> String {
        guard record.gated else { return record.token }
        guard let key = gateKey else { throw SessionStoreError.locked }
        guard let bytes = Data(base64Encoded: record.token),
              let box = try? AES.GCM.SealedBox(combined: bytes),
              let opened = try? AES.GCM.open(box, using: key),
              let token = String(data: opened, encoding: .utf8)
        else { throw SessionStoreError.undecipherable }
        return token
    }
}

extension JSONEncoder {
    /// ISO-8601 dates, readable by eye.
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

// MARK: - Biometrics on this device

enum Biometrics {
    /// "Face ID", "Touch ID", or nil when the device has neither enrolled.
    static var name: String? {
        let context = LAContext()
        guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: nil) else {
            return nil
        }
        switch context.biometryType {
        case .faceID: return "Face ID"
        case .touchID: return "Touch ID"
        case .opticID: return "Optic ID"
        default: return nil
        }
    }

    static var symbol: String {
        switch LAContext().biometryType {
        case .touchID: return "touchid"
        case .opticID: return "opticid"
        default: return "faceid"
        }
    }

    /// A passcode will do without biometry; the gate item needs `kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly`.
    static var isAvailable: Bool {
        LAContext().canEvaluatePolicy(.deviceOwnerAuthentication, error: nil)
    }

    /// What the toggle is called on this phone.
    static var gateTitle: String {
        "Require \(name ?? "the passcode") to open"
    }
}

// MARK: - What the app used to keep, and no longer does

/// The Keycloak-era refresh cookie.
enum LegacyCookies {
    static let name = "mdx_rt"

    /// Delete any legacy `mdx_rt` cookie left in the shared store. Returns how many were removed.
    @discardableResult
    static func purge(from storage: HTTPCookieStorage = .shared) -> Int {
        let stale = (storage.cookies ?? []).filter { $0.name == name }
        for cookie in stale { storage.deleteCookie(cookie) }
        return stale.count
    }
}

/// The password vault's service string and its delete side (`purge()`);
/// `CredentialStore` reads and writes it during `dual` (ADR-0047).
enum LegacyCredentials {
    static let service = "ai.notes.capture.credentials"

    /// Whether the old item is still there. Does not prompt ("would need UI" means "exists").
    static var exists: Bool {
        let context = LAContext()
        context.interactionNotAllowed = true
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecUseAuthenticationContext as String: context,
        ]
        let status = SecItemCopyMatching(query as CFDictionary, nil)
        return status == errSecSuccess || status == errSecInteractionNotAllowed
    }

    /// Delete every item under the old service; deleting a biometry-bound item needs no biometry.
    @discardableResult
    static func purge() -> Int {
        let existed = exists
        SecItemDelete([
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
        ] as CFDictionary)
        return existed ? 1 : 0
    }
}

/// The one-time cut-over from the password vault to a device session. Held
/// back during `dual`: only the refresh cookie is cleaned; `purgeCredentials`
/// defaults to a no-op until every user is native.
enum SessionMigration {
    static let key = "sessionMigrationV1"

    /// Runs once per install. Returns the sign-in notice, or nil (a purged cookie is not news).
    @discardableResult
    static func run(defaults: UserDefaults = .standard,
                    purgeCredentials: () -> Int = { 0 },
                    purgeCookies: () -> Int = { LegacyCookies.purge() }) -> String? {
        guard !defaults.bool(forKey: key) else { return nil }
        defaults.set(true, forKey: key)
        _ = purgeCookies()
        guard purgeCredentials() > 0 else { return nil }
        return "Sign-in now uses a device session; your password is no longer stored on this phone."
    }
}
