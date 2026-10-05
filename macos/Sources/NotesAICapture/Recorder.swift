import AVFoundation
import Foundation

enum RecorderError: LocalizedError, Equatable {
    case permissionDenied
    case noInputDevice
    case failedToStart

    var errorDescription: String? {
        switch self {
        case .permissionDenied:
            return "Microphone access is not allowed for Notes AI Capture. Turn it on in System Settings → Privacy & Security → Microphone, then try again."
        case .noInputDevice:
            return "No audio input device found — connect or select a microphone."
        case .failedToStart:
            return "Could not start recording — check your input device."
        }
    }
}

extension RecorderError {
    /// Deep link to the Microphone privacy pane.
    static let privacySettingsURL = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")!
}

/// Audio container the recorder writes. Both are in the ASR service's MIME
/// allow-list (`audio/mp4`/`.m4a` is not, and the service also verifies the
/// magic bytes, so the file really has to be one of these).
///
/// Sprint 31: plus a channel count — 1 (the microphone) as before, or 2 when
/// the call audio is recorded too (ch0 = microphone, ch1 = call audio).
struct RecordingFormat: Equatable, Sendable {
    enum Container: Equatable, Sendable {
        case flac
        case wav
    }

    var container: Container
    var channelCount: Int = 1

    static let flac = RecordingFormat(container: .flac)
    static let wav = RecordingFormat(container: .wav)

    func withChannels(_ count: Int) -> RecordingFormat {
        RecordingFormat(container: container, channelCount: count)
    }

    var fileExtension: String {
        switch container {
        case .flac: return "flac"
        case .wav: return "wav"
        }
    }

    var contentType: String {
        switch container {
        case .flac: return "audio/flac"
        case .wav: return "audio/wav"
        }
    }

    /// 16 kHz mono is what the speech models resample to anyway; it keeps a
    /// one-hour meeting well under the service's upload limit. Two channels
    /// only with call audio.
    var fileSettings: [String: Any] {
        switch container {
        case .flac:
            return [
                AVFormatIDKey: Int(kAudioFormatFLAC),
                AVSampleRateKey: 16_000,
                AVNumberOfChannelsKey: channelCount,
            ]
        case .wav:
            return [
                AVFormatIDKey: Int(kAudioFormatLinearPCM),
                AVSampleRateKey: 16_000,
                AVNumberOfChannelsKey: channelCount,
                AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsFloatKey: false,
                AVLinearPCMIsBigEndianKey: false,
            ]
        }
    }
}

/// What the current recording captures (Sprint 31).
enum CaptureMode: Equatable, Sendable {
    /// Microphone on ch0, call audio on ch1.
    case micAndSystem
    case micOnly(MicOnlyReason)

    var recordsSystemAudio: Bool { self == .micAndSystem }
}

/// Why a recording is microphone-only.
enum MicOnlyReason: Equatable, Sendable {
    /// "Record call audio" is off — today's behaviour.
    case settingOff
    /// The setting is on but the consent notice changed and was not
    /// accepted again yet.
    case consentNeeded
    /// Older than macOS 14.2: no process taps.
    case unsupportedOS
    /// The tap could not start — most likely the System Audio Recording
    /// permission is off. The message is for the log/UI, not a code.
    case unavailable(String)

    /// Whether the person can fix it in System Settings.
    var offersFix: Bool {
        if case .unavailable = self { return true }
        return false
    }
}

/// The fallback rule of `AudioRecorder.start`, as a pure function: try the
/// call audio only when it is wanted and possible, and fall back to the
/// microphone with a reason on anything else.
enum CaptureModeSelector {
    struct Selection {
        var mode: CaptureMode
        /// The started source (only for `.micAndSystem`).
        var source: SystemAudioSource?
        var format: AudioStreamBasicDescription?
    }

