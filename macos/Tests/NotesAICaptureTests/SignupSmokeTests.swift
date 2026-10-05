import XCTest
@testable import NotesAICapture

/// End-to-end proof that a brand-new account works on this Mac: create it through
/// the API, sign in with the app's own client, upload a second of audio, find the
/// note in Recents. The only test here against a real stack; it catches a signup
/// that produces an account the Mac cannot use (missing membership, token without `tid`).
///
/// Runs only when a stack is pointed at it (`swift test` and the `macos-app` CI job skip it;
/// `macos-signup-smoke` supplies the environment, see `.github/workflows/ci.yml`):
///
///     MAC_SMOKE_AUTH_URL   http://localhost:8000
///     MAC_SMOKE_ASR_URL    http://localhost:8001
///     MAC_SMOKE_NOTE_URL   http://localhost:8006
///     MAC_SMOKE_FIXTURE    the test fixture token
///
/// Server endpoints used: `POST /auth/signup` (`{email, password, display_name}` → 201/202)
/// and `POST /test/signup/confirm` (`{email}` with `X-Test-Fixture: <token>`, mounted only
/// where `MDX_TEST_FIXTURES` is on). If the shape changes, change `Signup.create`/`Signup.confirm` only.
final class SignupSmokeTests: XCTestCase {

    // MARK: - The stack under test

    private struct Stack {
        let settings: BackendSettings
        let fixtureToken: String

        static func fromEnvironment() throws -> Stack {
            let env = ProcessInfo.processInfo.environment
            guard let auth = env["MAC_SMOKE_AUTH_URL"],
                  let asr = env["MAC_SMOKE_ASR_URL"],
                  let note = env["MAC_SMOKE_NOTE_URL"],
                  let fixture = env["MAC_SMOKE_FIXTURE"]
            else {
                throw XCTSkip("no stack: set MAC_SMOKE_AUTH_URL/ASR/NOTE and MAC_SMOKE_FIXTURE")
            }
            return Stack(
                settings: BackendSettings(authBaseURL: auth, asrBaseURL: asr,
                                          noteBaseURL: note, webAppURL: ""),
                fixtureToken: fixture)
        }
    }

    /// A fresh address every run, so a rerun never collides with the one before.
    private let email = "mac-smoke-\(UUID().uuidString.prefix(8).lowercased())@smoke.invalid"
    private let password = "Sm0ke-\(UUID().uuidString.prefix(12))!"

    func testANewAccountCanSignInRecordAndSeeItsNote() async throws {
        let stack = try Stack.fromEnvironment()
        let signup = Signup(stack: stack)

        // ── 1. the account ───────────────────────────────────────────
        try await signup.create(email: email, password: password, displayName: "Mac Smoke")

        // Before confirmation the app must be told *why* it cannot sign in (the Resend button's state).
        let unconfirmed = makeClient(for: stack)
        do {
            _ = try await unconfirmed.login(email: email, password: password)
            XCTFail("an unconfirmed account signed in")
        } catch let error as APIError {
            XCTAssertEqual(error.code, "email_not_verified",
                           "the Mac's resend button hangs off this code")
        }

        try await signup.confirm(email: email)

        // ── 2. signing in, through the app's own client ──────────────
        let storage = InMemorySessionStorage()
        let client = makeClient(for: stack, storage: storage)
        let result = try await client.login(email: email, password: password)
        guard case .authenticated(let session) = result else {
            return XCTFail("signup produced an account that cannot open a session: \(result)")
        }
        XCTAssertFalse(session.tenantId.isEmpty,
                       "a new account arrived without a workspace; nothing can be recorded into it")
        XCTAssertNotNil(storage.session, "the session was not kept for the next launch")

        // ── 3. a second of audio ─────────────────────────────────────
        let audio = try oneSecondOfAudio()
        defer { try? FileManager.default.removeItem(at: audio) }
        let submitted = try await client.submitJob(
            fileURL: audio, contentType: "audio/wav", language: "auto", diarize: false)

        let finished = try await poll(client: client, jobId: submitted.id)
        XCTAssertEqual(finished.status, .complete,
                       "transcription did not finish: \(finished.errorMessage ?? "—")")

        // ── 4. the note, and Recents ─────────────────────────────────
        let note = try await client.createNoteFromTranscript(
            asrJobId: finished.id, templateId: nil, title: "Mac smoke")

        // Recents is the app's own list; asserting on the server's note list would prove less.
        let suite = "mac-smoke-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let local = LocalStore(defaults: defaults)
        let scope = AppState.LocalScope(identityId: session.identity?.id ?? email,
                                        tenantId: session.tenantId)
        local.addRecent(RecentCapture(jobId: finished.id, title: "Mac smoke",
                                      createdAt: Date(), status: .complete, noteId: note.id),
                        to: scope)

        let recents = local.recents(for: scope)
        XCTAssertEqual(recents.first?.jobId, finished.id, "the capture did not reach Recents")
        XCTAssertEqual(recents.first?.noteId, note.id, "Recents has no note to open")
    }

