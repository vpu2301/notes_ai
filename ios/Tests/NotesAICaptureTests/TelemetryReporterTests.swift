import Foundation
import XCTest
@testable import NotesAICapture

/// Telemetry sprint 3: the shared client-event reporter (clients/Shared/TelemetryReporter.swift).
final class TelemetryReporterTests: XCTestCase {
    /// Collects what would be POSTed; can be told to fail.
    actor Sink {
        var bodies: [[String: Any]] = []
        var failures = 0
        func fail(_ n: Int) { failures = n }
        func take(_ data: Data) throws {
            if failures > 0 {
                failures -= 1
                throw URLError(.notConnectedToInternet)
            }
            bodies.append(try JSONSerialization.jsonObject(with: data) as! [String: Any])
        }
        func events() -> [[String: Any]] { bodies.flatMap { $0["events"] as! [[String: Any]] } }
    }

    private func reporter(_ sink: Sink, file: URL? = nil, now: @escaping @Sendable () -> Date = { Date() })
        -> TelemetryReporter {
        TelemetryReporter(client: "ios", version: "test", file: file, now: now) { data in
            try await sink.take(data)
        }
    }

    func testADisplayIsReportedOncePerRecording() async {
        let sink = Sink()
        let r = reporter(sink)
        await r.report(.transcriptDisplayed, recordingId: "job-1")
        await r.report(.transcriptDisplayed, recordingId: "job-1")
        await r.report(.notesDisplayed, recordingId: "job-1")
        await r.flushNow()
        let events = await sink.events()
        XCTAssertEqual(events.map { $0["event"] as? String }, ["transcript_displayed", "notes_displayed"])
        XCTAssertEqual(events.first?["client"] as? String, "ios")
        let bodies = await sink.bodies
        XCTAssertNotNil(bodies.first?["sent_at"])
    }

    func testEventsBeforeTheUploadAreTaggedWithTheirCapturesRecording() async {
        let sink = Sink()
        let r = reporter(sink)
        let stopped = Date(timeIntervalSince1970: 1_800_000_000)
        await r.reportBeforeRecording(.recordingStopped, capture: "a.flac", at: stopped)
        await r.reportBeforeRecording(.uploadStarted, capture: "a.flac", attributes: ["bytes": 10])
        await r.reportBeforeRecording(.recordingStopped, capture: "b.flac")  // another capture: waits
        await r.attachRecording("job-a", capture: "a.flac")
        await r.flushNow()
        let events = await sink.events()
        XCTAssertEqual(events.map { $0["recording_id"] as? String }, ["job-a", "job-a"])
        XCTAssertEqual(events.map { $0["event"] as? String }, ["recording_stopped", "upload_started"])
        XCTAssertNil(events.first?["client_monotonic_ns"] as? Int)  // a time passed in: no monotonic stamp
        XCTAssertEqual((events.last?["attributes"] as? [String: Int])?["bytes"], 10)
    }

    func testAFailedSendIsKeptOnDiskAndDeliveredLater() async throws {
        let file = FileManager.default.temporaryDirectory.appending(path: "telemetry-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: file) }
        let sink = Sink()
        await sink.fail(1)
        let first = reporter(sink, file: file)
        await first.report(.notesDisplayed, recordingId: "job-2")
        await first.flushNow()  // fails: kept
        let empty = await sink.events()
        XCTAssertTrue(empty.isEmpty)
        // A new process (app restart) picks the queue up from disk.
        let second = reporter(sink, file: file)
        await second.flushNow()
        let events = await sink.events()
        XCTAssertEqual(events.map { $0["recording_id"] as? String }, ["job-2"])
    }

    func testEventsOlderThanADayAreDropped() async {
        let sink = Sink()
        let clock = TestClock(Date(timeIntervalSince1970: 1_800_000_000))
        let r = reporter(sink, now: { clock.now })
        await sink.fail(1)
        await r.report(.notesDisplayed, recordingId: "job-3")
        await r.flushNow()
        clock.advance(by: TelemetryReporter.maxAge + 1)
        await r.flushNow()
        let events = await sink.events()
        XCTAssertTrue(events.isEmpty)
        let queued = await r.queued()
        XCTAssertTrue(queued.isEmpty)
    }
}

/// A settable clock for the reporter's `now`.
final class TestClock: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Date
    init(_ start: Date) { value = start }
    var now: Date { lock.withLock { value } }
    func advance(by seconds: TimeInterval) { lock.withLock { value = value.addingTimeInterval(seconds) } }
}
