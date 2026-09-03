import AVFoundation
import Foundation
import UIKit

enum RecorderError: LocalizedError, Equatable {
    case permissionDenied
    case noInputDevice
    case failedToStart

    var errorDescription: String? {
        switch self {
        case .permissionDenied:
            return "Microphone access is off for Notes AI. Turn it on in Settings → Notes AI → Microphone, then try again."
        case .noInputDevice:
            return "No microphone is available right now."
        case .failedToStart:
            return "Could not start recording — try again."
        }
    }
}

extension RecorderError {
    /// The app's own page in the Settings app (microphone switch and all).
    static let settingsURL = URL(string: UIApplication.openSettingsURLString)!
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
/// `AVAudioConverter` and written through `AVAudioFile` instead. The audio
/// session is `.playAndRecord` and the app declares the `audio` background
/// mode, so a recording keeps going when the phone is locked or another app
/// is in front. A phone call interrupts it; the engine is restarted when the
/// call ends and the recording simply misses those minutes.
@MainActor
final class AudioRecorder: ObservableObject {
    @Published private(set) var isRecording = false
    @Published private(set) var elapsed: TimeInterval = 0
    @Published private(set) var level: Double = 0
    /// True while a call or Siri has the microphone.
    @Published private(set) var interrupted = false

    private(set) var fileURL: URL?
    private(set) var format: RecordingFormat = .flac

    private var engine: AVAudioEngine?
    private var meterTimer: Timer?
    private var startedAt: Date?
    private var observers: [NSObjectProtocol] = []
    private let sink = TapSink()

    func start() async throws {
        // A denied grant never re-prompts; say so instead of failing quietly.
        if AVAudioApplication.shared.recordPermission == .denied {
            throw RecorderError.permissionDenied
        }
        let granted = await AVAudioApplication.requestRecordPermission()
        guard granted else { throw RecorderError.permissionDenied }

        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.playAndRecord, mode: .default,
                                    options: [.allowBluetoothHFP, .defaultToSpeaker])
            try session.setActive(true, options: [])
        } catch {
            throw RecorderError.failedToStart
        }

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
        self.interrupted = false
        self.isRecording = true
        observeSession()

        meterTimer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
    }

    /// Stops recording and returns the finished audio file.
    func stop() -> URL? {
        meterTimer?.invalidate()
        meterTimer = nil
        for observer in observers { NotificationCenter.default.removeObserver(observer) }
        observers = []
        if let engine {
            engine.inputNode.removeTap(onBus: 0)
            engine.stop()
        }
        engine = nil
        sink.finish()  // releases the AVAudioFile → finalizes the container
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        isRecording = false
        interrupted = false
        level = 0
        startedAt = nil
        return fileURL
    }

    private func tick() {
        guard isRecording, let startedAt else { return }
        elapsed = Date().timeIntervalSince(startedAt)
        level = interrupted ? 0 : sink.currentLevel()
    }

    // MARK: - Interruptions & route changes

    private func observeSession() {
        let center = NotificationCenter.default
        observers.append(center.addObserver(
            forName: AVAudioSession.interruptionNotification, object: nil, queue: .main
        ) { [weak self] notification in
            guard let raw = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                  let type = AVAudioSession.InterruptionType(rawValue: raw) else { return }
            let shouldResume = (notification.userInfo?[AVAudioSessionInterruptionOptionKey] as? UInt)
                .map { AVAudioSession.InterruptionOptions(rawValue: $0).contains(.shouldResume) } ?? true
            Task { @MainActor in
                switch type {
                case .began: self?.interrupted = true
                case .ended: if shouldResume { self?.resume() }
                @unknown default: break
                }
            }
        })
        // AirPods in, headset out: the input format may change under the
        // tap, so it is re-installed against the new format.
        observers.append(center.addObserver(
            forName: .AVAudioEngineConfigurationChange, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.resume() }
        })
    }

    private func resume() {
        guard isRecording, let engine else { return }
        let input = engine.inputNode
        input.removeTap(onBus: 0)
        let inputFormat = input.outputFormat(forBus: 0)
        guard inputFormat.sampleRate > 0, inputFormat.channelCount > 0,
              let converter = sink.converter(for: inputFormat) else { return }
        sink.rebind(converter: converter, inputFormat: inputFormat)
        input.installTap(onBus: 0, bufferSize: 4096, format: inputFormat) { [sink] buffer, _ in
            sink.consume(buffer)
        }
        try? AVAudioSession.sharedInstance().setActive(true, options: [])
        if (try? engine.start()) != nil {
            interrupted = false
        }
    }

    /// Prefer FLAC; if CoreAudio refuses to open a FLAC writer on this
    /// device, fall back to 16-bit WAV (larger, but universally supported).
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

    /// A converter from a new input format to the open file's format.
    func converter(for inputFormat: AVAudioFormat) -> AVAudioConverter? {
        lock.lock()
        defer { lock.unlock() }
        guard let file else { return nil }
        return AVAudioConverter(from: inputFormat, to: file.processingFormat)
    }

    /// Keep the file, swap the converter (a route change mid-recording).
    func rebind(converter: AVAudioConverter, inputFormat: AVAudioFormat) {
        lock.lock()
        defer { lock.unlock() }
        guard let file else { return }
        self.converter = converter
        self.ratio = file.processingFormat.sampleRate / inputFormat.sampleRate
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
