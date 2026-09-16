import CryptoKit
import Foundation
import LocalAuthentication
import Security

/// Which issuer minted the session this phone is holding.
///
/// During the dual-issuer period (ADR-0047) both are live at once:
/// auth-service mints for email-code sign-ins, Keycloak keeps minting for
/// password sign-ins, and a client has to know which one it has because
/// the two behave differently in ways the person can feel — how long the
/// refresh token idles, and whether there is a password to save.
///
/// The discriminator is the refresh token's own prefix, which is also what
/// BE-2 routes `/auth/refresh` and `/auth/logout` on, so the phone and the
/// server cannot disagree about what a token is.
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

    /// Keycloak's refresh token dies after the realm's idle timeout —
    /// thirty minutes in this deployment — while a native one idles for
    /// thirty days (`AUTH_REFRESH_TTL_SECONDS`). Only the first kind needs
    /// the app to refresh in the background to survive a long recording,
    /// and running a keepalive for the second would be a phone waking up
    /// every quarter of an hour for nothing.
    var needsKeepAlive: Bool { self == .keycloak }

    /// Only a Keycloak user has a password to save: the native issuer has
    /// no password grant until IDX-A4, and email codes are the way in.
    var canSavePassword: Bool { self == .keycloak }

    /// The biometric gate is native-only, and off in this batch anyway
    /// (IOS-1). A Keycloak session already sits behind the saved-password
    /// item's own `.biometryCurrentSet`, and stacking a second face prompt
    /// on top of it protects nothing new.
    var canGate: Bool { self == .native }
}

/// The signed-in session, as this phone keeps it.
///
/// Everything here is a credential or names one, which is why it lives in
/// the Keychain and not in UserDefaults beside the backend URLs. The
/// access token is deliberately absent: it lives fifteen minutes, it is
/// re-mintable from the refresh token, and writing it to disk would be
/// storing a secret with none of the benefits of storing it.
///
/// Both kinds of session live here during the dual-issuer period: a native
/// refresh token and a Keycloak one are both tokens this phone holds and
/// presents in a body, and `X-Client-Type: ios` is what makes even the
/// Keycloak login hand one over rather than set a cookie
/// (`routers/login.py:243`). `kind` is what tells them apart.
///
/// Before IDX-I1 this app stored the **password** instead, behind Face ID.
/// It still does, for Keycloak users only, because during `dual` that is
/// still their way in — see `CredentialStore`. `SessionMigration` deletes
/// it when IDX-A4/A5 move them.
struct StoredSession: Equatable, Sendable {
    var refreshToken: String
    var refreshExpiresAt: Date
    var identityId: String
    var email: String
    var lastTenantId: String?

    var isExpired: Bool { refreshExpiresAt <= Date() }

    /// Read off the token itself, so a stored record and the token in it
    /// can never disagree.
    var kind: SessionKind { SessionKind(refreshToken: refreshToken) }
}

/// What the Keychain item actually holds.
///
/// `token` is the refresh token in the clear when the gate is off, and the
/// base64 of an AES-GCM sealed box when it is on. Everything else stays
/// readable either way: at boot the app has to know whether there is a
/// session, whose it is and whether it has expired **before** it can ask
/// for Face ID, and none of those fields is a secret.
struct SessionRecord: Codable, Equatable, Sendable {
    var token: String
    var gated: Bool = false
    /// Which issuer minted the token. Stored in the clear alongside the
    /// address and the expiry, and for the same reason: with the gate on
    /// the token itself is unreadable until a face opens it, and the app
    /// has to know at boot whether to arm the keepalive — before it can
    /// put a prompt on screen. Defaults to `.native` for an item written
    /// before this field existed, which is what every such item is.
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
    /// The gate item is gone — biometry was re-enrolled, or the passcode
    /// was removed. The session cannot be read again, ever.
    case gateLost
    /// The item is there, the key is there, and the bytes still will not
    /// open: the wrong key, or a tampered item.
    case undecipherable
    /// The gate was asked for on a session that cannot carry one — a
    /// Keycloak session, during the dual-issuer period.
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

/// Where the session bytes actually go. One implementation in the app
/// (the Keychain), another in the tests — the session logic is worth
/// exercising without a Keychain to depend on.
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

/// The optional biometric gate: a random 32-byte key in its own Keychain
/// item, created with `.biometryCurrentSet` so that re-enrolling a face or
/// finger destroys it — and with it the readability of the refresh token.
///
/// The key is a separate item from the session on purpose. The session has
/// to be readable after the first unlock (an upload that finishes while
/// the phone is in a pocket still has to refresh); the gate key must not
/// be readable without a face. Two accessibility classes cannot live on
/// one item, so they live on two.
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
        // `.biometryCurrentSet` is the point of the gate: re-enrolling a
        // face or a finger destroys the key, and with it the readability
        // of the refresh token. A phone with no biometry enrolled cannot
        // hold such an item at all, so there the gate falls back to
        // `.userPresence` — the passcode (IDX-I1 J).
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
                // `.biometryCurrentSet` invalidated the item: the face or
                // finger that could open it is no longer enrolled.
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
    private let gate: SessionGateKeyring
    /// Read once, then kept: every authorised request that needs a refresh
    /// would otherwise go to the Keychain first.
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

    /// Who the stored session belongs to and whether it is gated. Never
    /// prompts; nil when there is no session.
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

    /// Which issuer minted the stored session. Nil when there is none.
    /// Never prompts: the field is in the clear precisely so the keepalive
    /// decision can be made before any face prompt (see `SessionRecord`).
    var kind: SessionKind? { record()?.kind }

