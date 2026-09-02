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

        var isBusy: Bool {
            switch self {
            case .uploading, .transcribing, .creatingNote: return true
            default: return false
            }
        }
    }

    @Published var title = ""
    @Published var language = "en"
    @Published var diarize = true
    @Published private(set) var phase: Phase = .idle

    let recorder = AudioRecorder()
    private unowned let app: AppState
    private var recorderSubscription: AnyCancellable?
    private var pipelineTask: Task<Void, Never>?

    init(app: AppState) {
        self.app = app
        // Re-publish the recorder's changes (level, elapsed) through this
        // object so views and the menu-bar label stay in sync.
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
    }

    // MARK: - Pipeline

    private func beginRecording() async {
        guard !phase.isBusy else { return }
        do {
            try await recorder.start()
            phase = .recording
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
        pipelineTask = Task { await process(fileURL: fileURL, meetingTitle: meetingTitle) }
    }

    private func process(fileURL: URL, meetingTitle: String) async {
        defer { try? FileManager.default.removeItem(at: fileURL) }
        var jobId: String?
        do {
            phase = .uploading
            let job = try await app.api.submitJob(fileURL: fileURL, language: language, diarize: diarize)
            jobId = job.id
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
            let templateId = await app.meetingTemplateID(language: language)
            let note = try await app.api.createNoteFromTranscript(
                asrJobId: job.id, templateId: templateId, title: meetingTitle)
            app.updateRecent(jobId: job.id, status: .complete, noteId: note.id)
            phase = .done(noteId: note.id)
            title = ""
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