    static func select(settingOn: Bool, consentCurrent: Bool,
                       makeSource: () -> SystemAudioSource?) -> Selection {
        guard settingOn else { return Selection(mode: .micOnly(.settingOff)) }
        guard consentCurrent else { return Selection(mode: .micOnly(.consentNeeded)) }
        guard let source = makeSource() else { return Selection(mode: .micOnly(.unsupportedOS)) }
        do {
            let format = try source.start()
            return Selection(mode: .micAndSystem, source: source, format: format)
        } catch {
            source.stop()
            return Selection(mode: .micOnly(.unavailable(error.localizedDescription)))
        }
    }
}

/// Records mono 16 kHz FLAC (falling back to WAV) into a temporary file via
/// `AVAudioEngine`, publishing the elapsed time and a normalized input level
/// for the live meter.
///
/// `AVAudioRecorder` cannot encode FLAC, so the input tap is resampled with an
/// `AVAudioConverter` and written through `AVAudioFile` instead.
///
/// Sprint 31: with "Record call audio" on (and macOS 14.2+), the microphone
/// and the call audio come from one `SystemAudioSource` instead and the file
/// has two channels. Anything that stops that from starting falls back to
/// the mono path above, unchanged, with `captureMode` saying why.
@MainActor
final class AudioRecorder: ObservableObject {
    @Published private(set) var isRecording = false
    @Published private(set) var elapsed: TimeInterval = 0
    @Published private(set) var level: Double = 0
    /// Sprint 31: the call-audio level (0 while microphone-only).
    @Published private(set) var systemLevel: Double = 0
    /// What this recording captures; `.micOnly(.settingOff)` when idle.
    @Published private(set) var captureMode: CaptureMode = .micOnly(.settingOff)
    /// The call audio stopped mid-recording; the rest of ch1 is silence.
    @Published private(set) var systemAudioLost = false
    /// Sprint F1: milliseconds from the Record press to the first buffer
    /// written to the file; nil until that buffer arrives.
    @Published private(set) var firstFrameOffsetMs: Int?
    /// Sprint F1: the wall clock at the Record press (kept after `stop()`
    /// so the upload can carry it).
    private(set) var recordPressedAt: Date?
    /// The server's cap on one recording. The app reads the real value
    /// before each recording (`AsrLimits`); this is the fallback.
    @Published var limitSeconds: TimeInterval = 2 * 3600
    /// Seconds until the cap.
    var remaining: TimeInterval { max(0, limitSeconds - elapsed) }
    /// How far ahead of the cap the warning fires.
    static let warningLead: TimeInterval = 5 * 60
    /// Called once, `warningLead` before the cap, and once at the cap.
    var onLimitWarning: (() -> Void)?
    var onLimitReached: (() -> Void)?
    private var warned = false
    private var limitHit = false

    private(set) var fileURL: URL?
    private(set) var format: RecordingFormat = .flac

    private var engine: AVAudioEngine?
    private var meterTimer: Timer?
    private var startedAt: Date?
    private let sink = TapSink()
    /// Sprint 31: the microphone + call-audio source while it runs.
    private var systemSource: SystemAudioSource?
    /// Where call audio comes from; a test can swap it for a fake.
    var makeSystemAudioSource: () -> SystemAudioSource? = AudioRecorder.defaultSystemAudioSource

    nonisolated static func defaultSystemAudioSource() -> SystemAudioSource? {
        if #available(macOS 14.2, *) { return SystemAudioTap() }
        return nil
    }

    /// `captureSystemAudio`: the person's setting; `consentCurrent`: they
    /// accepted the current call-audio notice. Both false → exactly the
    /// microphone path of before.
    func start(captureSystemAudio: Bool = false, consentCurrent: Bool = false) async throws {
        // Sprint F1: the press, before any permission or tap setup — that
        // wait is exactly what the offset measures.
        recordPressedAt = Date()
        firstFrameOffsetMs = nil
        sink.firstFrame.reset()
        // A previously denied (or silently dropped — see scripts/make-app.sh)
        // grant never re-prompts; say so instead of failing quietly.
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .denied, .restricted:
            throw RecorderError.permissionDenied
        default:
            break
        }
        let granted = await AVCaptureDevice.requestAccess(for: .audio)
        guard granted else { throw RecorderError.permissionDenied }

