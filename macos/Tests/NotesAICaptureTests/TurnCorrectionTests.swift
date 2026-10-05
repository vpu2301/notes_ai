import XCTest
@testable import NotesAICapture

/// Moving turns to another speaker, resetting speaker edits, names offered from the calendar, and the capture context on upload.
final class TurnCorrectionTests: XCTestCase {
    private var directory: URL!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory
            .appending(path: "pending-s30-\(UUID().uuidString)")
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: directory)
    }

    private func client() -> APIClient {
        makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
    }

    private static func reassigned(created: String? = nil) -> Data {
        Fixtures.json([
            "job_id": "j1", "edit_id": "e9",
            "speakers": ["SPEAKER_1", "SPEAKER_2"],
            "speaker_names": ["SPEAKER_1": "Anna", "SPEAKER_2": "Speaker 2"],
            "speaker_stats": [["label": "SPEAKER_1", "speech_ms": 60_000, "share": 0.6, "turns": 3],
                              ["label": "SPEAKER_2", "speech_ms": 40_000, "share": 0.4, "turns": 2]],
            "created_label": created ?? NSNull(),
        ])
    }

    // MARK: - Requests

    func testAReassignSendsTheRevTheIndicesAndTheTarget() async throws {
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (200, Self.reassigned(created: request.json()["to"] as? String == "new" ? "SPEAKER_3" : nil), [:])
        }
        let api = client()
        let moved = try await api.reassignTurns(jobId: "j1", resultRev: 3, segmentIndices: [41, 42, 43],
                                                to: .speaker("SPEAKER_2"))
        let created = try await api.reassignTurns(jobId: "j1", resultRev: 3, segmentIndices: [41], to: .new)
        _ = try await api.reassignTurns(jobId: "j1", resultRev: 3, segmentIndices: [41], to: .unknown)

        let sent = StubServer.requests(to: "/asr/jobs/j1/speakers/reassign")
        XCTAssertEqual(sent.map(\.method), ["POST", "POST", "POST"])
        XCTAssertEqual(sent[0].json()["result_rev"] as? Int, 3)
        XCTAssertEqual(sent[0].json()["segment_indices"] as? [Int], [41, 42, 43])
        XCTAssertEqual(sent[0].json()["to"] as? String, "SPEAKER_2")
        XCTAssertEqual(sent[1].json()["to"] as? String, "new")
        XCTAssertTrue(sent[2].json()["to"] is NSNull, "Unknown is an explicit null")
        XCTAssertTrue(sent[2].json().keys.contains("to"))
        XCTAssertEqual(moved.editId, "e9")
        XCTAssertNil(moved.createdLabel)
        XCTAssertEqual(created.createdLabel, "SPEAKER_3")
    }

    func testResetPostsToItsOwnPath() async throws {
        StubServer.install { request in
            request.path == "/auth/refresh" ? (200, Fixtures.authenticated(), [:]) : (204, Data(), [:])
        }
        try await client().resetSpeakerEdits(jobId: "j1")
        XCTAssertEqual(StubServer.requests(to: "/asr/jobs/j1/speakers/edits/reset").map(\.method), ["POST"])
    }

    func testARenameSaysHowTheNameWasChosen() async throws {
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (200, Fixtures.json(["job_id": "j1", "speaker_names": ["SPEAKER_2": "Tom Berg"]]), [:])
        }
        let api = client()
        _ = try await api.setSpeakerNames(jobId: "j1", names: ["SPEAKER_2": "Tom Berg"],
                                          sources: ["SPEAKER_2": .picklist])
        _ = try await api.setSpeakerNames(jobId: "j1", names: ["SPEAKER_2": "Tom"])
        let sent = StubServer.requests(to: "/asr/jobs/j1/speakers")
        XCTAssertEqual(sent[0].json()["sources"] as? [String: String], ["SPEAKER_2": "picklist"])
        XCTAssertNil(sent[1].json()["sources"], "no sources, no key")
    }

    func testRefusalsBecomeTypedErrors() {
        func http(_ status: Int, _ code: String?) -> Error {
            APIError.http(status: status, problem: Problem(title: nil, detail: "x", status: status, code: code))
        }
        XCTAssertEqual(SpeakerEditError.from(http(409, "stale_result_rev")) as? SpeakerEditError, .staleResultRev)
        XCTAssertEqual(SpeakerEditError.from(http(422, "bad_segment_index")) as? SpeakerEditError, .badSegmentIndex)
        XCTAssertEqual(SpeakerEditError.from(http(422, "too_many_segments")) as? SpeakerEditError, .tooManySegments)
        XCTAssertEqual(SpeakerEditError.from(http(422, "too_many_speakers")) as? SpeakerEditError, .tooManySpeakers)
        XCTAssertEqual(SpeakerEditError.from(http(422, "unknown_label")) as? SpeakerEditError, .unknownLabel)
        XCTAssertEqual(SpeakerEditError.from(http(409, "rediarize_in_progress")) as? SpeakerEditError,
                       .relabelInProgress)
        XCTAssertEqual(SpeakerEditError.from(http(410, nil)) as? SpeakerEditError, .erased)
        XCTAssertTrue(APIClient.refusedNames(http(422, "name_candidates_invalid")))
        XCTAssertFalse(APIClient.refusedNames(http(422, "something_else")))
    }

    // MARK: - Decoding

    func testNewResultFieldsDecodeAndOlderServersStillDo() throws {
        let result = try JSONDecoder().decode(TranscriptResult.self, from: Data("""
        {"job_id":"j1","result_rev":3,
         "segments":[{"text":"Hi","start_ms":0,"end_ms":900,"speaker":"SPEAKER_1","artifact_index":41}],
         "turns":[{"speaker":"SPEAKER_1","name":"Anna","start_ms":0,"end_ms":900,"paragraphs":["Hi"],
                   "segment_indices":[41,42],"uncertain":true}],
         "name_candidates":["Anna Keller","Tom Berg"]}
        """.utf8))
        XCTAssertEqual(result.segments.first?.artifactIndex, 41)
        XCTAssertEqual(result.turns?.first?.segmentIndices, [41, 42])
        XCTAssertEqual(result.turns?.first?.isUncertain, true)
        XCTAssertEqual(result.turns?.first?.isMovable, true)
        XCTAssertEqual(result.nameCandidates, ["Anna Keller", "Tom Berg"])

        let old = try JSONDecoder().decode(TranscriptResult.self, from: Data("""
        {"job_id":"j1","segments":[{"text":"Hi","start_ms":0,"end_ms":900,"speaker":null}],
         "turns":[{"speaker":null,"name":null,"start_ms":0,"end_ms":900,"paragraphs":["Hi"]}]}
        """.utf8))
        XCTAssertNil(old.segments.first?.artifactIndex)
        XCTAssertEqual(old.turns?.first?.isMovable, false, "an older server's turns cannot be moved")
        XCTAssertEqual(old.turns?.first?.isUncertain, false)
        XCTAssertNil(old.nameCandidates)
    }

    // MARK: - The capture context

    func testTheInviteeCountIsACapOnlyForRealMeetings() {
        XCTAssertNil(CaptureContext.calendarEvent(attendeeCount: 0, names: []).speakersMax)
        XCTAssertNil(CaptureContext.calendarEvent(attendeeCount: 1, names: ["Anna"]).speakersMax,
                     "one invitee is not a meeting to cap")
        XCTAssertEqual(CaptureContext.calendarEvent(attendeeCount: 2, names: []).speakersMax, 2)
        XCTAssertEqual(CaptureContext.calendarEvent(attendeeCount: 5, names: []).speakersMax, 5)
        XCTAssertEqual(CaptureContext.calendarEvent(attendeeCount: 30, names: []).speakersMax, 8, "capped at 8")
        XCTAssertEqual(CaptureContext.calendarEvent(attendeeCount: 3, names: []).source, .calendarEvent)
        XCTAssertNil(CaptureContext.manual.speakersMax)
    }

    func testNamesAreCleanedCappedAndExcludeTheCurrentUser() {
        let many = (1...20).map { "Person \($0)" }
        XCTAssertEqual(CaptureContext.candidates(many).count, 12)
        XCTAssertEqual(
            CaptureContext.candidates(["  Anna   Keller ", "anna keller", "tom@acme.example", "", "Me Myself",
                                       "Bad\u{0007}Name", String(repeating: "x", count: 81)],
                                      excluding: ["me myself"]),
            ["Anna Keller", "BadName"])
    }

    func testTheUploadFieldsFollowThePolicy() {
        let context = CaptureContext.calendarEvent(attendeeCount: 3, names: ["Anna Keller", "Tom Berg"])
        let fields = APIClient.jobFields(language: "auto", diarize: true, speakersExpected: nil, context: context)
        XCTAssertTrue(fields.contains { $0 == ("speakers_max", "3") })
        XCTAssertTrue(fields.contains { $0 == ("name_candidates", #"["Anna Keller","Tom Berg"]"#) })
        XCTAssertTrue(fields.contains { $0 == ("capture_source", "calendar_event") })
        XCTAssertFalse(fields.contains { $0.0 == "speakers_expected" }, "the invitee count is never an exact count")

        // A number the person picked still goes; the server drops the max.
        let both = APIClient.jobFields(language: "auto", diarize: true, speakersExpected: 2, context: context)
        XCTAssertTrue(both.contains { $0 == ("speakers_expected", "2") })
        XCTAssertTrue(both.contains { $0 == ("speakers_max", "3") })

        // Without diarization the hints mean nothing; the source still goes.
        let plain = APIClient.jobFields(language: "auto", diarize: false, speakersExpected: nil, context: context)
        XCTAssertFalse(plain.contains { $0.0 == "speakers_max" || $0.0 == "name_candidates" })
        XCTAssertTrue(plain.contains { $0 == ("capture_source", "calendar_event") })

        let manual = APIClient.jobFields(language: "auto", diarize: true, speakersExpected: nil, context: .manual)
        XCTAssertEqual(manual.filter { $0.0 != "language" && $0.0 != "diarize" }.map(\.0), ["capture_source"])
        XCTAssertEqual(CaptureContext.upload.formFields(diarize: true).map(\.1), ["upload"])
    }

    func testARefusedNameListIsDroppedAndTheUploadRetried() async throws {
        let calls = CallCount()
        StubServer.install { request in
            if request.path == "/auth/refresh" { return (200, Fixtures.authenticated(), [:]) }
            return calls.next() == 0
                ? (422, Fixtures.json(["title": "Unprocessable", "status": 422, "detail": "x",
                                       "code": "name_candidates_invalid"]), [:])
                : (202, Fixtures.json(["id": "job-1", "status": "queued"]), [:])
        }
        let recording = FileManager.default.temporaryDirectory.appending(path: "\(UUID().uuidString).flac")
        try Data("audio".utf8).write(to: recording)
        defer { try? FileManager.default.removeItem(at: recording) }

        let job = try await client().submitJob(
            fileURL: recording, contentType: "audio/flac", language: "auto", diarize: true,
            context: .calendarEvent(attendeeCount: 3, names: ["Anna Keller"]))
        XCTAssertEqual(job.id, "job-1")
        let bodies = StubServer.requests(to: "/asr/jobs").map { String(decoding: $0.body ?? Data(), as: UTF8.self) }
        XCTAssertEqual(bodies.count, 2)
        XCTAssertTrue(bodies[0].contains("name=\"name_candidates\"\r\n\r\n[\"Anna Keller\"]\r\n"))
        XCTAssertFalse(bodies[1].contains("name_candidates"))
        XCTAssertTrue(bodies[1].contains("name=\"speakers_max\"\r\n\r\n3\r\n"), "the cap survives the retry")
    }

    func testCalendarRowsCarryTheirInvitees() {
        let start = Date().addingTimeInterval(3600)
        let google = UpcomingEvent(
            id: "g1", connectionId: "c1", accountEmail: "olena@acme.example", calendarId: "cal",
            calendarName: "Work", color: nil, title: "Planning", start: start, end: start + 1800,
            allDay: false, location: nil, meetingUrl: nil, htmlLink: nil, attendeeCount: 4,
            attendees: ["Anna Keller", "olena@acme.example", "Tom Berg", "Room 4"], organizer: nil,
            responseStatus: nil, icalUid: "g1@google.com",
            agendaLines: ["Roadmap", "Hiring"])
        let device = CalendarService.Event(id: "d1", title: "1:1", start: start + 7200, end: start + 9000,
                                           isAllDay: false, calendarColor: nil,
                                           attendeeCount: 2, attendeeNames: ["Ida"])
        let items = ComingUpItem.merge(google: [google], mac: [device])
        XCTAssertEqual(items[0].captureContext.speakersMax, 4)
        XCTAssertEqual(items[0].captureContext.nameCandidates, ["Anna Keller", "Tom Berg", "Room 4"])
        XCTAssertEqual(items[0].captureContext.inviteLine, "4 invited · names will be offered for speakers")
        XCTAssertEqual(items[1].captureContext.speakersMax, 2)
        XCTAssertEqual(items[1].captureContext.nameCandidates, ["Ida"])
        // What goes ON the note: the people and the invite's agenda. A device calendar has only the raw notes field.
        XCTAssertEqual(items[0].meetingCalendar?.agendaLines, ["Roadmap", "Hiring"])
        XCTAssertEqual(items[0].meetingCalendar?.icalUid, "g1@google.com")
        XCTAssertEqual(items[0].meetingCalendar?.source, "google")
        XCTAssertNil(items[0].meetingCalendar?.description)
        XCTAssertEqual(items[1].meetingCalendar?.source, "eventkit")
        XCTAssertNil(items[1].meetingCalendar?.agendaLines)
    }

    // MARK: - The pending-capture sidecar

    func testAnOldSidecarDecodesWithoutAContext() throws {
        let json = """
        {"title":"Weekly sync","language":"auto","diarize":true,"speakers_expected":3,
         "recorded_at":"2026-09-01T09:00:00Z","identity_id":"id-1","tenant_id":"t-1"}
        """
        let info = try JSONDecoder.pending.decode(PendingCapture.Info.self, from: Data(json.utf8))
        XCTAssertEqual(info.speakersExpected, 3)
        XCTAssertNil(info.speakersMax)
        XCTAssertNil(info.nameCandidates)
        XCTAssertNil(info.captureContext, "an old recording uploads as it was made")
    }

    func testTheContextTravelsWithAKeptCapture() throws {
        let recording = FileManager.default.temporaryDirectory.appending(path: "\(UUID().uuidString).flac")
        try Data("audio".utf8).write(to: recording)
        var info = PendingCapture.Info(title: "Planning", language: "auto", diarize: true,
                                       recordedAt: Date(timeIntervalSince1970: 1_757_000_000),
                                       identityId: "id-1", tenantId: "t-1")
        info.setCaptureContext(.calendarEvent(attendeeCount: 3, names: ["Anna Keller", "Tom Berg"]))

        let kept = try XCTUnwrap(PendingCaptures.keep(recording, info: info, in: directory))
        let object = try JSONSerialization.jsonObject(
            with: Data(contentsOf: kept.deletingPathExtension().appendingPathExtension("json"))) as! [String: Any]
        XCTAssertEqual(object["speakers_max"] as? Int, 3)
        XCTAssertEqual(object["name_candidates"] as? [String], ["Anna Keller", "Tom Berg"])
        XCTAssertEqual(object["capture_source"] as? String, "calendar_event")

        let back = try XCTUnwrap(PendingCaptures.all(in: directory).first?.info.captureContext)
        XCTAssertEqual(back.speakersMax, 3)
        XCTAssertEqual(back.nameCandidates, ["Anna Keller", "Tom Berg"])
        XCTAssertEqual(back.source, .calendarEvent)
    }

    func testAnUnknownSourceDoesNotLoseTheRecording() throws {
        let json = """
        {"title":"X","language":"auto","diarize":true,"capture_source":"teleport",
         "recorded_at":"2026-09-01T09:00:00Z","identity_id":"id-1"}
        """
        let info = try JSONDecoder.pending.decode(PendingCapture.Info.self, from: Data(json.utf8))
        XCTAssertEqual(info.captureContext?.source, .manual)
    }

    // MARK: - The rename picklist

    func testThePicklistLeavesOutNamesAlreadyGiven() {
        let names = ["SPEAKER_1": "Anna Keller", "SPEAKER_2": "Speaker 2", "SPEAKER_3": "tom berg"]
        let candidates = ["Anna Keller", "Tom Berg", "Ida Novak"]
        XCTAssertEqual(NoteViewModel.picklist(candidates: candidates, names: names, renaming: "SPEAKER_2"),
                       ["Ida Novak"])
        XCTAssertEqual(NoteViewModel.picklist(candidates: candidates, names: names, renaming: "SPEAKER_1"),
                       ["Anna Keller", "Ida Novak"], "a speaker's own name stays on its list")
        XCTAssertEqual(NoteViewModel.completions(["Anna Keller", "Ida Novak"], typed: "Speaker 2", current: "Speaker 2"),
                       ["Anna Keller", "Ida Novak"])
        XCTAssertEqual(NoteViewModel.completions(["Anna Keller", "Ida Novak"], typed: "nov", current: "Speaker 2"),
                       ["Ida Novak"])
    }

    func testSegmentIndicesAreConcatenatedOnce() {
        let turns = [
            TranscriptTurn(speaker: "SPEAKER_1", name: nil, startMs: 0, endMs: 1, paragraphs: [], segmentIndices: [41, 42]),
            TranscriptTurn(speaker: "SPEAKER_2", name: nil, startMs: 2, endMs: 3, paragraphs: [], segmentIndices: [7, 42]),
            TranscriptTurn(speaker: nil, name: nil, startMs: 4, endMs: 5, paragraphs: []),
        ]
        XCTAssertEqual(NoteViewModel.segmentIndices(of: turns), [41, 42, 7])
    }

    // MARK: - The view model

    /// A result whose turns can be moved.
    private static func result(rev: Int, secondSpeaker: String = "SPEAKER_2", edits: Int = 0) -> Data {
        Fixtures.json([
            "job_id": "j1", "segments": [], "result_rev": rev,
            "turns": [
                ["speaker": "SPEAKER_1", "start_ms": 0, "end_ms": 1000, "paragraphs": ["Hi"],
                 "segment_indices": [41, 42]],
                ["speaker": secondSpeaker, "start_ms": 2000, "end_ms": 3000, "paragraphs": ["Hello"],
                 "segment_indices": [43], "uncertain": true],
                ["speaker": "SPEAKER_1", "start_ms": 4000, "end_ms": 5000, "paragraphs": ["Bye"],
                 "segment_indices": [44]],
            ],
            "speakers": ["SPEAKER_1", "SPEAKER_2"],
            "speaker_names": ["SPEAKER_1": "Anna", "SPEAKER_2": "Speaker 2"],
            "speaker_stats": [["label": "SPEAKER_1", "speech_ms": 60_000, "share": 0.6, "turns": 2],
                              ["label": "SPEAKER_2", "speech_ms": 40_000, "share": 0.4, "turns": 1]],
            "name_candidates": ["Anna", "Tom Berg"],
            "edits": (0..<edits).map { ["id": "e\($0)", "kind": "reassign"] },
        ])
    }

    @MainActor
    func testSelectedTurnsMoveInOneCall() async throws {
        let moved = Flag()
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh": return (200, Fixtures.authenticated(), [:])
            case "/asr/jobs/j1/speakers/reassign":
                moved.set()
                return (200, Self.reassigned(), [:])
            case "/asr/jobs/j1/result":
                return (200, moved.value ? Self.result(rev: 4, edits: 1) : Self.result(rev: 3), [:])
            default: return (200, Fixtures.json(["id": "j1", "status": "complete"]), [:])
            }
        }
        let model = NoteViewModel(noteId: "n1", jobId: "j1", api: client())
        await model.loadTranscript()
        XCTAssertTrue(model.canMoveTurns)
        XCTAssertEqual(model.nameSuggestions(for: "SPEAKER_2"), ["Tom Berg"], "Anna is taken")
        XCTAssertFalse(model.canResetSpeakerEdits)

        let turns = try XCTUnwrap(model.turns)
        model.selecting = true
        model.toggleSelection(turns[0])
        model.toggleSelection(turns[2])
        XCTAssertEqual(model.moveSelectionTitle, "Move 2 turns to")
        XCTAssertEqual(model.moveTargets(for: model.selectedTurns), ["SPEAKER_2"], "both are Anna's already")

        await model.moveTurns(model.selectedTurns, to: .speaker("SPEAKER_2"))

        let sent = StubServer.requests(to: "/asr/jobs/j1/speakers/reassign")
        XCTAssertEqual(sent.count, 1)
        XCTAssertEqual(sent[0].json()["segment_indices"] as? [Int], [41, 42, 44])
        XCTAssertEqual(sent[0].json()["result_rev"] as? Int, 3)
        XCTAssertEqual(model.lastEdit?.summary, "Moved 2 turns to Speaker 2")
        XCTAssertEqual(model.resultRev, 4)
        XCTAssertFalse(model.selecting)
        XCTAssertTrue(model.selectedTurnIds.isEmpty)
        XCTAssertTrue(model.canResetSpeakerEdits)
        XCTAssertNil(model.actionError)
    }

    @MainActor
    func testAStaleMoveReloadsAndSaysSo() async throws {
        let refused = Flag()
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh": return (200, Fixtures.authenticated(), [:])
            case "/asr/jobs/j1/speakers/reassign":
                refused.set()
                return (409, Fixtures.json(["title": "Conflict", "status": 409, "detail": "x",
                                            "code": "stale_result_rev", "current_rev": 5]), [:])
            case "/asr/jobs/j1/result":
                return (200, refused.value ? Self.result(rev: 5, secondSpeaker: "SPEAKER_1") : Self.result(rev: 3), [:])
            default: return (200, Fixtures.json(["id": "j1", "status": "complete"]), [:])
            }
        }
        let model = NoteViewModel(noteId: "n1", jobId: "j1", api: client())
        await model.loadTranscript()
        let turn = try XCTUnwrap(model.turns?[1])
        model.toggleSelection(turn)

        await model.moveTurns([turn], to: .unknown)

        XCTAssertEqual(StubServer.requests(to: "/asr/jobs/j1/speakers/reassign").first?.json()["to"].map { $0 is NSNull },
                       true)
        XCTAssertEqual(model.speakerNotice, "Speakers were updated elsewhere.")
        XCTAssertNil(model.actionError, "a conflict is not an error")
        XCTAssertEqual(model.resultRev, 5, "the fresh result is shown")
        XCTAssertEqual(model.turns?[1].speaker, "SPEAKER_1")
        XCTAssertTrue(model.selectedTurnIds.isEmpty)
        XCTAssertNil(model.lastEdit)
        XCTAssertEqual(StubServer.requests(to: "/asr/jobs/j1/speakers/reassign").count, 1, "never retried silently")
    }

    @MainActor
    func testResetUndoesEveryEditAndReloads() async throws {
        let reset = Flag()
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh": return (200, Fixtures.authenticated(), [:])
            case "/asr/jobs/j1/speakers/edits/reset":
                reset.set()
                return (204, Data(), [:])
            case "/asr/jobs/j1/result":
                return (200, Self.result(rev: 3, edits: reset.value ? 0 : 2), [:])
            default: return (200, Fixtures.json(["id": "j1", "status": "complete"]), [:])
            }
        }
        let model = NoteViewModel(noteId: "n1", jobId: "j1", api: client())
        await model.loadTranscript()
        XCTAssertTrue(model.canResetSpeakerEdits)
        await model.resetSpeakerEdits()
        XCTAssertEqual(StubServer.requests(to: "/asr/jobs/j1/speakers/edits/reset").count, 1)
        XCTAssertFalse(model.canResetSpeakerEdits)
        XCTAssertNil(model.actionError)
    }
}

/// A one-way switch a `@Sendable` stub handler can flip.
private final class Flag: @unchecked Sendable {
    private let lock = NSLock()
    private var on = false

    var value: Bool {
        lock.lock(); defer { lock.unlock() }
        return on
    }

    func set() {
        lock.lock(); defer { lock.unlock() }
        on = true
    }
}

/// How many times the stub was asked (0-based).
private final class CallCount: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0

    func next() -> Int {
        lock.lock(); defer { lock.unlock() }
        count += 1
        return count - 1
    }
}
