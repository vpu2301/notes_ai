import AppKit
import Combine
import Foundation
import UserNotifications

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
        /// The microphone is off for this app in System Settings.
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
    /// window can show the live card for that meeting and nothing else.
    @Published private(set) var activeJobId: String?
    /// Set five minutes before the recording cap; cleared on the next start.
    @Published private(set) var limitWarning: String?
    /// True when the cap, not the person, stopped the last recording.
    @Published private(set) var stoppedAtLimit = false

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
        // object so views and the menu-bar label stay in sync.
        recorderSubscription = recorder.objectWillChange.sink { [weak self] _ in
            self?.objectWillChange.send()
        }
        recorder.onLimitWarning = { [weak self] in self?.limitApproaching() }
        recorder.onLimitReached = { [weak self] in self?.limitReached() }
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
        limitWarning = nil
        stoppedAtLimit = false
    }

    /// The one-click path: clear any finished state and start recording now.
    /// A title (say, from a calendar event) can be handed in.
    func startNew(title: String = "") {
        guard !recorder.isRecording, !phase.isBusy else { return }
        reset()
        self.title = title
        Task { await beginRecording() }
    }

    // MARK: - The recording cap

    private func limitApproaching() {
        let lead = formatElapsed(AudioRecorder.warningLead)
        limitWarning = "\(lead) left — recordings stop at \(formatLimit(recorder.limitSeconds)). Stop and start a new meeting to keep going."
        NSSound.beep()
        NSApp.requestUserAttention(.criticalRequest)
        notify(title: "5 minutes of recording left",
               body: "Recordings stop at \(formatLimit(recorder.limitSeconds)). Stop and start a new meeting to keep going.")
    }

    private func limitReached() {
        guard recorder.isRecording else { return }
        stoppedAtLimit = true
        limitWarning = nil
        finishRecording()
        NSSound.beep()
        notify(title: "Recording stopped at the \(formatLimit(recorder.limitSeconds)) limit",
               body: "The note is being drafted. Start a new meeting to keep recording.")
    }

    /// A system notification, when this process can post one: a bare
    /// `swift build` binary has no bundle and UNUserNotificationCenter
    /// would abort, so the in-app banner and the Dock bounce carry it then.
    private func notify(title: String, body: String) {
        guard Bundle.main.bundleIdentifier != nil else { return }
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { return }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            content.sound = .default
            center.add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
        }
    }

    // MARK: - Pipeline

    private func beginRecording() async {
        guard !phase.isBusy else { return }
        limitWarning = nil
        stoppedAtLimit = false
        // The cap as the server has it today; the fallback stands if the
        // call fails, and the server's own check still applies.
        if let limits = try? await app.api.asrLimits() {
            recorder.limitSeconds = TimeInterval(limits.maxDurationSeconds)
        }
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
        // The recording is deleted only once the server has it. Every other
        // exit from this function — a failed upload, a lost session, the
        // app being quit mid-pipeline — moves it to `pending/` with a
        // sidecar instead. A meeting cannot be recorded twice (IDX-M1 F).
        var uploaded = false
        let recordedAt = Date()
        defer {
            if uploaded {
                try? FileManager.default.removeItem(at: fileURL)
            } else {
                keep(fileURL, title: meetingTitle, recordedAt: recordedAt)
            }
        }
        var jobId: String?
        do {
            phase = .uploading
            let job = try await app.api.submitJob(fileURL: fileURL,
                                                  contentType: recorder.format.contentType,
                                                  language: language, diarize: diarize)
            uploaded = true
            jobId = job.id
            activeJobId = job.id
            app.addRecent(jobId: job.id, title: meetingTitle)
            if app.selection == nil { app.selection = .capture(jobId: job.id) }

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
            // Show the fresh note in the window unless the user is reading
            // another one there.
            if app.selection == nil || app.selection == .capture(jobId: job.id) {
                app.selection = .capture(jobId: job.id)
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

    /// Put the recording somewhere it will still be tomorrow, and say in
    /// the banner where it went — a file the person is not told about is
    /// only technically not lost.
    private func keep(_ fileURL: URL, title: String, recordedAt: Date) {
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return }
        let kept = PendingCaptures.keep(fileURL, info: PendingCapture.Info(
            title: title,
            language: language,
            diarize: diarize,
            recordedAt: recordedAt,
            identityId: app.identityId,
            tenantId: app.tenantId))
        guard kept != nil else { return }
        if case .failed(let message) = phase {
            phase = .failed(message + " The recording was kept on this Mac.")
        }
    }

    private static func defaultTitle() -> String {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return "Meeting \(formatter.string(from: Date()))"
    }
}
