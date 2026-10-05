import XCTest
@testable import NotesAICapture

/// Name suggestions (accept, undo, dismiss, the quote's turn), the re-label banner, the roster's spoken labels, and what a sign-out removes.
final class NameSuggestionTests: XCTestCase {
    private var directory: URL!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory
            .appending(path: "pending-s32-\(UUID().uuidString)")
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: directory)
    }

    private func client() -> APIClient {
        makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
    }

    private static let suggestion: [String: Any] = [
        "label": "SPEAKER_2", "name": "Anna Keller", "source": "self_introduction",
        "quote": "Hi, this is Anna from Acme", "start_ms": 14_000, "end_ms": 16_200,
        "segment_indices": [3],
    ]

    /// A two-speaker result; `extra` adds the suggestion fields.
    private static func result(_ jobId: String, extra: [String: Any] = [:]) -> Data {
        var object: [String: Any] = [
            "job_id": jobId, "segments": [], "result_rev": 1,
            "turns": [["speaker": "SPEAKER_1", "start_ms": 0, "end_ms": 9_000, "paragraphs": ["Welcome"],
                       "segment_indices": [0, 1, 2]],
                      ["speaker": "SPEAKER_2", "start_ms": 13_500, "end_ms": 20_000, "paragraphs": ["Hi, this is Anna"],
                       "segment_indices": [3, 4]]],
            "speakers": ["SPEAKER_1", "SPEAKER_2"],
            "speaker_names": ["SPEAKER_1": "Olena", "SPEAKER_2": "Speaker 2"],
            "speaker_stats": [["label": "SPEAKER_1", "speech_ms": 60_000, "share": 0.6, "turns": 3],
                              ["label": "SPEAKER_2", "speech_ms": 40_000, "share": 0.4, "turns": 2]],
            "speaker_name_sources": ["SPEAKER_1": "typed"],
        ]
        object.merge(extra) { _, new in new }
        return Fixtures.json(object)
    }

    /// Serves the result, echoes a PUT's names back, and takes a dismiss.
    private static func install(_ jobId: String, extra: [String: Any], dismissStatus: Int = 204) {
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/asr/jobs/\(jobId)/result":
                return (200, result(jobId, extra: extra), [:])
            case "/asr/jobs/\(jobId)/speakers":
                let names = request.json()["names"] as? [String: String] ?? [:]
                return (200, Fixtures.json(["job_id": jobId, "speaker_names": names]), [:])
            case "/asr/jobs/\(jobId)/speakers/suggestions/dismiss":
                return (dismissStatus, dismissStatus == 204 ? Data() : Fixtures.problem("boom"), [:])
            case "/asr/jobs/\(jobId)/rediarize":
                return (202, Fixtures.json(["job_id": jobId, "diarization_status": "queued", "diarization_rev": 2]), [:])
            default:
                return (200, Fixtures.json(["id": jobId, "status": "complete", "diarization_status": "complete"]), [:])
            }
        }
    }

    @MainActor
    private func loaded(_ jobId: String, extra: [String: Any], dismissStatus: Int = 204) async -> NoteViewModel {
        Self.install(jobId, extra: extra, dismissStatus: dismissStatus)
        let model = NoteViewModel(noteId: "n1", jobId: jobId, api: client())
        model.relabelPollInterval = .seconds(60)
        await model.loadTranscript()
        return model
    }

    // MARK: - Decoding

    func testSuggestionsAndTheRelabelFlagDecodeAndOlderResultsStillDo() throws {
        let result = try JSONDecoder().decode(TranscriptResult.self, from: Self.result("j1", extra: [
            "name_suggestions": [Self.suggestion, ["label": "SPEAKER_1", "name": "Olena Petrenko"]],
            "relabel_available": true,
        ]))
        let first = try XCTUnwrap(result.nameSuggestions?.first)
        XCTAssertEqual(first.label, "SPEAKER_2")
        XCTAssertEqual(first.name, "Anna Keller")
        XCTAssertEqual(first.quote, "Hi, this is Anna from Acme")
        XCTAssertEqual(first.startMs, 14_000)
        XCTAssertEqual(first.segmentIndices, [3])
        XCTAssertNil(result.nameSuggestions?.last?.quote, "a trimmed field does not cost the transcript")
        XCTAssertEqual(result.relabelAvailable, true)

        let old = try JSONDecoder().decode(TranscriptResult.self, from: Data(#"{"job_id":"j1","segments":[]}"#.utf8))
        XCTAssertNil(old.nameSuggestions)
        XCTAssertNil(old.relabelAvailable)
    }

    // MARK: - Nothing offered

    @MainActor
    func testWithoutTheFieldsNothingIsOffered() async {
        let model = await loaded("j32-none", extra: [:])
        XCTAssertTrue(model.nameSuggestions.isEmpty)
        XCTAssertNil(model.suggestion(for: "SPEAKER_2"))
        XCTAssertFalse(model.relabelAvailable)
        XCTAssertFalse(model.showsRelabelBanner)
        XCTAssertFalse(model.isSuggestedName("SPEAKER_2"))
    }

    func testOnlyOneSuggestionPerRosterSpeakerAndNeverTheSameName() {
        func s(_ label: String, _ name: String) -> NameSuggestion { NameSuggestion(label: label, name: name) }
        let visible = NoteViewModel.visibleSuggestions(
            [s("SPEAKER_2", "Anna"), s("SPEAKER_2", "Anja"), s("SPEAKER_1", "Olena"), s("SPEAKER_9", "Tom")],
            speakers: ["SPEAKER_1", "SPEAKER_2"],
            names: ["SPEAKER_1": "Olena", "SPEAKER_2": "Speaker 2"])
        XCTAssertEqual(visible.map(\.name), ["Anna"], "one per speaker, on the roster, not already its name")
    }

    // MARK: - Accept, undo, dismiss

    @MainActor
    func testAcceptPutsTheNameKeepsTheOthersAndUndoPutsThemBack() async throws {
        let model = await loaded("j32-a", extra: ["name_suggestions": [Self.suggestion]])
        let suggestion = try XCTUnwrap(model.suggestion(for: "SPEAKER_2"))
        XCTAssertNil(model.suggestion(for: "SPEAKER_1"))

        await model.accept(suggestion)

        let put = try XCTUnwrap(StubServer.requests(to: "/asr/jobs/j32-a/speakers").last)
        XCTAssertEqual(put.method, "PUT")
        XCTAssertEqual(put.json()["names"] as? [String: String],
                       ["SPEAKER_1": "Olena", "SPEAKER_2": "Anna Keller"], "every other name kept")
        XCTAssertEqual(put.json()["sources"] as? [String: String], ["SPEAKER_2": "suggestion"])
        XCTAssertEqual(model.name(for: "SPEAKER_2"), "Anna Keller")
        XCTAssertTrue(model.isSuggestedName("SPEAKER_2"), "the roster marks it as suggested")
        XCTAssertNil(model.suggestion(for: "SPEAKER_2"), "an accepted suggestion is not offered again")
        XCTAssertEqual(model.lastEdit?.summary, "Named Anna Keller")
        XCTAssertEqual(model.announcement?.text, "Named Anna Keller")

        await model.undoLastSpeakerEdit()

        let undo = try XCTUnwrap(StubServer.requests(to: "/asr/jobs/j32-a/speakers").last)
        XCTAssertEqual(StubServer.requests(to: "/asr/jobs/j32-a/speakers").count, 2)
        XCTAssertEqual(undo.json()["names"] as? [String: String], ["SPEAKER_1": "Olena"],
                       "undo is a PUT of the previous names")
        XCTAssertNil(undo.json()["sources"])
        XCTAssertTrue(StubServer.requests(to: "/asr/jobs/j32-a/speakers/edits/").isEmpty)
        XCTAssertEqual(model.name(for: "SPEAKER_2"), "Speaker 2")
        XCTAssertFalse(model.isSuggestedName("SPEAKER_2"))
        XCTAssertNil(model.lastEdit)
        XCTAssertEqual(model.suggestion(for: "SPEAKER_2"), suggestion, "the suggestion is offered again")
    }

    @MainActor
    func testATypedNameDropsTheMarker() async throws {
        let model = await loaded("j32-t", extra: ["name_suggestions": [Self.suggestion]])
        await model.accept(try XCTUnwrap(model.suggestion(for: "SPEAKER_2")))
        XCTAssertTrue(model.isSuggestedName("SPEAKER_2"))
        await model.renameSpeaker(label: "SPEAKER_2", to: "Anna K.")
        XCTAssertFalse(model.isSuggestedName("SPEAKER_2"), "edited by hand, no longer a suggestion")
    }

    @MainActor
    func testDismissPostsThePairAndTheSuggestionGoes() async throws {
        let model = await loaded("j32-d", extra: ["name_suggestions": [Self.suggestion]])
        await model.dismiss(try XCTUnwrap(model.suggestion(for: "SPEAKER_2")))

        let sent = StubServer.requests(to: "/asr/jobs/j32-d/speakers/suggestions/dismiss")
        XCTAssertEqual(sent.map(\.method), ["POST"])
        XCTAssertEqual(sent.first?.json() as? [String: String], ["label": "SPEAKER_2", "name": "Anna Keller"])
        XCTAssertNil(model.suggestion(for: "SPEAKER_2"))
        XCTAssertTrue(StubServer.requests(to: "/asr/jobs/j32-d/speakers").isEmpty, "no name was changed")
    }

    @MainActor
    func testAFailedDismissPutsTheSuggestionBack() async throws {
        let model = await loaded("j32-f", extra: ["name_suggestions": [Self.suggestion]], dismissStatus: 500)
        await model.dismiss(try XCTUnwrap(model.suggestion(for: "SPEAKER_2")))
        XCTAssertNotNil(model.suggestion(for: "SPEAKER_2"))
        XCTAssertNotNil(model.actionError)
    }

    // MARK: - The quote's turn

    @MainActor
    func testTheQuoteScrollsToTheTurnHoldingItsFirstSegment() async throws {
        let model = await loaded("j32-q", extra: ["name_suggestions": [Self.suggestion]])
        model.highlightDuration = .milliseconds(30)
        model.revealTurn(for: try XCTUnwrap(model.suggestion(for: "SPEAKER_2")))
        XCTAssertEqual(model.highlightedTurnId, 13_500)
        try await Task.sleep(for: .milliseconds(150))
        XCTAssertNil(model.highlightedTurnId, "the highlight fades")
    }

    func testTheTurnIsFoundBySegmentThenByTime() {
        let turns = [
            TranscriptTurn(speaker: "SPEAKER_1", name: nil, startMs: 0, endMs: 9_000, paragraphs: [],
                           segmentIndices: [0, 1, 2]),
            TranscriptTurn(speaker: "SPEAKER_2", name: nil, startMs: 13_500, endMs: 20_000, paragraphs: [],
                           segmentIndices: [3, 4]),
        ]
        XCTAssertEqual(NoteViewModel.turnId(for: NameSuggestion(label: "SPEAKER_2", name: "A", segmentIndices: [4]),
                                            in: turns), 13_500)
        XCTAssertEqual(NoteViewModel.turnId(for: NameSuggestion(label: "SPEAKER_1", name: "A", startMs: 5_000),
                                            in: turns), 0, "no indices: the turn it started in")
        XCTAssertNil(NoteViewModel.turnId(for: NameSuggestion(label: "SPEAKER_1", name: "A"), in: turns))
    }

    func testTheSpokenLabelCarriesTheEvidence() {
        let full = NameSuggestion(label: "SPEAKER_2", name: "Anna Keller", quote: "Hi, this is Anna", startMs: 14_000)
        XCTAssertEqual(NoteViewModel.suggestionTime(full), formatElapsed(ms: 14_000))
        XCTAssertEqual(NoteViewModel.suggestionAccessibilityLabel(full, speaker: "Speaker 2"),
                       "Speaker 2 is probably Anna Keller. Heard: Hi, this is Anna, at \(formatElapsed(ms: 14_000)).")
        XCTAssertEqual(NoteViewModel.suggestionAccessibilityLabel(NameSuggestion(label: "SPEAKER_2", name: "Anna"),
                                                                  speaker: "Speaker 2"),
                       "Speaker 2 is probably Anna.")
    }

    @MainActor
    func testTheChipSaysNameShareAndWhereTheNameCameFrom() async throws {
        let model = await loaded("j32-l", extra: ["name_suggestions": [Self.suggestion]])
        XCTAssertEqual(model.speakerAccessibilityLabel("SPEAKER_1"), "Olena, 60 percent of the talking")
        await model.accept(try XCTUnwrap(model.suggestion(for: "SPEAKER_2")))
        XCTAssertEqual(model.speakerAccessibilityLabel("SPEAKER_2"),
                       "Anna Keller, 40 percent of the talking, suggested name")
    }

    // MARK: - The re-label banner

    func testTheBannerRules() {
        XCTAssertTrue(NoteViewModel.showsRelabelBanner(available: true, dismissed: false, relabel: .idle, hasJob: true))
        XCTAssertFalse(NoteViewModel.showsRelabelBanner(available: false, dismissed: false, relabel: .idle, hasJob: true))
        XCTAssertFalse(NoteViewModel.showsRelabelBanner(available: true, dismissed: true, relabel: .idle, hasJob: true))
        XCTAssertFalse(NoteViewModel.showsRelabelBanner(available: true, dismissed: false, relabel: .running, hasJob: true))
        XCTAssertFalse(NoteViewModel.showsRelabelBanner(available: true, dismissed: false, relabel: .idle, hasJob: false))
    }

    @MainActor
    func testTheBannerRelabelsWithTheCountLeftToTheDiarizer() async throws {
        let model = await loaded("j32-r", extra: ["relabel_available": true, "count_confidence": "low"])
        XCTAssertTrue(model.showsRelabelBanner)
        XCTAssertFalse(model.showsCountBanner, "one banner at a time; re-labelling comes first")
        XCTAssertNil(model.smallSpeakerPrompt)

        await model.relabelFromBanner()

        let sent = try XCTUnwrap(StubServer.requests(to: "/asr/jobs/j32-r/rediarize").first)
        XCTAssertEqual(sent.method, "POST")
        XCTAssertTrue(sent.json().keys.contains("speakers_expected"))
        XCTAssertTrue(sent.json()["speakers_expected"] is NSNull, "null = let the diarizer decide")
        XCTAssertEqual(model.relabel, .running, "the Sprint 29 progress row takes over")
        XCTAssertFalse(model.showsRelabelBanner)
    }

    @MainActor
    func testNotNowHidesTheBanner() async {
        let model = await loaded("j32-n", extra: ["relabel_available": true])
        model.dismissRelabelBanner()
        XCTAssertFalse(model.showsRelabelBanner)
        XCTAssertTrue(StubServer.requests(to: "/asr/jobs/j32-n/rediarize").isEmpty)
    }

    // MARK: - Sign-out

    private func keep(identity: String) throws -> PendingCapture {
        let recording = FileManager.default.temporaryDirectory.appending(path: "\(UUID().uuidString).flac")
        try Data("audio".utf8).write(to: recording)
        var info = PendingCapture.Info(title: "Board call", language: "auto", diarize: true,
                                       recordedAt: Date(timeIntervalSince1970: 1_757_000_000),
                                       identityId: identity, tenantId: "t-1", speakersExpected: 3)
        info.setCaptureContext(CaptureContext(speakersMax: 4, nameCandidates: ["Anna Keller", "Tom Berg"],
                                              source: .calendarEvent))
        info.channelLayout = "mic_system"
        info.localSpeakerName = "Olena Petrenko"
        _ = try XCTUnwrap(PendingCaptures.keep(recording, info: info, in: directory))
        return try XCTUnwrap(PendingCaptures.all(in: directory).first { $0.info.identityId == identity })
    }

    func testSignOutDropsTheAccountsNamesFromItsRecordingsAndKeepsTheRest() throws {
        let mine = try keep(identity: "id-1")
        let theirs = try keep(identity: "id-2")
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "s32-\(UUID().uuidString)"))
        defaults.set(true, forKey: NoteViewModel.countBannerKey("job-1"))
        defaults.set(true, forKey: NoteViewModel.countBannerKey("job-2"))
        defaults.set("de", forKey: "captureLanguage")

        SignOutCleanup.run(identityId: "id-1", directory: directory, defaults: defaults)

        let after = PendingCaptures.all(in: directory)
        XCTAssertEqual(after.count, 2, "no recording is deleted by a sign-out")
        let cleaned = try XCTUnwrap(after.first { $0.id == mine.id })
        XCTAssertTrue(FileManager.default.fileExists(atPath: cleaned.audioURL.path))
        XCTAssertNil(cleaned.info.nameCandidates, "the invitees' names go")
        XCTAssertNil(cleaned.info.localSpeakerName, "the account's name goes")
        XCTAssertEqual(cleaned.info.channelLayout, "mic_system", "the layout describes the file and stays")
        XCTAssertEqual(cleaned.info.speakersExpected, 3, "the People hint describes the audio and stays")
        XCTAssertEqual(cleaned.info.speakersMax, 4)
        XCTAssertEqual(cleaned.info.captureSource, "calendar_event")
        XCTAssertEqual(cleaned.info.title, "Board call")
        XCTAssertEqual(after.first { $0.id == theirs.id }?.info.nameCandidates, ["Anna Keller", "Tom Berg"],
                       "another person's recording on this device is not touched")

        XCTAssertNil(defaults.object(forKey: NoteViewModel.countBannerKey("job-1")), "per-job answers go")
        XCTAssertNil(defaults.object(forKey: NoteViewModel.countBannerKey("job-2")))
        XCTAssertEqual(defaults.string(forKey: "captureLanguage"), "de", "device settings stay")
    }

    func testSigningOutWithNoIdentityTouchesNoRecording() throws {
        let kept = try keep(identity: "id-1")
        XCTAssertEqual(SignOutCleanup.scrubPending(identityId: "", in: directory), 0)
        XCTAssertEqual(PendingCaptures.all(in: directory).first?.info, kept.info)
    }
}
