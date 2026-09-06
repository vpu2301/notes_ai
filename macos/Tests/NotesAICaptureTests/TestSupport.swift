import Foundation
import XCTest
@testable import NotesAICapture

// MARK: - A session store that is not the Keychain

/// The Keychain is the app's storage; a test binary has no app identity to
/// key items to and would leave real items behind if it did. The store's
/// own behaviour (cache, rotate, clear) is what these tests are about.
final class InMemorySessionStorage: SessionStorage, @unchecked Sendable {
    private let lock = NSLock()
    private var data: Data?
    /// Set to make every write fail, as a locked Keychain would.
    var writeStatus: OSStatus = errSecSuccess
    private(set) var writes = 0
    private(set) var deletes = 0

    init(seed: StoredSession? = nil) {
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

    var session: StoredSession? {
        read().flatMap { try? JSONDecoder.session.decode(StoredSession.self, from: $0) }
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

    /// A JSON array — `GET /auth/sessions` answers one.
    static func json(_ array: [[String: Any]]) -> Data {
        try! JSONSerialization.data(withJSONObject: array)
    }

    /// An `AuthResult` for a native client: the refresh token is in the body.
    static func authenticated(refreshToken: String = "rt-1",
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

    static func storedSession(refreshToken: String = "rt-0",
                              expiresIn: TimeInterval = 2_592_000) -> StoredSession {
        StoredSession(
            refreshToken: refreshToken,
            refreshExpiresAt: Date().addingTimeInterval(expiresIn),
            identityId: "22222222-2222-2222-2222-222222222222",
            email: "olena@acme.example",
            lastTenantId: "11111111-1111-1111-1111-111111111111")
    }
}

extension XCTestCase {
    /// An `APIClient` wired to the stub server and an in-memory session.
    func makeClient(storage: InMemorySessionStorage) -> APIClient {
        APIClient(settings: .default,
                  store: SessionStore(storage: storage),
                  configuration: StubServer.configuration())
    }
}