        systemAudioLost = false
        systemLevel = 0
        let selection = CaptureModeSelector.select(
            settingOn: captureSystemAudio, consentCurrent: consentCurrent,
            makeSource: { [sink, weak self] in
                guard let source = self?.makeSystemAudioSource() else { return nil }
                // Wired before start: the first cycle must find a handler.
                source.onBuffers = { mic, system in sink.consume(mic: mic, system: system) }
                source.onFailure = { _ in
                    Task { @MainActor in self?.systemSourceFailed() }
                }
                return source
            })
        captureMode = selection.mode
        if let source = selection.source {
            do {
                try startDual(source: source)
                return
            } catch {
                source.stop()
                sink.finish()
                captureMode = .micOnly(.unavailable(error.localizedDescription))
            }
        }
        try startMono()
    }

    /// Microphone + call audio, two channels.
    private func startDual(source: SystemAudioSource) throws {
        let base = FileManager.default.temporaryDirectory
            .appendingPathComponent("NotesAICapture-\(UUID().uuidString)")
        let (file, url, format) = try Self.openOutputFile(base: base, channels: 2)
        sink.beginDual(file: file)
        systemSource = source
        commitStart(url: url, format: format)
    }

    /// Today's microphone-only path, unchanged.
    private func startMono() throws {
        let engine = AVAudioEngine()
        let input = engine.inputNode
        let inputFormat = input.outputFormat(forBus: 0)
        guard inputFormat.sampleRate > 0, inputFormat.channelCount > 0 else {
            throw RecorderError.noInputDevice
        }

        let base = FileManager.default.temporaryDirectory
            .appendingPathComponent("NotesAICapture-\(UUID().uuidString)")
        let (file, url, format) = try Self.openOutputFile(base: base)
        guard let converter = AVAudioConverter(from: inputFormat, to: file.processingFormat) else {
            throw RecorderError.failedToStart
        }

        sink.begin(file: file, converter: converter, inputFormat: inputFormat)
        input.installTap(onBus: 0, bufferSize: 4096, format: inputFormat) { [sink] buffer, _ in
            sink.consume(buffer)
        }

        engine.prepare()
        do {
            try engine.start()
        } catch {
            input.removeTap(onBus: 0)
            sink.finish()
            try? FileManager.default.removeItem(at: url)
            throw RecorderError.failedToStart
        }

        self.engine = engine
        commitStart(url: url, format: format)
    }

    private func commitStart(url: URL, format: RecordingFormat) {
        self.fileURL = url
        self.format = format
        self.startedAt = Date()
        self.elapsed = 0
        self.level = 0
        self.warned = false
        self.limitHit = false
        self.isRecording = true

        meterTimer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
    }

    /// The call-audio source gave up mid-recording (a device change it
    /// could not rebuild from, the tap invalidated). The file keeps its two
    /// channels: the microphone continues through `AVAudioEngine` into ch0
    /// and ch1 is silence from here on, flagged as lost.
    private func systemSourceFailed() {
        guard isRecording, systemSource != nil else { return }
        systemSource?.stop()
        systemSource = nil
        sink.markSystemLost()
        systemAudioLost = true

        let engine = AVAudioEngine()
        let input = engine.inputNode
        let inputFormat = input.outputFormat(forBus: 0)
        guard inputFormat.sampleRate > 0, inputFormat.channelCount > 0 else { return }
        input.installTap(onBus: 0, bufferSize: 4096, format: inputFormat) { [sink] buffer, _ in
            sink.consume(mic: buffer, system: nil)
        }
        engine.prepare()
        if (try? engine.start()) != nil {
            self.engine = engine
        } else {
            input.removeTap(onBus: 0)
        }
    }

    /// Sprint F1: the press and the first frame of the last recording, for
    /// the upload; nil when no buffer ever reached the file.
    var captureTiming: CaptureTiming? {
        CaptureTiming(pressedAt: recordPressedAt, firstFrameAt: sink.firstFrame.firstFrameAt)
    }

    /// Stops recording and returns the finished audio file.
    func stop() -> URL? {
        meterTimer?.invalidate()
        meterTimer = nil
        systemSource?.stop()
        systemSource = nil
        if let engine {
            engine.inputNode.removeTap(onBus: 0)
            engine.stop()
        }
        engine = nil
        sink.finish()  // releases the AVAudioFile → finalizes the container
        isRecording = false
        level = 0
        systemLevel = 0
        startedAt = nil
        return fileURL
    }

    private func tick() {
        guard isRecording, let startedAt else { return }
        elapsed = Date().timeIntervalSince(startedAt)
        level = sink.currentLevel()
        if firstFrameOffsetMs == nil, let timing = captureTiming {
            firstFrameOffsetMs = timing.firstFrameOffsetMs
        }
        if captureMode.recordsSystemAudio {
            systemLevel = sink.currentSystemLevel()
            if !systemAudioLost, sink.systemLost { systemAudioLost = true }
        }
        if !warned, remaining <= Self.warningLead {
            warned = true
            onLimitWarning?()
        }
        if !limitHit, elapsed >= limitSeconds {
            limitHit = true
            onLimitReached?()
        }
    }

    /// Prefer FLAC; if CoreAudio refuses to open a FLAC writer on this
    /// machine, fall back to 16-bit WAV (larger, but universally supported).
    private static func openOutputFile(base: URL, channels: Int = 1) throws -> (AVAudioFile, URL, RecordingFormat) {
        for format in [RecordingFormat.flac, .wav].map({ $0.withChannels(channels) }) {
            let url = base.appendingPathExtension(format.fileExtension)
            if let file = try? AVAudioFile(forWriting: url, settings: format.fileSettings) {
                return (file, url, format)
            }
            try? FileManager.default.removeItem(at: url)
        }
        throw RecorderError.failedToStart
    }
}

