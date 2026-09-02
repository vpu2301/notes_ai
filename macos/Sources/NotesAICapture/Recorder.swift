import AVFoundation
import Foundation

enum RecorderError: LocalizedError {
    case permissionDenied
    case failedToStart

    var errorDescription: String? {
        switch self {
        case .permissionDenied:
            return "Microphone access was denied. Allow it in System Settings → Privacy & Security → Microphone."
        case .failedToStart:
            return "Could not start recording — check your input device."
        }
    }
}

/// Records mono AAC (.m4a) into a temporary file, publishing the elapsed
/// time and a normalized input level for the live meter.
@MainActor
final class AudioRecorder: ObservableObject {
    @Published private(set) var isRecording = false
    @Published private(set) var elapsed: TimeInterval = 0
    @Published private(set) var level: Double = 0

    private var recorder: AVAudioRecorder?
    private var meterTimer: Timer?
    private(set) var fileURL: URL?

    func start() async throws {
        let granted = await AVCaptureDevice.requestAccess(for: .audio)
        guard granted else { throw RecorderError.permissionDenied }

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("NotesAICapture-\(UUID().uuidString).m4a")
        let settings: [String: Any] = [
            AVFormatIDKey: Int(kAudioFormatMPEG4AAC),
            AVSampleRateKey: 44_100,
            AVNumberOfChannelsKey: 1,
            AVEncoderAudioQualityKey: AVAudioQuality.high.rawValue,
        ]
        let recorder = try AVAudioRecorder(url: url, settings: settings)
        recorder.isMeteringEnabled = true
        guard recorder.record() else { throw RecorderError.failedToStart }

        self.recorder = recorder
        self.fileURL = url
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
        recorder?.stop()
        recorder = nil
        isRecording = false
        level = 0
        return fileURL
    }

    private func tick() {
        guard let recorder, recorder.isRecording else { return }
        recorder.updateMeters()
        elapsed = recorder.currentTime
        // averagePower is in dBFS (-160…0); map the useful -50…0 range to 0…1.
        let power = Double(recorder.averagePower(forChannel: 0))
        level = max(0, min(1, (power + 50) / 50))
    }
}
