import CryptoKit
import Foundation
import XCTest
@testable import NotesAICapture

// MARK: - A session store that is not the Keychain

/// The Keychain is the app's storage; a test bundle would leave real items
/// behind in the simulator's keychain if it used it, and cannot show a Face
/// ID prompt to anybody. The store's own behaviour (cache, rotate, seal,
/// clear) is what these tests are about.
final class InMemorySessionStorage: SessionStorage, @unchecked Sendable {
    private let lock = NSLock()
    private var data: Data?
    /// Set to make every write fail, as a locked Keychain would.
    var writeStatus: OSStatus = errSecSuccess
    private(set) var writes = 0
    private(set) var deletes = 0

    init(seed: SessionRecord? = nil) {
        if let seed { data = try? JSONEncoder.session.encode(seed) }
    }

    func read() -> Data? {
        lock.lock(); defer { lock.unlock() }
        return data
    }

    func write(_ new: Data) -> OSStatus {
        lock.lock(); defer { lock.unlock() }
        writes += 1
        guard writeStatus == errSecSuccess else { return writeStatus }
        data = new
        return errSecSuccess
    }

    func delete() {
        lock.lock(); defer { lock.unlock() }
        deletes += 1
        data = nil
    }

    var record: SessionRecord? {
        read().flatMap { try? JSONDecoder.session.decode(SessionRecord.self, from: $0) }
    }

    /// What a reader without the gate key would find: the bytes as stored.
    var storedText: String { String(data: read() ?? Data(), encoding: .utf8) ?? "" }
}

/// A gate that answers like the Keychain's, without a face.
final class FakeGate: SessionGateKeyring, @unchecked Sendable {
    private let lock = NSLock()
    private var key: SymmetricKey?
    /// The person cancels the prompt.
    var refuses = false
    /// Biometry was re-enrolled: the item is gone for good.
    var lost = false
    private(set) var prompts = 0

    func exists() -> Bool {
        lock.lock(); defer { lock.unlock() }
        return key != nil && !lost
    }

    func create() throws -> SymmetricKey {
        lock.lock(); defer { lock.unlock() }
        let new = SymmetricKey(size: .bits256)
        key = new
        lost = false
        return new
    }

    func unlock(reason: String) async throws -> SymmetricKey {
        // The lock is taken in a synchronous call: `NSLock` must not be
        // held across a suspension point, and Swift 6 makes that an error.
        try prompt()
    }

    private func prompt() throws -> SymmetricKey {
        lock.lock(); defer { lock.unlock() }
        prompts += 1
        if lost || key == nil { throw SessionStoreError.gateLost }
        if refuses { throw SessionStoreError.locked }
        return key!
    }

    func destroy() {
        lock.lock(); defer { lock.unlock() }
        key = nil
    }

    /// Simulate re-enrolling Face ID: `.biometryCurrentSet` drops the item.
    func simulateBiometryChange() {
        lock.lock(); defer { lock.unlock() }
        lost = true
    }
}

// MARK: - A server that answers from a script

/// One `URLProtocol` for every test: it records what the app sent (which
/// is where the transport assertions live — headers, bodies, the absence
/// of a cookie) and answers from a handler the test installs.
final class StubServer: URLProtocol {
    struct Recorded: Sendable {
        let url: URL
        let method: String
        let headers: [String: String]
        let body: Data?

        var path: String { url.path }
        func json() -> [String: Any] {
            guard let body, let object = try? JSONSerialization.jsonObject(with: body) else {
                return [:]
            }
            return object as? [String: Any] ?? [:]
        }
    }

    /// The script. Returns a status, a body, and optional headers.
    typealias Handler = @Sendable (Recorded) -> (Int, Data, [String: String])

    private static let lock = NSLock()
    nonisolated(unsafe) private static var handler: Handler?
    nonisolated(unsafe) private static var recorded: [Recorded] = []

    static func install(_ handler: @escaping Handler) {
        lock.lock(); defer { lock.unlock() }
        self.handler = handler
        recorded = []
    }

    static var requests: [Recorded] {
        lock.lock(); defer { lock.unlock() }
        return recorded
    }

    static func requests(to path: String) -> [Recorded] {
        requests.filter { $0.path == path }
    }

    static func configuration() -> URLSessionConfiguration {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubServer.self]
        return config
    }

    // ── URLProtocol ──────────────────────────────────────────────────

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let recorded = Recorded(
            url: request.url!,
            method: request.httpMethod ?? "GET",
            headers: request.allHTTPHeaderFields ?? [:],
            // `URLProtocol` sees the body as a stream, never as `httpBody`.
            body: Self.bodyData(of: request))
        Self.lock.lock()
        Self.recorded.append(recorded)
        let handler = Self.handler
        Self.lock.unlock()

        guard let handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))
            return
        }
        let (status, data, headers) = handler(recorded)
        if status == 0 {
            // The test asked for a transport failure rather than a reply.
            client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet))
            return
        }
        let response = HTTPURLResponse(
            url: recorded.url, statusCode: status, httpVersion: "HTTP/1.1",
            headerFields: headers.merging(["Content-Type": "application/json"]) { a, _ in a })!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    private static func bodyData(of request: URLRequest) -> Data? {
        if let body = request.httpBody { return body }
        guard let stream = request.httpBodyStream else { return nil }
        stream.open()
        defer { stream.close() }
        var data = Data()
        let size = 4096
        let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: size)
        defer { buffer.deallocate() }
        while stream.hasBytesAvailable {
            let read = stream.read(buffer, maxLength: size)
            if read <= 0 { break }
            data.append(buffer, count: read)
        }
        return data
    }
}

