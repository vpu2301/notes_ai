import Combine
import Foundation

/// Drives the capture pipeline: record → upload → poll → create note.
@MainActor
final class CaptureViewModel: ObservableObject {
    enum Phase: Equatable {
        case idle
        case recording
        case uploading
        case transcribing
        case creatingNote
        case done(noteId: String)
        case failed(String)
        /// The microphone is off for this app in Settings.
        case microphoneDenied

        var isBusy: Bool {
            switch self {
            case .uploading, .transcribing, .creatingNote: return true
            default: return false
            }
        }
    }

    /// Lets the recording decide its own language (the default).
    static let autoLanguage = "auto"

    @Published var title = ""
    /// "auto", or an ISO 639-1 code to pin the transcriber to.
    @Published var language: String {
        didSet { UserDefaults.standard.set(language, forKey: "captureLanguage") }
    }
    @Published var diarize: Bool {
        didSet { UserDefaults.standard.set(diarize, forKey: "captureDiarize") }
    }
    @Published private(set) var phase: Phase = .idle
    /// The ASR job of the capture being processed (or just finished), so the
    /// meeting page can show the live state for that meeting and nothing else.
    @Published private(set) var activeJobId: String?

    let recorder = AudioRecorder()
    private unowned let app: AppState
    private var recorderSubscription: AnyCancellable?
    private var pipelineTask: Task<Void, Never>?

    init(app: AppState) {
        self.app = app
        let defaults = UserDefaults.standard
        self.language = defaults.string(forKey: "captureLanguage") ?? Self.autoLanguage
        self.diarize = defaults.object(forKey: "captureDiarize") as? Bool ?? true
        // Re-publish the recorder's changes (level, elapsed) through this
        // object so every view stays in sync.
        recorderSubscription = recorder.objectWillChange.sink { [weak self] _ in
            self?.objectWillChange.send()
        }
    }

    var isRecording: Bool { recorder.isRecording }

    func toggleRecording() {
        if recorder.isRecording {
            finishRecording()
        } else {
            Task { await beginRecording() }
        }
    }

    func reset() {
        pipelineTask?.cancel()
        pipelineTask = nil
        phase = .idle
        activeJobId = nil
    }

    /// The one-tap path: clear any finished state and start recording now.
    /// A title (say, from a calendar event) can be handed in.
    func startNew(title: String = "") {
        guard !recorder.isRecording, !phase.isBusy else { return }
        reset()
        self.title = title
        Task { await beginRecording() }
    }

    // MARK: - Pipeline

    private func beginRecording() async {
        guard !phase.isBusy else { return }
        do {
            try await recorder.start()
            phase = .recording
        } catch RecorderError.permissionDenied {
            phase = .microphoneDenied
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }

    private func finishRecording() {
        guard let fileURL = recorder.stop() else {
            phase = .idle
            return
        }
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        let meetingTitle = trimmed.isEmpty ? Self.defaultTitle() : trimmed
        // The card and the list should agree on the name while it processes.
        title = meetingTitle
        pipelineTask = Task { await process(fileURL: fileURL, meetingTitle: meetingTitle) }
    }

    private func process(fileURL: URL, meetingTitle: String) async {
        defer { try? FileManager.default.removeItem(at: fileURL) }
        var jobId: String?
        do {
            phase = .uploading
            let job = try await app.api.submitJob(fileURL: fileURL,
                                                  contentType: recorder.format.contentType,
                                                  language: language, diarize: diarize)
            jobId = job.id
            activeJobId = job.id
            app.addRecent(jobId: job.id, title: meetingTitle)

            phase = .transcribing
            var current = job
            while !current.status.isTerminal {
                try await Task.sleep(for: .seconds(3))
                current = try await app.api.jobStatus(id: job.id)
                app.updateRecent(jobId: job.id, status: current.status)
            }
            guard current.status == .complete else {
                let message = current.failureText
                app.updateRecent(jobId: job.id, status: current.status, errorMessage: message)
                phase = .failed(message)
                return
            }

            phase = .creatingNote
            // The note follows the language the recording was actually in.
            let templateId = await app.meetingTemplateID(
                language: current.detectedLanguage ?? language)
            let note = try await app.api.createNoteFromTranscript(
                asrJobId: job.id, templateId: templateId, title: meetingTitle)
            app.updateRecent(jobId: job.id, status: .complete, noteId: note.id)
            phase = .done(noteId: note.id)
            title = ""
            // Open the fresh note unless the user is reading another one.
            if app.selection == nil || app.selection == .capture(jobId: job.id) {
                app.show(.capture(jobId: job.id))
            }
            await app.refreshNotes()
        } catch is CancellationError {
            // reset() was called; nothing to do.
        } catch {
            let message = error.localizedDescription
            if let jobId {
                app.updateRecent(jobId: jobId, errorMessage: message)
            }
            phase = .failed(message)
        }
    }

    private static func defaultTitle() -> String {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return "Meeting \(formatter.string(from: Date()))"
    }
}