    /// True when the refresh token can be read right now.
    var isUnlocked: Bool {
        guard let record = record() else { return false }
        return !record.gated || gateKey != nil
    }

    // ── the token itself ─────────────────────────────────────────────

    /// The session, decrypted. Throws `.locked` when the gate is on and
    /// this launch has not been unlocked, `.gateLost` when the key is gone
    /// for good.
    func load() throws -> StoredSession? {
        guard let record = record() else { return nil }
        let token = try open(record)
        return StoredSession(refreshToken: token,
                             refreshExpiresAt: record.refreshExpiresAt,
                             identityId: record.identityId,
                             email: record.email,
                             lastTenantId: record.lastTenantId)
    }

    /// Show the biometric prompt and keep the key for this launch.
    ///
    /// `.gateLost` wipes the session on the way out: an item nothing can
    /// ever open again is not a session, and leaving it there would make
    /// every later launch ask for a face that no longer works.
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
        // Signing in again on a phone whose owner asked for the gate must
        // not quietly turn it off. If the gate item is there but this
        // launch holds no key — the usual case, since signing out drops it
        // — mint a fresh one rather than prompting: the key that is being
        // replaced protected a session that no longer exists.
        //
        // A Keycloak session is the exception: it cannot be gated (see
        // `SessionKind.canGate`), so an existing gate key is left alone —
        // untouched, not destroyed, because the next native sign-in on
        // this phone should still find the gate the owner asked for.
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
        // The issuer follows the token, not the record it replaces. A
        // rotation should never change it, but if a deployment flips mode
        // under a live session the phone must believe the token it is
        // actually holding — that is what decides the keepalive.
        record.kind = SessionKind(refreshToken: refreshToken)
        record.token = try seal(refreshToken, gated: record.gated)
        record.refreshExpiresAt = expiresAt
        if let tenantId { record.lastTenantId = tenantId }
        try write(record)
    }

    /// Remember which workspace the session is in, without touching the
    /// token. `POST /auth/token` rotates nothing, so neither does this.
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

    /// Turn the gate on or off, re-writing the session item either way.
    ///
    /// Turning it on needs the token in the clear right now, which is why
    /// it can only be done from a signed-in, unlocked app. Turning it off
    /// destroys the key first: a key nothing references is a key that
    /// should not survive the switch being flipped.
    func setGate(enabled: Bool) async throws {
        guard var record = record() else {
            // Not signed in: still honour the switch, so the preference is
            // in force by the time there is a session to protect.
            if enabled {
                gateKey = try gate.create()
            } else {
                gate.destroy()
                gateKey = nil
            }
            return
        }
        guard record.kind.canGate else {
            // A Keycloak session has no native refresh token to seal, so
            // there is nothing to gate: its way back in is the saved
            // password, which carries a face of its own. Turning the gate
            // *on* is reported rather than silently ignored, so the toggle
            // does not sit there looking as though it worked. Turning it
            // *off* is honoured — de-escalation should never be refused,
            // and the key it drops belonged to a session that is gone.
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
            // Unreadable (an older shape, a truncated write): treat it as no
            // session rather than leaving a value nothing can use.
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
    /// ISO-8601 dates, so the item stays readable by eye when something
    /// goes wrong.
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

    /// A passcode will do when there is no biometry to enrol against — the
    /// gate item is created with `kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly`,
    /// so a phone with no passcode at all cannot hold one.
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

    /// Delete any `mdx_rt` cookie left in the shared store.
    ///
    /// Before IDX-I1 the refresh token lived here — on disk, attached
    /// automatically to every request to the auth host. The app no longer
    /// uses cookie storage at all (`URLSession` is built with none), so a
    /// cookie left behind would be a credential nothing reads and nobody
    /// rotates. Returns how many were removed.
    @discardableResult
    static func purge(from storage: HTTPCookieStorage = .shared) -> Int {
        let stale = (storage.cookies ?? []).filter { $0.name == name }
        for cookie in stale { storage.deleteCookie(cookie) }
        return stale.count
    }
}

/// The password vault, and the one place its service string is written.
///
/// IDX-I1 retired it; IOS-1 un-retired it for the dual-issuer period,
/// because a Keycloak user's password is still their way in (ADR-0047) and
/// `CredentialStore` is what reads and writes it. What survives here is
/// `purge()` — the delete side — which is called by `SessionMigration`
/// only once IDX-A4/A5 have moved these users onto native sessions and
/// there is no longer a password worth keeping.
enum LegacyCredentials {
    static let service = "ai.notes.capture.credentials"

    /// Whether the old item is still there. Does not prompt: the query is
    /// told to fail rather than show UI, and "would need UI" means "exists".
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

    /// Delete every item under the old service. Deleting a biometry-bound
    /// item does not need the biometry, which is the whole reason this can
    /// run unattended at launch.
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

/// The one-time cut-over from the password vault to a device session.
///
/// **Held back during `dual`.** The cut-over this was written for deletes
/// the saved password, and during the dual-issuer period that password is
/// still how every pre-existing user signs in: running it now would log
/// them out of their own phone in the release that was supposed to add
/// email codes. So this batch cleans up only the refresh **cookie** — a
/// credential nothing in this app has read since IDX-I1, because even the
/// Keycloak login hands a native client its token in the body — and leaves
/// the password alone.
///
/// `purgeCredentials` stays a parameter, defaulted to a no-op, so that
/// IDX-A4/A5 turns this back on by changing one default rather than by
/// rewriting a migration under a user's live session.
enum SessionMigration {
    static let key = "sessionMigrationV1"

    /// Runs once per install. Returns the notice to show on the sign-in
    /// screen, or nil when there was nothing worth telling anybody about
    /// — which, during `dual`, is every case: a purged cookie is not news.
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
