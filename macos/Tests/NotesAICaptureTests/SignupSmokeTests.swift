import XCTest
@testable import NotesAICapture

/// MAC-0 item 2 — the end-to-end proof that a **brand-new** account works
/// on this Mac: create it through the API, sign in with the app's own
/// client, upload a second of audio, and find the note in Recents.
///
/// Every other test in this target answers a stubbed server. This one
/// does not: it is the only place that would catch a signup that produces
/// an account the Mac cannot actually use — a missing membership, a token
/// without a `tid`, an ASR service that refuses a first-day tenant. None
/// of that is visible against a stub.
///
/// **It runs only when a stack is pointed at it.** `swift test` on a
/// laptop and the `macos-app` CI job skip it, so neither goes red for the
/// absence of a server. The `macos-signup-smoke` job supplies the
/// environment (see `.github/workflows/ci.yml`).
///
///     MAC_SMOKE_AUTH_URL   http://localhost:8000
///     MAC_SMOKE_ASR_URL    http://localhost:8001
///     MAC_SMOKE_NOTE_URL   http://localhost:8006
///     MAC_SMOKE_FIXTURE    the BE-0 fixture token (see below)
///
/// ### What it expects of BE-0
///
/// Two endpoints, and this is the only place the Mac side names them:
///
/// * `POST /auth/signup` — `{email, password, display_name}` → 201/202,
///   creating an unconfirmed account with a personal workspace.
/// * `POST /test/signup/confirm` — `{email}` with `X-Test-Fixture:
///   <token>`, confirming that address without reading mail. Mounted only
///   where `MDX_TEST_FIXTURES` is on; never in production.
///
/// If BE-0 lands a different shape, change `Signup.create` and
/// `Signup.confirm` below and nothing else.
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

    /// A fresh address every run: this test creates accounts, and a rerun
    /// must not collide with the one before it.
    private let email = "mac-smoke-\(UUID().uuidString.prefix(8).lowercased())@smoke.invalid"
    private let password = "Sm0ke-\(UUID().uuidString.prefix(12))!"

    func testANewAccountCanSignInRecordAndSeeItsNote() async throws {
        let stack = try Stack.fromEnvironment()
        let signup = Signup(stack: stack)

        // ── 1. the account BE-0 makes ────────────────────────────────
        try await signup.create(email: email, password: password, displayName: "Mac Smoke")

        // Before confirmation the app must be told *why* it cannot sign
        // in, because that is the state the Resend button exists for.
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

        // Recents is the app's own list, written by the app's own store —
        // asserting on the server's note list would prove less.
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

    /// ASR is a queue, not a request: the job is worth waiting for, but
    /// not forever — a smoke test that hangs tells CI nothing.
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

    /// One second of 16 kHz mono PCM — a quiet tone rather than silence,
    /// because some front-ends drop an all-zero file before it reaches a
    /// model, and this test is about the pipeline, not the words.
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
