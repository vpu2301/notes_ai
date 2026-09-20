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
    /// "People": how many speakers the person says are in the meeting.
    @Published var people: PeopleCount {
        didSet { UserDefaults.standard.set(people.rawValue, forKey: "capturePeople") }
    }
    /// The hint the upload carries: an exact number, and only when speakers
    /// are being told apart at all.
    var speakersExpected: Int? { diarize ? people.speakersExpected : nil }
    /// Sprint 30: where the current capture started and what its calendar
    /// event knew (invitee cap, names to offer). Manual unless a capture
    /// was started from an upcoming event.
    @Published private(set) var context: CaptureContext = .manual
    @Published private(set) var phase: Phase = .idle
    /// The ASR job of the capture being processed (or just finished), so the
    /// meeting page can show the live state for that meeting and nothing else.
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
        self.people = defaults.string(forKey: "capturePeople").flatMap(PeopleCount.init(rawValue:)) ?? .auto
        // Re-publish the recorder's changes (level, elapsed) through this
        // object so every view stays in sync.
        recorderSubscription = recorder.objectWillChange.sink { [weak self] _ in
            self?.objectWillChange.send()
        }
        recorder.onLimitWarning = { [weak self] in self?.limitApproaching() }
        recorder.onLimitReached = { [weak self] in self?.limitReached() }
    }

    var isRecording: Bool { recorder.isRecording }

    /// Sign-out (Sprint 32): a calendar event picked for the next capture —
    /// its invitees' names — does not outlive the session. A recording in
    /// progress keeps the context it was started with.
    func forgetContext() {
        guard !isRecording else { return }
        context = .manual
    }

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
        context = .manual
    }

    /// The one-tap path: clear any finished state and start recording now.
    /// A title (say, from a calendar event) can be handed in.
    ///
    /// Sprint 30: a capture started from a calendar event hands in its
    /// `context` (the invitees as a cap and as names to offer); everything
    /// else is `.manual`.
    func startNew(title: String = "", context: CaptureContext = .manual) {
        guard !recorder.isRecording, !phase.isBusy else { return }
        reset()
        self.title = title
        self.context = context
        Task { await beginRecording() }
    }

    // MARK: - The recording cap

    private func limitApproaching() {
        let lead = formatElapsed(AudioRecorder.warningLead)
        limitWarning = "\(lead) left — recordings stop at \(formatLimit(recorder.limitSeconds)). Stop and start a new meeting to keep going."
        notify(title: "5 minutes of recording left",
               body: "Recordings stop at \(formatLimit(recorder.limitSeconds)). Stop and start a new meeting to keep going.")
    }

    private func limitReached() {
        guard recorder.isRecording else { return }
        stoppedAtLimit = true
        limitWarning = nil
        finishRecording()
        notify(title: "Recording stopped at the \(formatLimit(recorder.limitSeconds)) limit",
               body: "The note is being drafted. Start a new meeting to keep recording.")
    }

    /// A local notification, so the phone in a pocket still says so.
    private func notify(title: String, body: String) {
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
            boundTenantId = app.tenantId
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
        // The workspace as it was when the recording started, not as it is
        // when the upload finally goes out: switching workspaces during a
        // meeting must not re-file the meeting (IDX-I2 G).
        let tenantId = boundTenantId ?? app.tenantId
        boundTenantId = nil
        // The context belongs to this recording; the next one starts manual.
        let context = self.context
        self.context = .manual
        pipelineTask = Task {
            await process(fileURL: fileURL, meetingTitle: meetingTitle, tenantId: tenantId, context: context)
        }
    }

    /// The workspace the current recording belongs to, captured when it
    /// started.
    private var boundTenantId: String?

    private func process(fileURL: URL, meetingTitle: String, tenantId: String?,
                         context: CaptureContext) async {
        // The recording is deleted only once the server has it. Every other
        // exit from this function — a failed upload, a lost session, the
        // app being killed mid-pipeline — moves it to `pending/` with a
        // sidecar instead. A meeting cannot be recorded twice (IDX-I1 F).
        var uploaded = false
        let recordedAt = Date()
        defer {
            if uploaded {
                try? FileManager.default.removeItem(at: fileURL)
            } else {
                keep(fileURL, title: meetingTitle, recordedAt: recordedAt, tenantId: tenantId,
                     context: context)
            }
        }
        do {
            phase = .uploading
            let job = try await app.api.submitJob(fileURL: fileURL,
                                                  contentType: recorder.format.contentType,
                                                  language: language, diarize: diarize,
                                                  speakersExpected: speakersExpected,
                                                  context: context,
                                                  tenantId: tenantId)
            uploaded = true
            activeJobId = job.id
            app.addRecent(jobId: job.id, title: meetingTitle)
            await follow(job, meetingTitle: meetingTitle, language: language)
        } catch is CancellationError {
            // reset() was called; nothing to do.
        } catch {
            phase = .failed(AuthCopy.message(for: error))
        }
    }

    /// Poll a job that is already on the server and draft its note.
    ///
    /// Split out of `process` because a retried recording (IDX-I2) joins
    /// the pipeline here: the upload has happened, the file is gone, and
    /// what is left is the same waiting and the same note.
    func follow(jobId: String, title meetingTitle: String, language: String) async {
        activeJobId = jobId
        guard let job = try? await app.api.jobStatus(id: jobId) else {
            phase = .transcribing
            return
        }
        pipelineTask = Task { await follow(job, meetingTitle: meetingTitle, language: language) }
        await pipelineTask?.value
    }

    private func follow(_ job: TranscriptionJob, meetingTitle: String, language: String) async {
        do {
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
            let message = AuthCopy.message(for: error)
            app.updateRecent(jobId: job.id, errorMessage: message)
            phase = .failed(message)
        }
    }

    /// Put the recording somewhere it will still be there tomorrow, and
    /// say in the banner where it went — a file the person is not told
    /// about is only technically not lost.
    private func keep(_ fileURL: URL, title: String, recordedAt: Date, tenantId: String?,
                      context: CaptureContext) {
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return }
        var info = PendingCapture.Info(
            title: title,
            language: language,
            diarize: diarize,
            recordedAt: recordedAt,
            identityId: app.identityId,
            tenantId: tenantId ?? app.tenantId,
            speakersExpected: speakersExpected)
        info.setCaptureContext(context)
        let kept = PendingCaptures.keep(fileURL, info: info)
        guard kept != nil else { return }
        app.refreshPending()
        if case .failed(let message) = phase {
            phase = .failed(message + " The recording was kept on this phone.")
        }
    }

    private static func defaultTitle() -> String {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return "Meeting \(formatter.string(from: Date()))"
    }
}

/// The capture screen's "People" choice (Sprint 29). Auto and 6+ send no
/// hint — the diarizer counts; 1–5 is an exact number stated by a person.
/// Kept as a choice rather than an `Int?` so "6+" is still shown as picked
/// after a relaunch.
enum PeopleCount: String, CaseIterable, Hashable, Sendable {
    case auto
    case one = "1", two = "2", three = "3", four = "4", five = "5"
    case sixPlus = "6+"

    var label: String { self == .auto ? "Auto" : rawValue }

    /// `speakers_expected` for the upload, or nil for none.
    var speakersExpected: Int? { Int(rawValue) }
}