/// Receives input buffers on the audio thread, resamples them to the file's
/// processing format and appends them. Also keeps the latest RMS level for
/// the meter. Everything is guarded by a lock because the tap callback and
/// `start`/`stop` run on different threads.
///
/// Sprint 31: `beginDual`/`consume(mic:system:)` is the two-channel path —
/// each stream resampled to 16 kHz mono on its own converter, then
/// interleaved ch0 = microphone, ch1 = call audio. The mono path
/// (`begin`/`consume(_:)`) is untouched.
final class TapSink: @unchecked Sendable {
    private let lock = NSLock()
    private var file: AVAudioFile?
    private var converter: AVAudioConverter?
    private var ratio: Double = 1
    private var level: Double = 0
    // Two-channel state.
    private var dual = false
    private var micStream = MonoResampler()
    private var systemStream = MonoResampler()
    private var interleaver = ChannelInterleaver()
    private var systemLevel: Double = 0
    private var lost = false
    /// Sprint F1: when the first buffer was written to the file.
    let firstFrame = FirstFrameClock()

    func begin(file: AVAudioFile, converter: AVAudioConverter, inputFormat: AVAudioFormat) {
        lock.lock()
        defer { lock.unlock() }
        self.file = file
        self.converter = converter
        self.ratio = file.processingFormat.sampleRate / inputFormat.sampleRate
        self.level = 0
    }

    /// Start the two-channel path into `file` (2 channels, Float32
    /// processing format).
    func beginDual(file: AVAudioFile) {
        lock.lock()
        defer { lock.unlock() }
        self.file = file
        self.converter = nil
        self.dual = true
        let rate = file.processingFormat.sampleRate
        micStream = MonoResampler(outputRate: rate)
        systemStream = MonoResampler(outputRate: rate)
        interleaver = ChannelInterleaver(maxSkew: Int(rate))
        level = 0
        systemLevel = 0
        lost = false
    }

