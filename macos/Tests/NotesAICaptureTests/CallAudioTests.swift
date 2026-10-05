import AVFoundation
import CoreAudio
import XCTest
@testable import NotesAICapture

/// Channel-aware capture: microphone on ch0, call audio on ch1. No hardware or permission: `TapSink` is fed synthetic buffers.
final class CallAudioTests: XCTestCase {
    private var scratch: URL!

    override func setUpWithError() throws {
        scratch = FileManager.default.temporaryDirectory.appending(path: "s31-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: scratch)
    }

    // MARK: - Helpers

    private func monoBuffer(_ value: Float, frames: Int, rate: Double = 16_000) -> AVAudioPCMBuffer {
        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: rate, channels: 1, interleaved: false)!
        return AVAudioPCMBuffer.mono([Float](repeating: value, count: frames), format: format)!
    }

    /// A sink writing a two-channel file. Only the sink holds the `AVAudioFile`, so `finish()` finalizes the container.
    private func dualSink(_ format: RecordingFormat = RecordingFormat.wav.withChannels(2)) throws -> (TapSink, URL) {
        let url = scratch.appending(path: "rec-\(UUID().uuidString).\(format.fileExtension)")
        let sink = TapSink()
        sink.beginDual(file: try AVAudioFile(forWriting: url, settings: format.fileSettings))
        return (sink, url)
    }

