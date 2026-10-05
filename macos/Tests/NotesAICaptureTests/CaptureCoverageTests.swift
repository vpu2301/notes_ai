import AVFoundation
import XCTest
@testable import NotesAICapture

/// The capture timing sent with an upload, and the "Not transcribed" line read from a result.
final class CaptureCoverageTests: XCTestCase {
    private var scratch: URL!

    override func setUpWithError() throws {
        scratch = FileManager.default.temporaryDirectory.appending(path: "f1-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: scratch)
    }

    // MARK: - Offset measurement

    func testTheOffsetIsTheTimeFromThePressToTheFirstFrame() {
        let pressed = Date(timeIntervalSince1970: 1_000)
        XCTAssertEqual(CaptureTiming.offsetMs(pressedAt: pressed, firstFrameAt: pressed.addingTimeInterval(3.2104)), 3210)
        XCTAssertEqual(CaptureTiming.offsetMs(pressedAt: pressed, firstFrameAt: pressed.addingTimeInterval(-1)), 0,
                       "a clock step backwards is not a negative latency")
        XCTAssertEqual(CaptureTiming.offsetMs(pressedAt: pressed, firstFrameAt: pressed.addingTimeInterval(3600)),
                       600_000, "clamped to what the server accepts")
        XCTAssertNil(CaptureTiming(pressedAt: pressed, firstFrameAt: nil), "no frame ever written → no timing")
        XCTAssertNil(CaptureTiming(pressedAt: nil, firstFrameAt: pressed))
    }

    func testTheClockKeepsOnlyTheFirstMark() {
        let times = Times([Date(timeIntervalSince1970: 10), Date(timeIntervalSince1970: 20)])
        let clock = FirstFrameClock(now: { times.next() })
        XCTAssertNil(clock.firstFrameAt)
        clock.mark()
        clock.mark()
        XCTAssertEqual(clock.firstFrameAt, Date(timeIntervalSince1970: 10))
        clock.reset()
        XCTAssertNil(clock.firstFrameAt)
    }

    func testTheSinkMarksTheFirstBufferWrittenToTheFile() throws {
        let format = RecordingFormat.wav.withChannels(2)
        let url = scratch.appending(path: "rec.\(format.fileExtension)")
        let sink = TapSink()
        sink.beginDual(file: try AVAudioFile(forWriting: url, settings: format.fileSettings))
        XCTAssertNil(sink.firstFrame.firstFrameAt, "nothing written yet")
        let before = Date()
        sink.consume(mic: Self.buffer(frames: 1600), system: Self.buffer(frames: 1600))
        let marked = try XCTUnwrap(sink.firstFrame.firstFrameAt)
        XCTAssertGreaterThanOrEqual(marked, before)
        sink.consume(mic: Self.buffer(frames: 1600), system: Self.buffer(frames: 1600))
        XCTAssertEqual(sink.firstFrame.firstFrameAt, marked, "later buffers do not move it")
        sink.finish()
    }

    func testTheLatencyNoticeOnlyForANoticeableStart() {
        XCTAssertNil(CaptureTiming.latencyNotice(offsetMs: nil))
        XCTAssertNil(CaptureTiming.latencyNotice(offsetMs: 400))
        XCTAssertEqual(CaptureTiming.latencyNotice(offsetMs: 3_400), "Recording from 0:03")
        XCTAssertEqual(CaptureTiming.latencyNotice(offsetMs: 75_000), "Recording from 1:15")
    }

    // MARK: - Upload

    func testTheFormCarriesBothFieldsOrNeither() {
        let pressed = Date(timeIntervalSince1970: 1_790_000_000.25)
        let timing = CaptureTiming(recordPressedAt: pressed, firstFrameOffsetMs: 1234)
        let fields = APIClient.jobFields(language: "auto", diarize: true, speakersExpected: nil,
                                         captureTiming: timing)
        XCTAssertTrue(fields.contains { $0 == ("first_frame_offset_ms", "1234") })
        let stamp = fields.first { $0.0 == "record_pressed_at" }?.1
        XCTAssertEqual(stamp, "2026-09-21T14:13:20.250Z")
        XCTAssertEqual(CaptureTiming.isoFormatter.date(from: stamp ?? ""), pressed)

        let none = APIClient.jobFields(language: "auto", diarize: true, speakersExpected: nil)
        XCTAssertFalse(none.contains { $0.0 == "record_pressed_at" || $0.0 == "first_frame_offset_ms" })
    }

    func testTheUploadSendsTheTiming() async throws {
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (202, Fixtures.json(["id": "job-1", "status": "queued"]), [:])
        }
        let file = scratch.appending(path: "a.wav")
        try Data("RIFF".utf8).write(to: file)
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        _ = try await client.submitJob(fileURL: file, contentType: "audio/wav", language: "auto", diarize: false,
                                       captureTiming: CaptureTiming(recordPressedAt: Date(), firstFrameOffsetMs: 850))
        let body = String(decoding: StubServer.requests(to: "/asr/jobs").last?.body ?? Data(), as: UTF8.self)
        XCTAssertTrue(body.contains("name=\"first_frame_offset_ms\"\r\n\r\n850\r\n"))
        XCTAssertTrue(body.contains("name=\"record_pressed_at\""))

        _ = try await client.submitJob(fileURL: file, contentType: "audio/wav", language: "auto", diarize: false)
        let plain = String(decoding: StubServer.requests(to: "/asr/jobs").last?.body ?? Data(), as: UTF8.self)
        XCTAssertFalse(plain.contains("first_frame_offset_ms"), "an import sends no timing")
        XCTAssertFalse(plain.contains("record_pressed_at"))
    }