    func finish() {
        lock.lock()
        defer { lock.unlock() }
        if dual, let file {
            // What one stream is still ahead by, with the other side padded.
            write(interleaver.flush(), to: file)
        }
        file = nil
        converter = nil
        dual = false
        level = 0
        systemLevel = 0
    }

    func currentLevel() -> Double {
        lock.lock()
        defer { lock.unlock() }
        return level
    }

    func currentSystemLevel() -> Double {
        lock.lock()
        defer { lock.unlock() }
        return systemLevel
    }

    /// The call audio stopped delivering at some point in this recording.
    var systemLost: Bool {
        lock.lock()
        defer { lock.unlock() }
        return lost
    }

    func markSystemLost() {
        lock.lock()
        defer { lock.unlock() }
        if dual { lost = true }
    }

    func consume(_ buffer: AVAudioPCMBuffer) {
        lock.lock()
        defer { lock.unlock() }
        guard let file, let converter else { return }

        level = Self.normalizedLevel(of: buffer)

        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 1024
        guard let output = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: capacity) else {
            return
        }
        var handedOver = false
        var error: NSError?
        let status = converter.convert(to: output, error: &error) { _, outStatus in
            if handedOver {
                outStatus.pointee = .noDataNow
                return nil
            }
            handedOver = true
            outStatus.pointee = .haveData
            return buffer
        }
        guard status != .error, output.frameLength > 0 else { return }
        if (try? file.write(from: output)) != nil { firstFrame.mark() }
    }

    /// One cycle of both streams. `system == nil` means the call audio did
    /// not deliver: ch1 gets digital silence for the microphone's length
    /// and the loss is flagged — the file stays valid and aligned.
    func consume(mic: AVAudioPCMBuffer, system: AVAudioPCMBuffer?) {
        lock.lock()
        defer { lock.unlock() }
        guard dual, let file else { return }

        level = Self.normalizedLevel(of: mic)
        let micSamples = micStream.convert(mic)
        if let system {
            systemLevel = Self.normalizedLevel(of: system)
            interleaver.append(mic: micSamples, system: systemStream.convert(system))
        } else {
            lost = true
            systemLevel = 0
            interleaver.append(mic: micSamples, system: nil)
        }
        write(interleaver.drain(), to: file)
    }

    private func write(_ frames: (mic: [Float], system: [Float]), to file: AVAudioFile) {
        let count = min(frames.mic.count, frames.system.count)
        guard count > 0,
              let output = AVAudioPCMBuffer(pcmFormat: file.processingFormat,
                                            frameCapacity: AVAudioFrameCount(count)),
              let channels = output.floatChannelData,
              output.format.channelCount == 2
        else { return }
        output.frameLength = AVAudioFrameCount(count)
        var written = false
        defer { if written { firstFrame.mark() } }
        if output.format.isInterleaved {
            for i in 0..<count {
                channels[0][2 * i] = frames.mic[i]
                channels[0][2 * i + 1] = frames.system[i]
            }
        } else {
            frames.mic.withUnsafeBufferPointer { channels[0].update(from: $0.baseAddress!, count: count) }
            frames.system.withUnsafeBufferPointer { channels[1].update(from: $0.baseAddress!, count: count) }
        }
        written = (try? file.write(from: output)) != nil
    }

    /// RMS of the first channel mapped from roughly -50…0 dBFS to 0…1.
    static func normalizedLevel(of buffer: AVAudioPCMBuffer) -> Double {
        guard let data = buffer.floatChannelData, buffer.frameLength > 0 else { return 0 }
        let frames = Int(buffer.frameLength)
        var sum: Float = 0
        for i in 0..<frames {
            let sample = data[0][i]
            sum += sample * sample
        }
        let rms = (sum / Float(frames)).squareRoot()
        let db = 20 * log10(max(Double(rms), 1e-7))
        return max(0, min(1, (db + 50) / 50))
    }
}