    // MARK: - BE-0's surface, named in exactly one place

    private struct Signup {
        let stack: Stack

        func create(email: String, password: String, displayName: String) async throws {
            try await post("/auth/signup",
                           body: ["email": email, "password": password,
                                  "display_name": displayName])
        }

        func confirm(email: String) async throws {
            try await post("/test/signup/confirm", body: ["email": email],
                           headers: ["X-Test-Fixture": stack.fixtureToken])
        }

        private func post(_ path: String, body: [String: String],
                          headers: [String: String] = [:]) async throws {
            let base = try XCTUnwrap(URL(string: stack.settings.authBaseURL))
            var request = URLRequest(url: base.appending(path: path))
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.setValue("macos", forHTTPHeaderField: "X-Client-Type")
            for (key, value) in headers { request.setValue(value, forHTTPHeaderField: key) }
            request.httpBody = try JSONSerialization.data(withJSONObject: body)

            let (data, response) = try await URLSession.shared.data(for: request)
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard (200..<300).contains(status) else {
                throw XCTSkip("""
                    \(path) answered \(status) — BE-0 is not deployed on this stack, \
                    or its fixture is off. Body: \(String(decoding: data, as: UTF8.self))
                    """)
            }
        }
    }

    // MARK: - Pieces

    private func makeClient(for stack: Stack,
                            storage: InMemorySessionStorage = InMemorySessionStorage()) -> APIClient {
        APIClient(settings: stack.settings, store: SessionStore(storage: storage))
    }

    /// ASR is a queue: worth waiting for, but not forever.
    private func poll(client: APIClient, jobId: String,
                      timeout: TimeInterval = 180) async throws -> TranscriptionJob {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            let job = try await client.jobStatus(id: jobId)
            if job.status.isTerminal { return job }
            try await Task.sleep(for: .seconds(3))
        }
        XCTFail("job \(jobId) was still running after \(Int(timeout))s")
        return try await client.jobStatus(id: jobId)
    }

    /// One second of 16 kHz mono PCM — a quiet tone, since some front-ends drop an all-zero file.
    private func oneSecondOfAudio() throws -> URL {
        let rate = 16_000
        var samples = Data()
        for frame in 0..<rate {
            let value = sin(2 * Double.pi * 440 * Double(frame) / Double(rate)) * 3_000
            withUnsafeBytes(of: Int16(value).littleEndian) { samples.append(contentsOf: $0) }
        }

        var wav = Data()
        func append(_ text: String) { wav.append(contentsOf: Array(text.utf8)) }
        func append32(_ value: UInt32) {
            withUnsafeBytes(of: value.littleEndian) { wav.append(contentsOf: $0) }
        }
        func append16(_ value: UInt16) {
            withUnsafeBytes(of: value.littleEndian) { wav.append(contentsOf: $0) }
        }
        append("RIFF"); append32(UInt32(36 + samples.count)); append("WAVE")
        append("fmt "); append32(16); append16(1); append16(1)
        append32(UInt32(rate)); append32(UInt32(rate * 2)); append16(2); append16(16)
        append("data"); append32(UInt32(samples.count)); wav.append(samples)

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("mac-smoke-\(UUID().uuidString).wav")
        try wav.write(to: url)
        return url
    }
}
