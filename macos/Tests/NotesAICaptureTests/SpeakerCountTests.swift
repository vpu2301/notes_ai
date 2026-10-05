import XCTest
@testable import NotesAICapture

/// The speaker-count hint on capture, "Wrong number of speakers?" and the low-confidence banner.
final class SpeakerCountTests: XCTestCase {
    private var directory: URL!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory
            .appending(path: "pending-s29-\(UUID().uuidString)")
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: directory)
    }

    // MARK: - The pending-capture sidecar

    func testASidecarWrittenBeforeTheHintStillDecodes() throws {
        let json = """
        {"title":"Weekly sync","language":"auto","diarize":true,
         "recorded_at":"2026-09-01T09:00:00Z","identity_id":"id-1","tenant_id":"t-1"}
        """
        let info = try JSONDecoder.pending.decode(PendingCapture.Info.self, from: Data(json.utf8))
        XCTAssertEqual(info.title, "Weekly sync")
        XCTAssertNil(info.speakersExpected, "an old recording uploads with no hint, as it was made")
    }

    func testAnOldSidecarOnDiskIsStillListed() throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let audio = directory.appending(path: "old.flac")
        try Data("audio".utf8).write(to: audio)
        try Data("""
        {"title":"Old","language":"auto","diarize":true,
         "recorded_at":"2026-09-01T09:00:00Z","identity_id":"id-1"}
        """.utf8).write(to: audio.deletingPathExtension().appendingPathExtension("json"))

        let all = PendingCaptures.all(in: directory)
        XCTAssertEqual(all.map(\.info.title), ["Old"])
        XCTAssertNil(all.first?.info.speakersExpected)
    }

    func testTheHintIsKeptWithAnOfflineCapture() throws {
        let recording = FileManager.default.temporaryDirectory.appending(path: "\(UUID().uuidString).flac")
        try Data("audio".utf8).write(to: recording)
        let info = PendingCapture.Info(title: "Board call", language: "auto", diarize: true,
                                       recordedAt: Date(timeIntervalSince1970: 1_757_000_000),
                                       identityId: "id-1", tenantId: "t-1", speakersExpected: 3)

        let kept = try XCTUnwrap(PendingCaptures.keep(recording, info: info, in: directory))
        let object = try JSONSerialization.jsonObject(
            with: Data(contentsOf: kept.deletingPathExtension().appendingPathExtension("json"))) as! [String: Any]

        XCTAssertEqual(object["speakers_expected"] as? Int, 3)
        XCTAssertEqual(PendingCaptures.all(in: directory).first?.info.speakersExpected, 3)
    }

    // MARK: - The "People" choice

    func testOnlyAnExactNumberBecomesAHint() {
        XCTAssertNil(PeopleCount.auto.speakersExpected)
        XCTAssertNil(PeopleCount.sixPlus.speakersExpected, "6+ leaves the count to the diarizer")
        XCTAssertEqual(PeopleCount.three.speakersExpected, 3)
        XCTAssertEqual(PeopleCount.allCases.map(\.label), ["Auto", "1", "2", "3", "4", "5", "6+"])
    }

    // MARK: - Requests

    func testTheUploadCarriesTheHintOnlyWhenOneWasPicked() {
        let none = APIClient.jobFields(language: "auto", diarize: true, speakersExpected: nil)
        XCTAssertFalse(none.contains { $0.0 == "speakers_expected" })
        let three = APIClient.jobFields(language: "auto", diarize: true, speakersExpected: 3)
        XCTAssertTrue(three.contains { $0 == ("speakers_expected", "3") })
    }

    func testTheHintGoesOutAsAMultipartField() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (202, Fixtures.json(["id": "job-1", "status": "queued", "hints_applied": true]), [:])
        }
        let recording = FileManager.default.temporaryDirectory.appending(path: "\(UUID().uuidString).flac")
        try Data("audio".utf8).write(to: recording)
        defer { try? FileManager.default.removeItem(at: recording) }

        let job = try await client.submitJob(fileURL: recording, contentType: "audio/flac",
                                             language: "auto", diarize: true, speakersExpected: 2)
        let body = String(decoding: StubServer.requests(to: "/asr/jobs").first?.body ?? Data(), as: UTF8.self)
        XCTAssertTrue(body.contains("name=\"speakers_expected\"\r\n\r\n2\r\n"))
        XCTAssertEqual(job.hintsApplied, true)

        _ = try await client.submitJob(fileURL: recording, contentType: "audio/flac",
                                       language: "auto", diarize: true)
        let plain = String(decoding: StubServer.requests(to: "/asr/jobs").last?.body ?? Data(), as: UTF8.self)
        XCTAssertFalse(plain.contains("speakers_expected"), "Auto sends nothing")
    }

    func testARelabelAlwaysSaysTheCountEvenWhenItIsNull() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (202, Fixtures.json(["job_id": "j1", "diarization_status": "queued", "diarization_rev": 1]), [:])
        }

        let accepted = try await client.rediarize(jobId: "j1", speakersExpected: 2)
        _ = try await client.rediarize(jobId: "j1", speakersExpected: nil)

        let sent = StubServer.requests(to: "/asr/jobs/j1/rediarize")
        XCTAssertEqual(sent.map(\.method), ["POST", "POST"])
        XCTAssertEqual(sent[0].json()["speakers_expected"] as? Int, 2)
        XCTAssertTrue(sent[1].json()["speakers_expected"] is NSNull, "null = let the diarizer decide")
        XCTAssertEqual(accepted.diarizationStatus, "queued")
    }

    func testUndoPostsToItsOwnPath() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (409, Fixtures.json(["title": "Conflict", "status": 409, "detail": "x",
                                       "code": "nothing_to_undo"]), [:])
        }
        do {
            _ = try await client.undoRediarize(jobId: "j1")
            XCTFail("a second undo is refused")
        } catch {
            XCTAssertEqual(error as? RediarizeError, .nothingToUndo)
        }
        XCTAssertEqual(StubServer.requests(to: "/asr/jobs/j1/rediarize/undo").first?.method, "POST")
    }

    func testRefusalsBecomeTypedErrors() {
        func http(_ status: Int, _ code: String) -> Error {
            APIError.http(status: status, problem: Problem(title: nil, detail: "x", status: status, code: code))
        }
        XCTAssertEqual(RediarizeError.from(http(409, "rediarize_in_progress")) as? RediarizeError, .inProgress)
        XCTAssertEqual(RediarizeError.from(http(409, "audio_unavailable")) as? RediarizeError, .audioUnavailable)
        XCTAssertEqual(RediarizeError.from(http(429, "rediarize_limit")) as? RediarizeError, .limitReached)
        XCTAssertEqual(RediarizeError.from(http(429, "rate_limited")) as? RediarizeError, .rateLimited)
        XCTAssertEqual(RediarizeError.from(http(503, "enqueue_failed")) as? RediarizeError, .enqueueFailed)
        XCTAssertNil(RediarizeError.from(http(409, "something_else")) as? RediarizeError)
    }

    // MARK: - Decoding

    func testJobAndResultFieldsDecodeAndOlderServersStillDo() throws {
        let job = try JSONDecoder().decode(TranscriptionJob.self, from: Data("""
        {"id":"j1","status":"complete","diarization_rev":2,"diarization_status":"running",
         "diarization_error":null,"diarization_runs":1,"can_undo_rediarize":true}
        """.utf8))
        XCTAssertTrue(job.isRelabelling)
        XCTAssertEqual(job.diarizationRuns, 1)
        XCTAssertEqual(job.canUndoRediarize, true)

        let old = try JSONDecoder().decode(TranscriptionJob.self,
                                           from: Data(#"{"id":"j1","status":"complete"}"#.utf8))
        XCTAssertNil(old.diarizationStatus)
        XCTAssertFalse(old.isRelabelling)

        let result = try JSONDecoder().decode(TranscriptResult.self, from: Data("""
        {"job_id":"j1","segments":[],"speakers":["SPEAKER_1"],"count_confidence":"low","speakers_hint":3}
        """.utf8))
        XCTAssertEqual(result.countConfidence, "low")
        XCTAssertEqual(result.speakersHint, 3)
    }

    // MARK: - The banner and the re-label (view model)

    func testTheCountBannerRules() {
        XCTAssertTrue(NoteViewModel.showsCountBanner(confidence: "low", hint: nil, dismissed: false, relabelling: false))
        XCTAssertFalse(NoteViewModel.showsCountBanner(confidence: "high", hint: nil, dismissed: false, relabelling: false))
        XCTAssertFalse(NoteViewModel.showsCountBanner(confidence: nil, hint: nil, dismissed: false, relabelling: false))
        XCTAssertFalse(NoteViewModel.showsCountBanner(confidence: "low", hint: 3, dismissed: false, relabelling: false),
                       "the person already said how many")
        XCTAssertFalse(NoteViewModel.showsCountBanner(confidence: "low", hint: nil, dismissed: true, relabelling: false))
        XCTAssertFalse(NoteViewModel.showsCountBanner(confidence: "low", hint: nil, dismissed: false, relabelling: true))
    }

    /// Two speakers, one of whom barely spoke.
    private static func result(confidence: String?, speakers: [String] = ["SPEAKER_1", "SPEAKER_2"],
                               hint: Int? = nil, edits: Int = 0) -> Data {
        var object: [String: Any] = [
            "job_id": "j1", "segments": [], "turns": [
                ["speaker": "SPEAKER_1", "start_ms": 0, "end_ms": 1000, "paragraphs": ["Hi"]],
            ],
            "speakers": speakers,
            "speaker_names": Dictionary(uniqueKeysWithValues: speakers.map { ($0, $0) }),
            "speaker_stats": [
                ["label": "SPEAKER_1", "speech_ms": 300_000, "share": 0.97, "turns": 4],
                ["label": "SPEAKER_2", "speech_ms": 7_000, "share": 0.03, "turns": 1],
            ].filter { speakers.contains($0["label"] as! String) },
            "edits": (0..<edits).map { ["id": "e\($0)", "kind": "merge"] },
        ]
        object["count_confidence"] = confidence ?? NSNull()
        object["speakers_hint"] = hint ?? NSNull()
        return Fixtures.json(object)
    }

    @MainActor
    func testTheCountBannerTakesPrecedenceOverTheSmallSpeakerPrompt() async throws {
        let jobId = "job-\(UUID().uuidString)"
        defer { UserDefaults.standard.removeObject(forKey: NoteViewModel.countBannerKey(jobId)) }
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh": return (200, Fixtures.authenticated(), [:])
            case "/asr/jobs/\(jobId)/result": return (200, Self.result(confidence: "low", edits: 2), [:])
            default: return (200, Fixtures.json(["id": jobId, "status": "complete"]), [:])
            }
        }
        let model = NoteViewModel(noteId: "n1", jobId: jobId,
                                  api: makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession())))
        await model.loadTranscript()

        XCTAssertTrue(model.showsCountBanner)
        XCTAssertNil(model.smallSpeakerPrompt, "never both banners")
        XCTAssertEqual(model.relabelReplacesMerges, "Your 2 merges will be replaced by the new result.")

        model.dismissCountBanner()
        XCTAssertFalse(model.showsCountBanner)
        XCTAssertEqual(model.smallSpeakerPrompt?.speaker.label, "SPEAKER_2", "now the Sprint 28 question")

        // "Looks right" is remembered for this job.
        let reopened = NoteViewModel(noteId: "n1", jobId: jobId,
                                     api: makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession())))
        await reopened.loadTranscript()
        XCTAssertFalse(reopened.showsCountBanner)
    }

    @MainActor
    func testARelabelIsPolledUntilItSettlesAndTheResultReloads() async throws {
        let polls = StatusReads()
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/asr/jobs/j1/rediarize":
                return (202, Fixtures.json(["job_id": "j1", "diarization_status": "queued", "diarization_rev": 1]), [:])
            case "/asr/jobs/j1/result":
                // Before the re-run: one speaker. After: the three asked for.
                return (200, polls.value < 2
                        ? Self.result(confidence: "low", speakers: ["SPEAKER_1"])
                        : Self.result(confidence: "high", speakers: ["SPEAKER_1", "SPEAKER_2"], hint: 3), [:])
            case "/asr/jobs/j1":
                let n = request.method == "GET" ? polls.next() : 0
                // The first status read is the one loadTranscript makes.
                let status = n <= 1 ? "running" : "complete"
                return (200, Fixtures.json(["id": "j1", "status": "complete",
                                            "diarization_status": n == 0 ? "complete" : status,
                                            "can_undo_rediarize": n >= 2]), [:])
            default:
                return (404, Data(), [:])
            }
        }
        let model = NoteViewModel(noteId: "n1", jobId: "j1",
                                  api: makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession())))
        model.relabelPollInterval = .milliseconds(10)
        await model.loadTranscript()
        XCTAssertEqual(model.relabel, .idle)

        await model.relabelSpeakers(expected: 3)
        XCTAssertEqual(model.relabel, .running)
        XCTAssertNil(model.smallSpeakerPrompt)

        let deadline = Date().addingTimeInterval(5)
        while model.relabel == .running, Date() < deadline {
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTAssertEqual(model.relabel, .done(speakers: 2))
        XCTAssertTrue(model.canUndoRelabel)
        XCTAssertEqual(model.speakersHint, 3)
        XCTAssertEqual(model.hintShortfall, "Only 2 voices could be told apart.")
        XCTAssertEqual(StubServer.requests(to: "/asr/jobs/j1/rediarize").first?.json()["speakers_expected"] as? Int, 3)
    }

    @MainActor
    func testAFailedRelabelKeepsTheOldLabelsAndOffersTryAgain() async throws {
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/asr/jobs/j1/rediarize":
                return (202, Fixtures.json(["job_id": "j1", "diarization_status": "queued"]), [:])
            case "/asr/jobs/j1/result":
                return (200, Self.result(confidence: "low"), [:])
            default:
                return (200, Fixtures.json(["id": "j1", "status": "complete", "diarization_status": "failed",
                                            "diarization_error": "diarization_failed"]), [:])
            }
        }
        let model = NoteViewModel(noteId: "n1", jobId: "j1",
                                  api: makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession())))
        model.relabelPollInterval = .milliseconds(10)
        await model.loadTranscript()
        await model.relabelSpeakers(expected: 2)

        let deadline = Date().addingTimeInterval(5)
        while model.relabel == .running, Date() < deadline {
            try await Task.sleep(for: .milliseconds(20))
        }
        XCTAssertEqual(model.relabel, .failed)
        XCTAssertEqual(model.speakers, ["SPEAKER_1", "SPEAKER_2"], "the old labels stay")
    }
}

/// How many times the job's status was read (0-based), for a stub handler.
private final class StatusReads: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0

    var value: Int {
        lock.lock(); defer { lock.unlock() }
        return count
    }

    /// The reads so far, then one more.
    func next() -> Int {
        lock.lock(); defer { lock.unlock() }
        count += 1
        return count - 1
    }
}