/// One stream resampled to mono Float32 at the file's rate. The converter
/// is rebuilt when the input format changes (a new device after AirPods
/// connect can run at another rate).
struct MonoResampler {
    private(set) var outputRate: Double = 16_000
    private var converter: AVAudioConverter?
    private var inputFormat: AVAudioFormat?

    init(outputRate: Double = 16_000) {
        self.outputRate = outputRate
    }

    mutating func convert(_ buffer: AVAudioPCMBuffer) -> [Float] {
        guard buffer.frameLength > 0,
              let outFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: outputRate,
                                            channels: 1, interleaved: false)
        else { return [] }
        if inputFormat != buffer.format || converter == nil {
            converter = AVAudioConverter(from: buffer.format, to: outFormat)
            inputFormat = buffer.format
        }
        guard let converter else { return [] }
        let ratio = outputRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 1024
        guard let output = AVAudioPCMBuffer(pcmFormat: outFormat, frameCapacity: capacity) else { return [] }
        var handedOver = false
        var error: NSError?
        let status = converter.convert(to: output, error: &error) { _, outStatus in
            if handedOver {
                outStatus.pointee = .noDataNow
                return nil
            }
            handedOver = true
            outStatus.pointee = .haveData
            return buffer
        }
        guard status != .error, output.frameLength > 0, let data = output.floatChannelData?[0] else { return [] }
        return Array(UnsafeBufferPointer(start: data, count: Int(output.frameLength)))
    }
}

/// Pairs the two resampled streams frame by frame. Both come from one
/// clock, so they arrive in step; the resamplers may still hand out a few
/// frames more on one side in a given cycle, which is held until the other
/// side catches up. A side that falls more than `maxSkew` frames behind is
/// padded with silence so the file keeps moving and the channels never
/// drift further apart than that.
struct ChannelInterleaver {
    private(set) var pendingMic: [Float] = []
    private(set) var pendingSystem: [Float] = []
    var maxSkew = 16_000

    init(maxSkew: Int = 16_000) {
        self.maxSkew = maxSkew
    }

    /// `system == nil`: the call audio did not deliver — silence covering
    /// the microphone frames.
    mutating func append(mic: [Float], system: [Float]?) {
        pendingMic += mic
        if let system {
            pendingSystem += system
        } else if pendingSystem.count < pendingMic.count {
            pendingSystem += [Float](repeating: 0, count: pendingMic.count - pendingSystem.count)
        }
    }

    /// The frames both sides have, in order.
    mutating func drain() -> (mic: [Float], system: [Float]) {
        if pendingMic.count - pendingSystem.count > maxSkew {
            pendingSystem += [Float](repeating: 0, count: pendingMic.count - pendingSystem.count)
        } else if pendingSystem.count - pendingMic.count > maxSkew {
            pendingMic += [Float](repeating: 0, count: pendingSystem.count - pendingMic.count)
        }
        let n = min(pendingMic.count, pendingSystem.count)
        let out = (Array(pendingMic.prefix(n)), Array(pendingSystem.prefix(n)))
        pendingMic.removeFirst(n)
        pendingSystem.removeFirst(n)
        return out
    }

    /// Everything, the shorter side padded with silence.
    mutating func flush() -> (mic: [Float], system: [Float]) {
        let n = max(pendingMic.count, pendingSystem.count)
        pendingMic += [Float](repeating: 0, count: n - pendingMic.count)
        pendingSystem += [Float](repeating: 0, count: n - pendingSystem.count)
        return drain()
    }
}

/// "2 hours" / "90 minutes" — the cap, the way a person says it.
func formatLimit(_ seconds: TimeInterval) -> String {
    let minutes = Int(seconds / 60)
    if minutes % 60 == 0 {
        let hours = minutes / 60
        return hours == 1 ? "1 hour" : "\(hours) hours"
    }
    return "\(minutes) minutes"
}
