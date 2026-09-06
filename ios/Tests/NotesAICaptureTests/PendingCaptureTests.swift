import XCTest
@testable import NotesAICapture

/// IDX-I1 I1-03 — a recording that did not reach the server is kept.
final class PendingCaptureTests: XCTestCase {
    private var directory: URL!

    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory
            .appending(path: "pending-tests-\(UUID().uuidString)")
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: directory)
    }

    private func makeRecording(_ name: String = "meeting.flac") throws -> URL {
        let url = FileManager.default.temporaryDirectory.appending(path: "\(UUID().uuidString)-\(name)")
        try Data("audio".utf8).write(to: url)
        return url
    }

    private func info(title: String = "Weekly sync") -> PendingCapture.Info {
        PendingCapture.Info(title: title, language: "auto", diarize: true,
                            recordedAt: Date(timeIntervalSince1970: 1_757_000_000),
                            identityId: "id-1", tenantId: "t-1")
    }

    func testTheRecordingIsMovedRatherThanCopiedOrDeleted() throws {
        let recording = try makeRecording()

        let kept = PendingCaptures.keep(recording, info: info(), in: directory)

        XCTAssertNotNil(kept)
        XCTAssertFalse(FileManager.default.fileExists(atPath: recording.path),
                       "moved out of the temporary directory iOS reclaims")
        XCTAssertTrue(FileManager.default.fileExists(atPath: kept!.path))
        XCTAssertEqual(kept?.pathExtension, "flac", "the audio keeps its format")
    }

    func testTheSidecarSaysWhatTheRecordingWas() throws {
        let recording = try makeRecording()

        let kept = PendingCaptures.keep(recording, info: info(title: "Board call"), in: directory)!
        let sidecar = kept.deletingPathExtension().appendingPathExtension("json")
        let object = try JSONSerialization.jsonObject(
            with: Data(contentsOf: sidecar)) as! [String: Any]

        XCTAssertEqual(object["title"] as? String, "Board call")
        XCTAssertEqual(object["language"] as? String, "auto")
        XCTAssertEqual(object["diarize"] as? Bool, true)
        XCTAssertEqual(object["identity_id"] as? String, "id-1")
        XCTAssertEqual(object["tenant_id"] as? String, "t-1")
        XCTAssertNotNil(object["recorded_at"] as? String)
    }

    func testKeptRecordingsAreListedNewestFirst() throws {
        let old = try makeRecording("old.flac")
        let new = try makeRecording("new.wav")
        var earlier = info(title: "Older")
        earlier.recordedAt = Date(timeIntervalSince1970: 1_000_000)
        var later = info(title: "Newer")
        later.recordedAt = Date(timeIntervalSince1970: 2_000_000)

        PendingCaptures.keep(old, info: earlier, in: directory)
        PendingCaptures.keep(new, info: later, in: directory)

        let all = PendingCaptures.all(in: directory)
        XCTAssertEqual(all.map(\.info.title), ["Newer", "Older"])
        XCTAssertEqual(PendingCaptures.count(in: directory), 2)
    }

    func testNothingIsDestroyedWhenTheDestinationCannotBeWritten() throws {
        let recording = try makeRecording()
        // A directory that cannot be created: a path under a regular file.
        let blocker = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        try Data().write(to: blocker)
        defer { try? FileManager.default.removeItem(at: blocker) }

        let kept = PendingCaptures.keep(recording, info: info(), in: blocker.appending(path: "pending"))

        XCTAssertNil(kept)
        XCTAssertTrue(FileManager.default.fileExists(atPath: recording.path),
                      "a failed move leaves the recording where it is — never deleted")
    }

    func testCountingAnEmptyOrMissingDirectoryIsZero() {
        XCTAssertEqual(PendingCaptures.count(in: directory), 0)
        XCTAssertTrue(PendingCaptures.all(in: directory).isEmpty)
    }

    // MARK: - IDX-I2: whose it is, where it goes, and when it may go away

    func testOnlyThisIdentitysRecordingsAreListed() throws {
        var mine = info(title: "Mine")
        mine.identityId = "id-1"
        var theirs = info(title: "Theirs")
        theirs.identityId = "id-2"
        PendingCaptures.keep(try makeRecording("a.flac"), info: mine, in: directory)
        PendingCaptures.keep(try makeRecording("b.flac"), info: theirs, in: directory)

        let listed = PendingCaptures.all(identityId: "id-1", in: directory)

        XCTAssertEqual(listed.map(\.info.title), ["Mine"],
                       "a phone two people share must not offer one of them the other's meeting")
    }

    func testARecordingCanBeSentToAnotherWorkspace() throws {
        let kept = PendingCaptures.keep(try makeRecording(), info: info(), in: directory)!
        let capture = PendingCaptures.all(in: directory).first { $0.audioURL == kept }!
        XCTAssertEqual(capture.info.tenantId, "t-1")

        let moved = PendingCaptures.retarget(capture, to: "t-2")

        XCTAssertEqual(moved.info.tenantId, "t-2")
        XCTAssertEqual(PendingCaptures.all(in: directory).first?.info.tenantId, "t-2",
                       "the sidecar on disk is what the retry will read")
        XCTAssertEqual(moved.info.title, "Weekly sync", "only the workspace changes")
        XCTAssertTrue(FileManager.default.fileExists(atPath: kept.path))
    }

    func testARecordingIsUploadableOnlyToAWorkspaceItsOwnerIsStillIn() throws {
        PendingCaptures.keep(try makeRecording(), info: info(), in: directory)
        let capture = PendingCaptures.all(in: directory).first!

        XCTAssertFalse(PendingCaptures.needsWorkspace(capture, memberships: ["t-1", "t-2"]))
        XCTAssertTrue(PendingCaptures.needsWorkspace(capture, memberships: ["t-2"]),
                      "the client never uploads to a workspace it already knows it left")
        XCTAssertTrue(PendingCaptures.needsWorkspace(capture, memberships: []))
    }

    func testARecordingWithNoWorkspaceGoesToWhicheverIsOpen() throws {
        var orphan = info()
        orphan.tenantId = nil
        PendingCaptures.keep(try makeRecording(), info: orphan, in: directory)
        let capture = PendingCaptures.all(in: directory).first!

        XCTAssertFalse(PendingCaptures.needsWorkspace(capture, memberships: ["t-9"]))
    }

    func testDeletingTakesTheSidecarWithIt() throws {
        let kept = PendingCaptures.keep(try makeRecording(), info: info(), in: directory)!
        let capture = PendingCaptures.all(in: directory).first!

        PendingCaptures.delete(capture)

        XCTAssertFalse(FileManager.default.fileExists(atPath: kept.path))
        XCTAssertFalse(FileManager.default.fileExists(
            atPath: PendingCaptures.sidecar(of: kept).path))
        XCTAssertTrue(PendingCaptures.all(in: directory).isEmpty)
    }

    func testOldRecordingsAreOnlySomebodyElsesAndOnlyAfterAMonth() throws {
        var recent = info(title: "Yesterday, someone else")
        recent.identityId = "id-2"
        recent.recordedAt = Date().addingTimeInterval(-86_400)
        var ancient = info(title: "Long ago, someone else")
        ancient.identityId = "id-2"
        ancient.recordedAt = Date().addingTimeInterval(-60 * 86_400)
        var ancientMine = info(title: "Long ago, mine")
        ancientMine.identityId = "id-1"
        ancientMine.recordedAt = Date().addingTimeInterval(-60 * 86_400)
        PendingCaptures.keep(try makeRecording("a.flac"), info: recent, in: directory)
        PendingCaptures.keep(try makeRecording("b.flac"), info: ancient, in: directory)
        PendingCaptures.keep(try makeRecording("c.flac"), info: ancientMine, in: directory)

        let old = PendingCaptures.old(excluding: "id-1", in: directory)

        XCTAssertEqual(old.map(\.info.title), ["Long ago, someone else"])
        XCTAssertEqual(PendingCaptures.all(in: directory).count, 3,
                       "listing old recordings never removes any of them")
    }

    func testKeptFilesAreReadableAfterTheFirstUnlockAndNotBefore() throws {
        // `.complete` would make an upload that is still running as the
        // phone locks fail; `.none` would leave the recordings readable on
        // a stolen handset that was never unlocked. The class in between
        // is the one this app wants (IDX-I2 F).
        let kept = PendingCaptures.keep(try makeRecording(), info: info(), in: directory)!

        let audio = try FileManager.default.attributesOfItem(atPath: kept.path)
        let sidecar = try FileManager.default.attributesOfItem(
            atPath: PendingCaptures.sidecar(of: kept).path)

        #if !targetEnvironment(simulator)
        // The simulator's filesystem has no data protection to report.
        XCTAssertEqual(audio[.protectionKey] as? FileProtectionType,
                       .completeUntilFirstUserAuthentication)
        XCTAssertEqual(sidecar[.protectionKey] as? FileProtectionType,
                       .completeUntilFirstUserAuthentication)
        #else
        XCTAssertNotNil(audio[.size])
        XCTAssertNotNil(sidecar[.size])
        #endif
        XCTAssertEqual(PendingCaptures.protection, .completeUntilFirstUserAuthentication)
    }
}