    func testAKeptRecordingKeepsItsTiming() throws {
        var info = PendingCapture.Info(title: "T", language: "auto", diarize: true,
                                       recordedAt: Date(), identityId: "id-1", tenantId: nil)
        XCTAssertNil(info.captureTiming)
        let timing = CaptureTiming(recordPressedAt: Date(timeIntervalSince1970: 1_790_000_000), firstFrameOffsetMs: 2100)
        info.captureTiming = timing
        let decoded = try JSONDecoder.pending.decode(PendingCapture.Info.self,
                                                     from: JSONEncoder.pending.encode(info))
        XCTAssertEqual(decoded.captureTiming, timing)

        let old = #"{"title":"T","language":"auto","diarize":true,"recorded_at":"2026-09-01T10:00:00Z","identity_id":"i"}"#
        let legacy = try JSONDecoder.pending.decode(PendingCapture.Info.self, from: Data(old.utf8))
        XCTAssertNil(legacy.captureTiming, "an older sidecar uploads without timing")
    }

    // MARK: - Result decoding

    func testCoverageAndCaptureDecode() throws {
        let json = """
        {"job_id":"j1","segments":[],
         "coverage":{"speech_ms":136000,"transcribed_ms":91000,"first_speech_ms":11000,
                     "first_segment_ms":45000,"share":0.67,"vad":"silero",
                     "gaps":[{"start_ms":0,"end_ms":3000,"cause":"no_audio"},
                             {"start_ms":11000,"end_ms":44000,"cause":"prompt_echo"},
                             {"start_ms":50000,"end_ms":52000,"cause":"brand_new_cause"}]},
         "capture":{"record_pressed_at":"2026-09-25T16:29:00.000Z","first_frame_offset_ms":3000}}
        """
        let result = try JSONDecoder().decode(TranscriptResult.self, from: Data(json.utf8))
        XCTAssertEqual(result.coverage?.share, 0.67)
        XCTAssertEqual(result.coverage?.gaps?.count, 3)
        XCTAssertEqual(result.coverage?.gaps?[2].cause, "brand_new_cause", "an unknown cause still decodes")
        XCTAssertEqual(result.capture?.firstFrameOffsetMs, 3000)
    }

