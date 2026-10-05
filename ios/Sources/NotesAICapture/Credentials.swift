import Foundation
import LocalAuthentication
import Security

/// The saved password, in the Keychain behind Face ID / Touch ID, for
/// Keycloak users during the dual-issuer period only (ADR-0047). Same
/// service/account/access control as before so an updated phone finds its
/// item; `LegacyCredentials.purge()` deletes it. Unreachable for a native session.
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

    /// The same service `LegacyCredentials` names, so writer and purge cannot drift apart.
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

    // `Biometrics` (SessionStore.swift) is the one reader of `LAContext`; these names are kept for the sign-in screen.
    static var biometryName: String? { Biometrics.name }
    static var biometrySymbol: String { Biometrics.symbol }

    // MARK: - The saved sign-in

    /// Whether a password is saved. Does not prompt ("would need UI" means "exists").
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

    /// Show the biometric prompt and hand back the saved sign-in; nil when none or cancelled.
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
