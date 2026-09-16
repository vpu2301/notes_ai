import Foundation
import LocalAuthentication
import Security

/// The saved password, kept in the Keychain behind Face ID / Touch ID so a
/// Keycloak user never has to type it again.
///
/// IDX-I1 deleted this file: a native session makes a stored password
/// pointless, because a refresh token can be revoked and a password cannot.
/// IOS-1 brings it back **for the dual-issuer period only** (ADR-0047).
/// During `dual` the two issuers are live at once and existing users still
/// sign in with a Keycloak password; taking their saved password away in
/// the same release that adds email codes would be a regression they never
/// asked for, for a benefit they cannot yet have.
///
/// It is therefore deliberately unchanged from the pre-IDX-I1 version:
/// same service, same account, same access control, so a phone that
/// updates finds the item it already had. `LegacyCredentials.purge()` in
/// `SessionStore.swift` is what deletes it, and it is not called until
/// IDX-A4/A5 move these users onto native sessions.
///
/// Nothing here is reachable for a native (`nrt_`) session — see
/// `SessionKind.canSavePassword`.
enum CredentialStore {
    struct Credentials: Codable, Equatable {
        let email: String
        let password: String
    }

    enum Failure: LocalizedError {
        case keychain(OSStatus)
        case accessControl

        var errorDescription: String? {
            switch self {
            case .keychain(let status):
                let text = SecCopyErrorMessageString(status, nil) as String? ?? "code \(status)"
                return "Keychain error: \(text)"
            case .accessControl:
                return "Could not protect the password with biometrics."
            }
        }
    }

    /// The same service `LegacyCredentials` names, from the one place that
    /// owns the string: an item this app writes and an item the migration
    /// deletes must never be able to drift apart.
    static var service: String { LegacyCredentials.service }
    private static let account = "sign-in"

    private static var baseQuery: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    // MARK: - Biometrics on this device

    // `Biometrics` (SessionStore.swift) is the one reader of `LAContext`
    // in this app since IDX-I1; these are the names this file used before
    // and the sign-in screen still uses.
    static var biometryName: String? { Biometrics.name }
    static var biometrySymbol: String { Biometrics.symbol }

    // MARK: - The saved sign-in

    /// Whether a password is saved. Does not prompt: the query is told to
    /// fail rather than show UI, and "would need UI" means "exists".
    static var hasSaved: Bool {
        let context = LAContext()
        context.interactionNotAllowed = true
        var query = baseQuery
        query[kSecUseAuthenticationContext as String] = context
        let status = SecItemCopyMatching(query as CFDictionary, nil)
        return status == errSecSuccess || status == errSecInteractionNotAllowed
    }

    static func save(email: String, password: String) throws {
        delete()
        var error: Unmanaged<CFError>?
        guard let access = SecAccessControlCreateWithFlags(
            nil, kSecAttrAccessibleWhenUnlockedThisDeviceOnly, .biometryCurrentSet, &error)
        else { throw Failure.accessControl }
        let payload = try JSONEncoder().encode(Credentials(email: email, password: password))
        var attributes = baseQuery
        attributes[kSecAttrAccessControl as String] = access
        attributes[kSecValueData as String] = payload
        attributes[kSecAttrSynchronizable as String] = false
        let status = SecItemAdd(attributes as CFDictionary, nil)
        guard status == errSecSuccess else { throw Failure.keychain(status) }
    }

    /// Show the biometric prompt and hand back the saved sign-in. Nil when
    /// nothing is saved or the user cancelled / failed the check.
    static func load(reason: String) async throws -> Credentials? {
        // SecItemCopyMatching blocks its thread while the prompt is up.
        try await Task.detached(priority: .userInitiated) { () -> Credentials? in
            let context = LAContext()
            context.localizedReason = reason
            var query = baseQuery
            query[kSecReturnData as String] = true
            query[kSecMatchLimit as String] = kSecMatchLimitOne
            query[kSecUseAuthenticationContext as String] = context
            var result: AnyObject?
            let status = SecItemCopyMatching(query as CFDictionary, &result)
            switch status {
            case errSecSuccess:
                guard let data = result as? Data else { return nil }
                return try JSONDecoder().decode(Credentials.self, from: data)
            case errSecItemNotFound, errSecUserCanceled, errSecAuthFailed, errSecInteractionNotAllowed:
                return nil
            default:
                throw Failure.keychain(status)
            }
        }.value
    }

    static func delete() {
        SecItemDelete(baseQuery as CFDictionary)
    }
}