    func testOlderResultsDecodeWithoutCoverage() throws {
        let absent = try JSONDecoder().decode(TranscriptResult.self, from: Data(#"{"job_id":"j1","segments":[]}"#.utf8))
        XCTAssertNil(absent.coverage)
        XCTAssertNil(absent.capture)
        let null = try JSONDecoder().decode(TranscriptResult.self,
                                            from: Data(#"{"job_id":"j1","segments":[],"coverage":null,"capture":null}"#.utf8))
        XCTAssertNil(null.coverage)
        XCTAssertNil(null.capture)
        let partial = try JSONDecoder().decode(
            TranscriptResult.self,
            from: Data(#"{"job_id":"j1","segments":[],"coverage":{"gaps":[{"start_ms":5000}]},"capture":{}}"#.utf8))
        XCTAssertEqual(partial.coverage?.gaps?.first, CoverageGap(startMs: 5000, endMs: 5000, cause: "unknown"))
        XCTAssertNil(partial.capture?.firstFrameOffsetMs)
    }

    // MARK: - "Not transcribed"

    func testNothingIsShownForAFullRecording() {
        XCTAssertNil(CoverageGapsFormatter.line(nil))
        XCTAssertNil(CoverageGapsFormatter.line(TranscriptCoverage(share: 1, gaps: [])))
        XCTAssertNil(CoverageGapsFormatter.line(TranscriptCoverage(share: 1)))
    }

    func testTheLineNamesEachGapAndItsCause() throws {
        let line = try XCTUnwrap(CoverageGapsFormatter.line(TranscriptCoverage(gaps: [
            CoverageGap(startMs: 0, endMs: 44_000, cause: "no_audio"),
            CoverageGap(startMs: 61_000, endMs: 65_500, cause: "no_speech_detected"),
        ])))
        XCTAssertEqual(line.text,
                       "Not transcribed: 00:00–00:44 (audio started late), 01:01–01:05 (no speech detected)")
        XCTAssertFalse(line.items[0].seekable, "audio before the file began cannot be opened")
        XCTAssertTrue(line.items[1].seekable)
        XCTAssertEqual(line.items[1].startMs, 61_000)
    }

    func testCausesReadAsPlainWords() {
        XCTAssertEqual(CoverageGapsFormatter.reason("no_audio"), "audio started late")
        XCTAssertEqual(CoverageGapsFormatter.reason("no_speech_detected"), "no speech detected")
        XCTAssertEqual(CoverageGapsFormatter.reason("decoder_empty"), "could not be decoded")
        XCTAssertEqual(CoverageGapsFormatter.reason("prompt_echo"), "could not be decoded")
        XCTAssertEqual(CoverageGapsFormatter.reason("unknown"), "could not be decoded")
        XCTAssertEqual(CoverageGapsFormatter.reason("other_language"), "another language")
        XCTAssertEqual(CoverageGapsFormatter.reason("something_new"), "could not be decoded")
    }

    func testAtMostFourRangesThenACount() throws {
        let gaps = (0..<7).map { CoverageGap(startMs: $0 * 10_000, endMs: $0 * 10_000 + 4_000, cause: "decoder_empty") }
        let line = try XCTUnwrap(CoverageGapsFormatter.line(TranscriptCoverage(gaps: gaps)))
        XCTAssertEqual(line.items.count, 4)
        XCTAssertEqual(line.more, 3)
        XCTAssertTrue(line.text.hasSuffix("00:30–00:34 (could not be decoded) +3 more"))
    }

    func testTimesPastAnHourShowHours() {
        XCTAssertEqual(CoverageGapsFormatter.time(44_999), "00:44")
        XCTAssertEqual(CoverageGapsFormatter.time(3_723_000), "1:02:03")
        XCTAssertEqual(CoverageGapsFormatter.time(-5), "00:00")
    }

    // MARK: - Helpers

    private static func buffer(frames: Int) -> AVAudioPCMBuffer {
        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16_000, channels: 1, interleaved: false)!
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(frames))!
        buffer.frameLength = AVAudioFrameCount(frames)
        for i in 0..<frames { buffer.floatChannelData![0][i] = 0.1 }
        return buffer
    }
}

/// Hands out the given moments in order (the last one repeats).
private final class Times: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [Date]

    init(_ values: [Date]) { self.values = values }

    func next() -> Date {
        lock.lock()
        defer { lock.unlock() }
        return values.count > 1 ? values.removeFirst() : values[0]
    }
}
