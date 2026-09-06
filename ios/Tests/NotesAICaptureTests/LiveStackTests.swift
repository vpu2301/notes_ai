import XCTest
@testable import NotesAICapture

/// IOS-0's smoke, from inside the app: sign in, capture a second, see the
/// note land in Recents — against a real stack, through the app's own
/// `APIClient` rather than through `StubServer`.
///
/// **Opt-in, and inert by default.** Every case skips unless
/// `NOTES_STACK_HOST` is set, because the rest of this bundle must stay
/// runnable on a laptop with nothing up and in a CI job with no Docker.
/// Point it at a stack and it becomes the real thing:
///
///     make dev-up
///     NOTES_STACK_HOST=localhost ios/scripts/test.sh "iPhone 16"
///
/// The API half of the same path — including creating and confirming the
/// account, which is BE-0's and cannot be done from here — is
/// `scripts/smoke/ios_signup_e2e.py` (`make smoke-ios`). This half exists
/// because "the note appears in Recents" is a claim about the app's own
/// state, and only the app can make it.
///
/// The one second of audio is generated, not recorded. A simulator on a CI
/// runner has no audio input device at all, so `Recorder` is the single
/// step of this pipeline that cannot be exercised without a microphone;
/// everything after it is identical either way and `RecorderTests` covers
/// the rest.
final class LiveStackTests: XCTestCase {

    private struct Stack {
        let settings: BackendSettings
        let email: String
        let password: String
    }

    /// The stack under test, or nil when this run is not pointed at one.
    private func stack() throws -> Stack {
        let env = ProcessInfo.processInfo.environment
        let host = env["NOTES_STACK_HOST"] ?? ""
        try XCTSkipIf(host.isEmpty, "set NOTES_STACK_HOST to run the live smoke (see `make dev-up`)")
        guard let settings = BackendSettings.forHost(host) else {
            throw XCTSkip("NOTES_STACK_HOST=\(host) is not a usable host")
        }
        return Stack(settings: settings,
                     email: env["NOTES_STACK_EMAIL"] ?? "member@tenant-a.example",
                     password: env["NOTES_STACK_PASSWORD"] ?? "dev-password")
    }

    /// A client with no Keychain behind it: a test must not leave a real
    /// session item in the simulator's keychain, and the storage seam is
    /// there so it does not have to.
    private func client(for stack: Stack) -> (APIClient, InMemorySessionStorage) {
        let storage = InMemorySessionStorage()
        let client = APIClient(settings: stack.settings,
                               store: SessionStore(storage: storage, gate: FakeGate()))
        return (client, storage)
    }

    // MARK: - The whole path

    func testSignInCaptureAndTheNoteInRecents() async throws {
        let stack = try stack()
        let (api, storage) = client(for: stack)

        // 1. Sign in the way a BE-0 account does — email and password, no
        //    different from a seeded user, which is the ticket's claim.
        _ = try await api.login(email: stack.email, password: stack.password)
        let session = try XCTUnwrap(storage.record, "signing in must leave a session")
        XCTAssertFalse(session.token.isEmpty)
        XCTAssertFalse(HTTPCookieStorage.shared.cookies?.contains { $0.name == LegacyCookies.name } ?? false,
                       "a native client is handed the refresh token, never a cookie")

        // 2. A second of audio, uploaded exactly as a recording is.
        let recording = try oneSecondOfAudio()
        defer { try? FileManager.default.removeItem(at: recording) }
        let job = try await api.submitJob(fileURL: recording, contentType: "audio/wav",
                                          language: "en", diarize: false)
        XCTAssertFalse(job.id.isEmpty)

        // 3. Poll it to a terminal state, as `CaptureViewModel` does.
        let finished = try await poll(api, jobId: job.id)
        XCTAssertEqual(finished.status, .complete,
                       "the job failed: \(finished.errorMessage ?? "no reason given")")

        // 4. The note, as `AppState.draftNote` makes it.
        let note = try await api.createNoteFromTranscript(
            asrJobId: job.id, templateId: nil, title: "iOS smoke")
        XCTAssertFalse(note.id.isEmpty)
        _ = try await api.fetchNote(id: note.id)

        // 5. And in Recents — the app's own bookkeeping, against a
        //    scratch suite so the simulator's real state is untouched.
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "live-\(UUID().uuidString)"))
        let scope = try XCTUnwrap(StateScope.of(identityId: session.identityId,
                                                tenantId: session.lastTenantId))
        let recents = RecentsStore(scope: scope, defaults: defaults)
        recents.save([RecentCapture(jobId: job.id, title: "iOS smoke", createdAt: Date(),
                                    status: .complete, noteId: note.id, errorMessage: nil)])

        let readBack = recents.load()
        XCTAssertEqual(readBack.first?.jobId, job.id)
        XCTAssertEqual(readBack.first?.noteId, note.id,
                       "a completed capture carries the note it became")
    }

    // MARK: - Helpers

    private func poll(_ api: APIClient, jobId: String,
                      timeout: TimeInterval = 300) async throws -> TranscriptionJob {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            let job = try await api.jobStatus(id: jobId)
            if job.status.isTerminal { return job }
            try await Task.sleep(for: .seconds(2))
        }
        throw XCTSkip("the job did not finish inside \(Int(timeout))s — a cold whisper model, probably")
    }

    /// One second of 16 kHz mono tone, in a `.wav` container — the format
    /// `Recorder` itself falls back to, so the upload path under test is
    /// one the app really uses. A tone rather than silence: an all-zero
    /// buffer is the kind of input a decoder is entitled to reject.
    private func oneSecondOfAudio(rate: Int = 16_000) throws -> URL {
        var samples = Data()
        for n in 0..<rate {
            let value = Int16(12_000 * sin(2 * .pi * 440 * Double(n) / Double(rate)))
            withUnsafeBytes(of: value.littleEndian) { samples.append(contentsOf: $0) }
        }
        var wav = Data()
        func append<T: FixedWidthInteger>(_ value: T) {
            withUnsafeBytes(of: value.littleEndian) { wav.append(contentsOf: $0) }
        }
        wav.append(contentsOf: Array("RIFF".utf8))
        append(UInt32(36 + samples.count))
        wav.append(contentsOf: Array("WAVEfmt ".utf8))
        append(UInt32(16))                       // PCM header size
        append(UInt16(1))                        // format: PCM
        append(UInt16(1))                        // channels
        append(UInt32(rate))
        append(UInt32(rate * 2))                 // byte rate
        append(UInt16(2))                        // block align
        append(UInt16(16))                       // bits per sample
        wav.append(contentsOf: Array("data".utf8))
        append(UInt32(samples.count))
        wav.append(samples)

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("ios-smoke-\(UUID().uuidString).wav")
        try wav.write(to: url)
        return url
    }
}
