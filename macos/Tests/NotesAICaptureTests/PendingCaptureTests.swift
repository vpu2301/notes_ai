import XCTest
@testable import NotesAICapture

/// IDX-M1 M1-04 — a recording that did not reach the server is kept.
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
                       "moved out of the temporary directory macOS empties")
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
}