    private func readBack(_ url: URL) throws -> (channels: Int, ch0: [Float], ch1: [Float]) {
        let file = try AVAudioFile(forReading: url)
        let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat,
                                      frameCapacity: AVAudioFrameCount(file.length))!
        try file.read(into: buffer)
        let n = Int(buffer.frameLength)
        let data = buffer.floatChannelData!
        let channels = Int(file.fileFormat.channelCount)
        return (channels, Array(UnsafeBufferPointer(start: data[0], count: n)),
                channels > 1 ? Array(UnsafeBufferPointer(start: data[1], count: n)) : [])
    }

    private func mean(_ values: ArraySlice<Float>) -> Float {
        values.isEmpty ? 0 : values.reduce(0, +) / Float(values.count)
    }

    // MARK: - TapSink: interleaving

    func testMicGoesToChannelZeroAndCallAudioToChannelOne() throws {
        let (sink, url) = try dualSink()
        for _ in 0..<10 {
            sink.consume(mic: monoBuffer(0.25, frames: 1600), system: monoBuffer(-0.5, frames: 1600))
        }
        XCTAssertFalse(sink.systemLost)
        sink.finish()

        let back = try readBack(url)
        XCTAssertEqual(back.channels, 2)
        XCTAssertEqual(back.ch0.count, 16_000, "one second at 16 kHz")
        XCTAssertEqual(mean(back.ch0[...]), 0.25, accuracy: 0.001)
        XCTAssertEqual(mean(back.ch1[...]), -0.5, accuracy: 0.001)
        XCTAssertEqual(back.ch0.max()!, 0.25, accuracy: 0.001, "no call audio leaks into the mic channel")
    }

    func testDeviceRateBuffersAreResampledTo16kOnBothChannels() throws {
        let (sink, url) = try dualSink(RecordingFormat.flac.withChannels(2))
        for _ in 0..<40 {  // 4 s at 48 kHz
            sink.consume(mic: monoBuffer(0.3, frames: 4800, rate: 48_000),
                         system: monoBuffer(-0.2, frames: 4800, rate: 48_000))
        }
        sink.finish()

        let back = try readBack(url)
        XCTAssertEqual(back.channels, 2, "the FLAC writer takes two channels")
        // The resampler holds back its filter latency at the edges (tens of ms) — not a per-buffer loss.
        XCTAssertEqual(Double(back.ch0.count), 64_000, accuracy: 1_000)
        // Away from the resampler's start-up edge the levels are exact.
        let middle = 4_000..<60_000
        XCTAssertEqual(mean(back.ch0[middle]), 0.3, accuracy: 0.002)
        XCTAssertEqual(mean(back.ch1[middle]), -0.2, accuracy: 0.002)
    }

    func testLosingTheCallAudioWritesSilenceOnChannelOneAndFlagsIt() throws {
        let (sink, url) = try dualSink()
        for _ in 0..<5 {
            sink.consume(mic: monoBuffer(0.25, frames: 1600), system: monoBuffer(-0.5, frames: 1600))
        }
        for _ in 0..<5 {
            sink.consume(mic: monoBuffer(0.25, frames: 1600), system: nil)
        }
        XCTAssertTrue(sink.systemLost)
        XCTAssertEqual(sink.currentSystemLevel(), 0)
        sink.finish()

        let back = try readBack(url)
        XCTAssertEqual(back.channels, 2, "the file keeps its layout")
        XCTAssertEqual(back.ch0.count, 16_000, "the microphone kept its full length")
        XCTAssertEqual(mean(back.ch0[8_000...]), 0.25, accuracy: 0.001)
        XCTAssertEqual(mean(back.ch1[..<8_000]), -0.5, accuracy: 0.001)
        XCTAssertEqual(back.ch1[8_000...].map(abs).max(), 0, "digital silence after the loss")
    }

    func testMarkingTheSourceFailedFlagsTheLoss() throws {
        let (sink, _) = try dualSink()
        sink.markSystemLost()
        XCTAssertTrue(sink.systemLost)
        sink.finish()
    }

    func testTheMonoPathIgnoresTwoChannelInput() throws {
        let url = scratch.appending(path: "mono.wav")
        let sink = TapSink()
        do {
            let file = try AVAudioFile(forWriting: url, settings: RecordingFormat.wav.fileSettings)
            let input = monoBuffer(0.25, frames: 1600).format
            sink.begin(file: file, converter: AVAudioConverter(from: input, to: file.processingFormat)!,
                       inputFormat: input)
        }
        sink.consume(mic: monoBuffer(0.25, frames: 1600), system: monoBuffer(-0.5, frames: 1600))
        sink.consume(monoBuffer(0.25, frames: 1600))
        sink.finish()

        let back = try readBack(url)
        XCTAssertEqual(back.channels, 1)
        XCTAssertEqual(back.ch0.count, 1600, "only the mono consume wrote")
    }

    // MARK: - Interleaver

    func testFramesOneSideIsAheadByAreHeldUntilTheOtherCatchesUp() {
        var interleaver = ChannelInterleaver(maxSkew: 100)
        interleaver.append(mic: [1, 1, 1, 1], system: [2, 2])
        var out = interleaver.drain()
        XCTAssertEqual(out.mic, [1, 1])
        XCTAssertEqual(out.system, [2, 2])
        interleaver.append(mic: [], system: [3, 3, 3])
        out = interleaver.drain()
        XCTAssertEqual(out.mic, [1, 1])
        XCTAssertEqual(out.system, [3, 3])
        out = interleaver.flush()
        XCTAssertEqual(out.mic, [0], "the shorter side is padded at the end")
        XCTAssertEqual(out.system, [3])
    }

    func testASideThatFallsTooFarBehindIsPaddedWithSilence() {
        var interleaver = ChannelInterleaver(maxSkew: 3)
        interleaver.append(mic: [1, 1, 1, 1, 1], system: [2])
        let out = interleaver.drain()
        XCTAssertEqual(out.mic, [1, 1, 1, 1, 1])
        XCTAssertEqual(out.system, [2, 0, 0, 0, 0])
    }

    // MARK: - The IO block's channel split

    func testTheSplitterTakesMicChannelZeroAndMixesTheTapPair() {
        let frames = 4
        var mic: [Float] = [0.1, 0.2, 0.3, 0.4]
        var tap: [Float] = [1, 0, 1, 0, 1, 0, 1, 0]  // L=1, R=0 interleaved
        let list = AudioBufferList.allocate(maximumBuffers: 2)
        defer { free(list.unsafeMutablePointer) }
        mic.withUnsafeMutableBytes { micBytes in
            tap.withUnsafeMutableBytes { tapBytes in
                list[0] = AudioBuffer(mNumberChannels: 1, mDataByteSize: UInt32(frames * 4),
                                      mData: micBytes.baseAddress)
                list[1] = AudioBuffer(mNumberChannels: 2, mDataByteSize: UInt32(frames * 8),
                                      mData: tapBytes.baseAddress)
                let split = InputSplitter.split(buffers: list, micChannels: 1)
                XCTAssertEqual(split?.mic, [0.1, 0.2, 0.3, 0.4])
                XCTAssertEqual(split?.system, [0.5, 0.5, 0.5, 0.5])

                // The aggregate without its tap channels: call audio missing.
                list.unsafeMutablePointer.pointee.mNumberBuffers = 1
                let micOnly = InputSplitter.split(buffers: list, micChannels: 1)
                XCTAssertEqual(micOnly?.mic.count, 4)
                XCTAssertNil(micOnly?.system)
            }
        }
    }

    // MARK: - Fallback selection

    func testTheCallAudioIsOnlyTriedWhenWantedAndPossible() {
        var made = 0
        let off = CaptureModeSelector.select(settingOn: false, consentCurrent: true) { made += 1; return FakeSource() }
        XCTAssertEqual(off.mode, .micOnly(.settingOff))
        let stale = CaptureModeSelector.select(settingOn: true, consentCurrent: false) { made += 1; return FakeSource() }
        XCTAssertEqual(stale.mode, .micOnly(.consentNeeded))
        XCTAssertEqual(made, 0, "no tap is created without the setting and a current consent")

        let old = CaptureModeSelector.select(settingOn: true, consentCurrent: true) { nil }
        XCTAssertEqual(old.mode, .micOnly(.unsupportedOS))
    }

    func testAFailedTapFallsBackToTheMicrophoneWithAReason() {
        let source = FakeSource(error: SystemAudioError.tapFailed(-1))
        let selection = CaptureModeSelector.select(settingOn: true, consentCurrent: true) { source }
        XCTAssertEqual(selection.mode, .micOnly(.unavailable(SystemAudioError.tapFailed(-1).localizedDescription)))
        XCTAssertNil(selection.source)
        XCTAssertTrue(source.stopped, "a half-started tap is torn down")
        XCTAssertTrue(MicOnlyReason.unavailable("x").offersFix)
        XCTAssertFalse(MicOnlyReason.settingOff.offersFix)
        XCTAssertEqual(CaptureStateLine(mode: selection.mode, systemAudioLost: false), .micOnlyPermissionOff)
    }

    func testAStartedTapRecordsBothSides() {
        let source = FakeSource()
        let selection = CaptureModeSelector.select(settingOn: true, consentCurrent: true) { source }
        XCTAssertEqual(selection.mode, .micAndSystem)
        XCTAssertTrue(selection.source === source)
        XCTAssertFalse(source.stopped)
        XCTAssertEqual(CaptureStateLine(mode: .micAndSystem, systemAudioLost: false), .micAndCall)
        XCTAssertEqual(CaptureStateLine(mode: .micAndSystem, systemAudioLost: true), .callAudioLost)
        XCTAssertEqual(CaptureStateLine(mode: .micOnly(.settingOff), systemAudioLost: false), .micOnly)
        XCTAssertEqual(CaptureStateLine(mode: .micOnly(.consentNeeded), systemAudioLost: false),
                       .micOnlyConsentNeeded)
    }

    func testTheMonoFormatIsUnchangedAndTheDualOneHasTwoChannels() {
        XCTAssertEqual(RecordingFormat.flac.fileSettings[AVNumberOfChannelsKey] as? Int, 1)
        XCTAssertEqual(RecordingFormat.wav.fileSettings[AVNumberOfChannelsKey] as? Int, 1)
        XCTAssertEqual(RecordingFormat.flac.withChannels(2).fileSettings[AVNumberOfChannelsKey] as? Int, 2)
        XCTAssertEqual(RecordingFormat.flac.withChannels(2).contentType, "audio/flac")
        XCTAssertEqual(RecordingFormat.wav.withChannels(2).fileExtension, "wav")
    }

    // MARK: - Consent

    func testConsentIsPerVersion() throws {
        let suite = "s31-consent-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let consent = CallAudioConsent(defaults: defaults)
        XCTAssertFalse(consent.isCurrent)
        XCTAssertFalse(consent.needsRenewal)

        consent.accept(at: Date(timeIntervalSince1970: 1_790_000_000))
        XCTAssertTrue(consent.isCurrent)
        XCTAssertNotNil(defaults.object(forKey: CallAudioConsent.acceptedAtKey))

        // An older accepted version (as after the constant is raised) asks again.
        defaults.set(CallAudioConsent.currentVersion - 1, forKey: CallAudioConsent.versionKey)
        XCTAssertFalse(consent.isCurrent)
    }

    // MARK: - Upload fields

    func testChannelLayoutIsOnlyDeclaredForATwoChannelFile() throws {
        XCTAssertNil(ChannelLayout.field(channelCount: 1))
        XCTAssertNil(ChannelLayout.field(channelCount: nil))
        XCTAssertNil(ChannelLayout.field(channelCount: 3))
        XCTAssertEqual(ChannelLayout.field(channelCount: 2), "mic_system")

        let mono = try writeWav(channels: 1)
        let stereo = try writeWav(channels: 2)
        XCTAssertNil(ChannelLayout.field(forFileAt: mono))
        XCTAssertEqual(ChannelLayout.field(forFileAt: stereo), "mic_system")
        XCTAssertNil(ChannelLayout.field(forFileAt: scratch.appending(path: "missing.flac")))
    }

    func testTheLocalSpeakerNameIsOmittedWhenEmpty() {
        let none = APIClient.jobFields(language: "auto", diarize: true, speakersExpected: nil,
                                       channelLayout: nil, localSpeakerName: "   ")
        XCTAssertFalse(none.contains { $0.0 == "local_speaker_name" })
        XCTAssertFalse(none.contains { $0.0 == "channel_layout" })
        let nilName = APIClient.jobFields(language: "auto", diarize: true, speakersExpected: nil)
        XCTAssertFalse(nilName.contains { $0.0 == "local_speaker_name" })

        let named = APIClient.jobFields(language: "auto", diarize: true, speakersExpected: nil,
                                        channelLayout: "mic_system", localSpeakerName: "  Volodymyr \n Pugachov ")
        XCTAssertTrue(named.contains { $0 == ("channel_layout", "mic_system") })
        XCTAssertTrue(named.contains { $0 == ("local_speaker_name", "Volodymyr Pugachov") })
        XCTAssertEqual(LocalSpeakerName.normalized(String(repeating: "a", count: 200))?.count, 80)
    }

    func testATwoChannelUploadCarriesBothFields() async throws {
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (202, Fixtures.json(["id": "job-1", "status": "queued"]), [:])
        }
        let stereo = try writeWav(channels: 2)
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        _ = try await client.submitJob(fileURL: stereo, contentType: "audio/wav", language: "auto", diarize: true,
                                       channelLayout: ChannelLayout.field(forFileAt: stereo),
                                       localSpeakerName: "Olena")
        let body = String(decoding: StubServer.requests(to: "/asr/jobs").last?.body ?? Data(), as: UTF8.self)
        XCTAssertTrue(body.contains("name=\"channel_layout\"\r\n\r\nmic_system\r\n"))
        XCTAssertTrue(body.contains("name=\"local_speaker_name\"\r\n\r\nOlena\r\n"))

        let mono = try writeWav(channels: 1)
        _ = try await client.submitJob(fileURL: mono, contentType: "audio/wav", language: "auto", diarize: true,
                                       channelLayout: ChannelLayout.field(forFileAt: mono),
                                       localSpeakerName: "")
        let plain = String(decoding: StubServer.requests(to: "/asr/jobs").last?.body ?? Data(), as: UTF8.self)
        XCTAssertFalse(plain.contains("channel_layout"), "a mono file declares nothing")
        XCTAssertFalse(plain.contains("local_speaker_name"), "an empty name is omitted")
    }

    func testARefusedLayoutIsRetriedAsMono() async throws {
        let calls = LayoutCallCount()
        StubServer.install { request in
            if request.path == "/auth/refresh" { return (200, Fixtures.authenticated(), [:]) }
            return calls.next() == 0
                ? (422, Fixtures.json(["title": "Unprocessable", "status": 422, "detail": "x",
                                       "code": "channel_layout_mismatch"]), [:])
                : (202, Fixtures.json(["id": "job-1", "status": "queued"]), [:])
        }
        let stereo = try writeWav(channels: 2)
        let job = try await makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
            .submitJob(fileURL: stereo, contentType: "audio/wav", language: "auto", diarize: true,
                       channelLayout: "mic_system", localSpeakerName: "Olena")
        XCTAssertEqual(job.id, "job-1")
        let bodies = StubServer.requests(to: "/asr/jobs").map { String(decoding: $0.body ?? Data(), as: UTF8.self) }
        XCTAssertEqual(bodies.count, 2)
        XCTAssertTrue(bodies[0].contains("channel_layout"))
        XCTAssertFalse(bodies[1].contains("channel_layout"))
        XCTAssertTrue(bodies[1].contains("local_speaker_name"))
    }

    // MARK: - Kept recordings

    func testANewSidecarKeepsTheFieldsAndAnOldOneStillDecodes() throws {
        let pending = scratch.appending(path: "pending")
        let recording = try writeWav(channels: 2)
        var info = PendingCapture.Info(title: "Call", language: "auto", diarize: true,
                                       recordedAt: Date(timeIntervalSince1970: 1_790_000_000),
                                       identityId: "id-1", tenantId: "t-1")
        info.channelLayout = "mic_system"
        info.localSpeakerName = "Olena"
        let kept = try XCTUnwrap(PendingCaptures.keep(recording, info: info, in: pending))
        let object = try JSONSerialization.jsonObject(
            with: Data(contentsOf: kept.deletingPathExtension().appendingPathExtension("json"))) as! [String: Any]
        XCTAssertEqual(object["channel_layout"] as? String, "mic_system")
        XCTAssertEqual(object["local_speaker_name"] as? String, "Olena")
        let listed = try XCTUnwrap(PendingCaptures.all(in: pending).first)
        XCTAssertEqual(listed.info.channelLayout, "mic_system")
        XCTAssertEqual(listed.info.localSpeakerName, "Olena")
        XCTAssertEqual(listed.info.uploadChannelLayout(for: listed.audioURL), "mic_system")

        let old = try JSONDecoder.pending.decode(PendingCapture.Info.self, from: Data("""
        {"title":"Old","language":"auto","diarize":true,
         "recorded_at":"2026-09-01T09:00:00Z","identity_id":"id-1","speakers_expected":2}
        """.utf8))
        XCTAssertNil(old.channelLayout)
        XCTAssertNil(old.localSpeakerName)
        XCTAssertEqual(old.speakersExpected, 2)
    }

    func testARetryDeclaresTheLayoutOnlyWhileTheFileHasTwoChannels() throws {
        var info = PendingCapture.Info(title: "Call", language: "auto", diarize: true,
                                       recordedAt: Date(), identityId: "id-1", tenantId: nil)
        info.channelLayout = "mic_system"
        XCTAssertNil(info.uploadChannelLayout(for: try writeWav(channels: 1)))
        XCTAssertEqual(info.uploadChannelLayout(for: try writeWav(channels: 2)), "mic_system")
        info.channelLayout = nil
        XCTAssertNil(info.uploadChannelLayout(for: try writeWav(channels: 2)), "a mono capture never declares one")
    }

    private func writeWav(channels: Int) throws -> URL {
        let url = scratch.appending(path: "\(UUID().uuidString).wav")
        let format = RecordingFormat.wav.withChannels(channels)
        let file = try AVAudioFile(forWriting: url, settings: format.fileSettings)
        let buffer = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: 160)!
        buffer.frameLength = 160
        try file.write(from: buffer)
        return url
    }

    // MARK: - Roster markers

    func testTheSideGlyphComesFromSpeakerSides() {
        let sides = ["SPEAKER_1": "local", "SPEAKER_2": "remote", "SPEAKER_3": "sideways"]
        XCTAssertEqual(SpeakerChannelMarkers.side(of: "SPEAKER_1", in: sides), .local)
        XCTAssertEqual(SpeakerChannelMarkers.side(of: "SPEAKER_2", in: sides), .remote)
        XCTAssertNil(SpeakerChannelMarkers.side(of: "SPEAKER_3", in: sides), "an unknown value shows nothing")
        XCTAssertNil(SpeakerChannelMarkers.side(of: "SPEAKER_1", in: [:]), "mono jobs show nothing")
        XCTAssertEqual(SpeakerSide.local.symbol, "mic.fill")
        XCTAssertEqual(SpeakerSide.local.accessibilityLabel, "On your microphone")
        XCTAssertEqual(SpeakerSide.remote.accessibilityLabel, "On the call audio")
    }

    func testOnlyAChannelSourcedNameGetsTheMarker() {
        let sources = ["SPEAKER_1": "channel", "SPEAKER_2": "picklist"]
        XCTAssertTrue(SpeakerChannelMarkers.isChannelNamed("SPEAKER_1", sources: sources))
        XCTAssertFalse(SpeakerChannelMarkers.isChannelNamed("SPEAKER_2", sources: sources))
        XCTAssertFalse(SpeakerChannelMarkers.isChannelNamed("SPEAKER_3", sources: sources))
        XCTAssertEqual(SpeakerChannelMarkers.sources(sources, afterRenaming: "SPEAKER_1", sent: nil)["SPEAKER_1"],
                       "cleared")
        XCTAssertEqual(SpeakerChannelMarkers.sources(sources, afterRenaming: "SPEAKER_1", sent: .typed)["SPEAKER_1"],
                       "typed")
    }

    func testResultSidesAndSourcesDecodeAndOlderResultsStillDo() throws {
        let result = try JSONDecoder().decode(TranscriptResult.self, from: Data("""
        {"job_id":"j1","segments":[],
         "speaker_sides":{"SPEAKER_1":"local","SPEAKER_2":"remote"},
         "speaker_name_sources":{"SPEAKER_1":"channel"}}
        """.utf8))
        XCTAssertEqual(result.speakerSides, ["SPEAKER_1": "local", "SPEAKER_2": "remote"])
        XCTAssertEqual(result.speakerNameSources, ["SPEAKER_1": "channel"])
        let old = try JSONDecoder().decode(TranscriptResult.self, from: Data(#"{"job_id":"j1","segments":[]}"#.utf8))
        XCTAssertNil(old.speakerSides)
        XCTAssertNil(old.speakerNameSources)
    }

    @MainActor
    func testClearingAChannelNameSendsTheOtherNamesOnly() async throws {
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/asr/jobs/j31/result":
                return (200, Fixtures.json([
                    "job_id": "j31", "segments": [],
                    "turns": [["speaker": "SPEAKER_1", "start_ms": 0, "end_ms": 1000, "paragraphs": ["Hi"]],
                              ["speaker": "SPEAKER_2", "start_ms": 1000, "end_ms": 2000, "paragraphs": ["Hello"]]],
                    "speakers": ["SPEAKER_1", "SPEAKER_2"],
                    "speaker_names": ["SPEAKER_1": "Olena", "SPEAKER_2": "Anna"],
                    "speaker_sides": ["SPEAKER_1": "local", "SPEAKER_2": "remote"],
                    "speaker_name_sources": ["SPEAKER_1": "channel", "SPEAKER_2": "typed"],
                ]), [:])
            case "/asr/jobs/j31/speakers":
                return (200, Fixtures.json(["job_id": "j31", "speaker_names": ["SPEAKER_2": "Anna"]]), [:])
            default:
                return (200, Fixtures.json(["id": "j31", "status": "complete"]), [:])
            }
        }
        let model = NoteViewModel(noteId: "n1", jobId: "j31",
                                  api: makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession())))
        await model.loadTranscript()
        XCTAssertTrue(model.isChannelNamed("SPEAKER_1"))
        XCTAssertFalse(model.isChannelNamed("SPEAKER_2"))
        XCTAssertEqual(model.side(for: "SPEAKER_1"), .local)
        XCTAssertEqual(model.side(for: "SPEAKER_2"), .remote)

        await model.clearChannelName("SPEAKER_1")

        let put = try XCTUnwrap(StubServer.requests(to: "/asr/jobs/j31/speakers").last)
        XCTAssertEqual(put.method, "PUT")
        XCTAssertEqual(put.json()["names"] as? [String: String], ["SPEAKER_2": "Anna"],
                       "the label is removed, every other name kept")
        XCTAssertFalse(model.isChannelNamed("SPEAKER_1"), "the marker goes with the name")
        XCTAssertNotEqual(model.name(for: "SPEAKER_1"), "Olena")
        XCTAssertEqual(model.name(for: "SPEAKER_2"), "Anna")
    }
}

/// A `SystemAudioSource` that never touches hardware.
private final class FakeSource: SystemAudioSource {
    var onBuffers: ((AVAudioPCMBuffer, AVAudioPCMBuffer?) -> Void)?
    var onDeviceChange: (() -> Void)?
    var onFailure: ((Error) -> Void)?
    private let error: Error?
    private(set) var stopped = false

    init(error: Error? = nil) { self.error = error }

    func start() throws -> AudioStreamBasicDescription {
        if let error { throw error }
        return AudioStreamBasicDescription()
    }

    func stop() { stopped = true }
}

private final class LayoutCallCount: @unchecked Sendable {
    private let lock = NSLock()
    private var value = 0

    func next() -> Int {
        lock.lock()
        defer { lock.unlock() }
        defer { value += 1 }
        return value
    }
}