// MARK: - Bodies the server would send

enum Fixtures {
    static func json(_ object: [String: Any]) -> Data {
        try! JSONSerialization.data(withJSONObject: object)
    }

    /// A top-level array — `GET /auth/sessions` answers one.
    static func json(_ array: [[String: Any]]) -> Data {
        try! JSONSerialization.data(withJSONObject: array)
    }

    /// An `AuthResult` for a native client: the refresh token is in the body.
    static func authenticated(refreshToken: String = "nrt_rt-1",
                              accessToken: String = "at-1",
                              expiresIn: Int = 900,
                              refreshExpiresIn: Int = 2_592_000,
                              email: String = "olena@acme.example",
                              isNew: Bool = false) -> Data {
        json([
            "status": "authenticated",
            "access_token": accessToken,
            "expires_in": expiresIn,
            "token_type": "Bearer",
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "roles": ["tenant_admin"],
            "refresh_token": refreshToken,
            "refresh_expires_in": refreshExpiresIn,
            "is_new_identity": isNew,
            "identity": [
                "id": "22222222-2222-2222-2222-222222222222",
                "email": email,
                "display_name": "Olena",
                "mfa_enabled": false,
                "has_password": false,
                "status": "active",
            ],
            "memberships": [[
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "name": "acme", "kind": "team", "role": "admin", "status": "active",
            ]],
            "default_tenant_id": "11111111-1111-1111-1111-111111111111",
        ])
    }

    static func mfaRequired(challengeId: String = "c-1",
                            methods: [String] = ["totp", "recovery_code"]) -> Data {
        json([
            "status": "mfa_required",
            "challenge_id": challengeId,
            "methods": methods,
            "expires_in": 300,
        ])
    }

    static func problem(_ code: String, detail: String = "no") -> Data {
        json(["title": "Unauthorized", "status": 401, "detail": detail, "code": code])
    }

    /// A Keycloak refresh token: no `nrt_` prefix, so `SessionKind` reads
    /// it as the legacy issuer's (ADR-0047). Deliberately not a realistic
    /// JWT — the discriminator this app uses is the prefix, and a test
    /// that leant on anything else would be testing a fiction.
    static let keycloakToken = "eyJhbGciOiJSUzI1NiJ9.keycloak-refresh"

    /// An ungated session item, as it sits in the Keychain.
    static func record(refreshToken: String = "nrt_rt-0",
                       expiresIn: TimeInterval = 2_592_000) -> SessionRecord {
        SessionRecord(
            token: refreshToken,
            gated: false,
            kind: SessionKind(refreshToken: refreshToken),
            refreshExpiresAt: Date().addingTimeInterval(expiresIn),
            identityId: "22222222-2222-2222-2222-222222222222",
            email: "olena@acme.example",
            lastTenantId: "11111111-1111-1111-1111-111111111111")
    }

    static func storedSession(refreshToken: String = "nrt_rt-0",
                              expiresIn: TimeInterval = 2_592_000) -> StoredSession {
        StoredSession(
            refreshToken: refreshToken,
            refreshExpiresAt: Date().addingTimeInterval(expiresIn),
            identityId: "22222222-2222-2222-2222-222222222222",
            email: "olena@acme.example",
            lastTenantId: "11111111-1111-1111-1111-111111111111")
    }
}

// MARK: - Small test helpers

/// A counter the stub's `@Sendable` handler can close over.
final class Counter: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0

    func next() -> Int {
        lock.lock(); defer { lock.unlock() }
        count += 1
        return count
    }
}

final class ReasonBox: @unchecked Sendable {
    private let lock = NSLock()
    private var reason: SessionLostReason?

    func record(_ reason: SessionLostReason) {
        lock.lock(); defer { lock.unlock() }
        self.reason = reason
    }

    var value: SessionLostReason? {
        lock.lock(); defer { lock.unlock() }
        return reason
    }
}

extension XCTestCase {
    /// An `APIClient` wired to the stub server and an in-memory session.
    func makeClient(storage: InMemorySessionStorage, gate: FakeGate = FakeGate()) -> APIClient {
        APIClient(settings: .default,
                  store: SessionStore(storage: storage, gate: gate),
                  configuration: StubServer.configuration())
    }
}
