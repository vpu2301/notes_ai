import Foundation
import LocalAuthentication
import Security

/// The saved sign-in, kept in the Keychain behind Face ID / Touch ID so
/// the password never has to be typed again. The item is created with
/// `.biometryCurrentSet`: only the biometrics enrolled at save time can
/// open it (re-enrolling a face forgets the password), and it never leaves
/// this device. Reading it is what shows the Face ID prompt.
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

    private static let service = "ai.notes.capture.credentials"
    private static let account = "sign-in"

    private static var baseQuery: [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    // MARK: - Biometrics on this device

    /// "Face ID", "Touch ID", or nil when the device has neither enrolled.
    static var biometryName: String? {
        let context = LAContext()
        guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: nil) else { return nil }
        switch context.biometryType {
        case .faceID: return "Face ID"
        case .touchID: return "Touch ID"
        case .opticID: return "Optic ID"
        default: return nil
        }
    }

    static var biometrySymbol: String {
        switch LAContext().biometryType {
        case .touchID: return "touchid"
        case .opticID: return "opticid"
        default: return "faceid"
        }
    }

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
