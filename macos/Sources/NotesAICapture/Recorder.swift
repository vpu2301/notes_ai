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
enum RecordingFormat {
    case flac
    case wav

    var fileExtension: String {
        switch self {
        case .flac: return "flac"
        case .wav: return "wav"
        }
    }

    var contentType: String {
        switch self {
        case .flac: return "audio/flac"
        case .wav: return "audio/wav"
        }
    }

    /// 16 kHz mono is what the speech models resample to anyway; it keeps a
    /// one-hour meeting well under the service's upload limit.
    var fileSettings: [String: Any] {
        switch self {
        case .flac:
            return [
                AVFormatIDKey: Int(kAudioFormatFLAC),
                AVSampleRateKey: 16_000,
                AVNumberOfChannelsKey: 1,
            ]
        case .wav:
            return [
                AVFormatIDKey: Int(kAudioFormatLinearPCM),
                AVSampleRateKey: 16_000,
                AVNumberOfChannelsKey: 1,
                AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsFloatKey: false,
                AVLinearPCMIsBigEndianKey: false,
            ]
        }
    }
}

/// Records mono 16 kHz FLAC (falling back to WAV) into a temporary file via
/// `AVAudioEngine`, publishing the elapsed time and a normalized input level
/// for the live meter.
///
/// `AVAudioRecorder` cannot encode FLAC, so the input tap is resampled with an
/// `AVAudioConverter` and written through `AVAudioFile` instead.
@MainActor
final class AudioRecorder: ObservableObject {
    @Published private(set) var isRecording = false
    @Published private(set) var elapsed: TimeInterval = 0
    @Published private(set) var level: Double = 0

    private(set) var fileURL: URL?
    private(set) var format: RecordingFormat = .flac

    private var engine: AVAudioEngine?
    private var meterTimer: Timer?
    private var startedAt: Date?
    private let sink = TapSink()

    func start() async throws {
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
        self.fileURL = url
        self.format = format
        self.startedAt = Date()
        self.elapsed = 0
        self.level = 0
        self.isRecording = true

        meterTimer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
    }

    /// Stops recording and returns the finished audio file.
    func stop() -> URL? {
        meterTimer?.invalidate()
        meterTimer = nil
        if let engine {
            engine.inputNode.removeTap(onBus: 0)
            engine.stop()
        }
        engine = nil
        sink.finish()  // releases the AVAudioFile → finalizes the container
        isRecording = false
        level = 0
        startedAt = nil
        return fileURL
    }

    private func tick() {
        guard isRecording, let startedAt else { return }
        elapsed = Date().timeIntervalSince(startedAt)
        level = sink.currentLevel()
    }

    /// Prefer FLAC; if CoreAudio refuses to open a FLAC writer on this
    /// machine, fall back to 16-bit WAV (larger, but universally supported).
    private static func openOutputFile(base: URL) throws -> (AVAudioFile, URL, RecordingFormat) {
        for format in [RecordingFormat.flac, .wav] {
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
private final class TapSink: @unchecked Sendable {
    private let lock = NSLock()
    private var file: AVAudioFile?
    private var converter: AVAudioConverter?
    private var ratio: Double = 1
    private var level: Double = 0

    func begin(file: AVAudioFile, converter: AVAudioConverter, inputFormat: AVAudioFormat) {
        lock.lock()
        defer { lock.unlock() }
        self.file = file
        self.converter = converter
        self.ratio = file.processingFormat.sampleRate / inputFormat.sampleRate
        self.level = 0
    }

    func finish() {
        lock.lock()
        defer { lock.unlock() }
        file = nil
        converter = nil
        level = 0
    }

    func currentLevel() -> Double {
        lock.lock()
        defer { lock.unlock() }
        return level
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
        try? file.write(from: output)
    }

    /// RMS of the first channel mapped from roughly -50…0 dBFS to 0…1.
    private static func normalizedLevel(of buffer: AVAudioPCMBuffer) -> Double {
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
