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
    /// Where the current capture started and what its calendar event knew; manual by default.
    @Published private(set) var context: CaptureContext = .manual
    /// "My notes": what the author types WHILE the meeting runs; autosaved and kept verbatim.
    @Published var myNotes = "" {
        didSet { if myNotes != oldValue { notesChanged() } }
    }
    /// Picks the template family the note is written into. Per meeting, not a preference.
    @Published var meetingType: MeetingType = .auto
    /// The note this capture is typing into, once the server has opened one.
    @Published private(set) var noteId: String?
    /// True while typed text has not reached the server.
    @Published private(set) var notesUnsaved = false

    /// Idempotency key: the same capture retried or resumed anywhere is ONE note.
    private var clientCaptureId = UUID().uuidString
    /// Recording t=0, the origin for every line's offset.
    private var recordingStartedAt = Date()
    private var lineTimes: [String: Int] = [:]
    /// Line times the server has not acknowledged yet.
    private var unsentLineTimes: [String: Int] = [:]
    private var noteContent: NoteContent?
    private var noteVersion = 0
    private var saveTask: Task<Void, Never>?
    private var persistTask: Task<Void, Never>?
    /// The invite's people and agenda, kept for a note created later (offline at Record).
    private var meetingCalendar: MeetingCalendarContext?
    /// The workspace's names and terms, fetched at start and sent with the upload. Never waited for.
    private var vocabularyHint: String?
    @Published private(set) var phase: Phase = .idle
    /// The ASR job of the capture being processed (or just finished).
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
        // Re-publish the recorder's changes through this object.
        recorderSubscription = recorder.objectWillChange.sink { [weak self] _ in
            self?.objectWillChange.send()
        }
        recorder.onLimitWarning = { [weak self] in self?.limitApproaching() }
        recorder.onLimitReached = { [weak self] in self?.limitReached() }
    }

    var isRecording: Bool { recorder.isRecording }

    /// Sign-out: a picked calendar event does not outlive the session; a running recording keeps its context.
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
        saveTask?.cancel()
        persistTask?.cancel()
        phase = .idle
        activeJobId = nil
        limitWarning = nil
        stoppedAtLimit = false
        context = .manual
        // The next capture starts with a clean pad and a fresh idempotency key.
        myNotes = ""
        noteId = nil
        noteContent = nil
        noteVersion = 0
        notesUnsaved = false
        lineTimes.removeAll()
        unsentLineTimes.removeAll()
        meetingCalendar = nil
        vocabularyHint = nil
        clientCaptureId = UUID().uuidString
        // `meetingType` is deliberately NOT cleared: it is chosen before the next meeting.
    }

    /// The one-tap path: clear finished state, start recording, open the note
    /// beside it. The recorder goes first: a failed note is recoverable at stop, a lost recording is not.
    func startNew(title: String = "", context: CaptureContext = .manual,
                  calendar: MeetingCalendarContext? = nil,
                  meetingType: MeetingType? = nil) {
        guard !recorder.isRecording, !phase.isBusy else { return }
        let chosen = meetingType ?? self.meetingType
        reset()
        self.title = title
        self.context = context
        self.meetingCalendar = calendar
        self.meetingType = chosen
        self.recordingStartedAt = Date()
        Task {
            await beginRecording()
            guard case .recording = phase else { return }
            // Both are beside the recording, never in front of it.
            vocabularyHint = try? await app.api.glossaryHint().hint
            await openMeetingNote()
        }
    }

    /// Upload an existing file through the same pipeline, with no live note.
    /// The file is copied first: a security-scoped picker URL is not ours to keep.
    func uploadFile(_ picked: URL) {
        guard !recorder.isRecording, !phase.isBusy else { return }
        let scoped = picked.startAccessingSecurityScopedResource()
        defer { if scoped { picked.stopAccessingSecurityScopedResource() } }
        let copy = FileManager.default.temporaryDirectory
            .appending(path: "upload-\(UUID().uuidString).\(picked.pathExtension.isEmpty ? "audio" : picked.pathExtension)")
        do {
            try FileManager.default.copyItem(at: picked, to: copy)
        } catch {
            phase = .failed("That file could not be read.")
            return
        }
        reset()
        let name = picked.deletingPathExtension().lastPathComponent.trimmingCharacters(in: .whitespaces)
        title = name.isEmpty ? Self.defaultTitle() : name
        let tenantId = app.tenantId
        pipelineTask = Task {
            vocabularyHint = try? await app.api.glossaryHint().hint
            await process(fileURL: copy, meetingTitle: title, tenantId: tenantId, context: .upload,
                          contentType: Self.contentType(of: copy))
        }
    }

    /// The MIME type a picked file is uploaded as.
    nonisolated static func contentType(of url: URL) -> String {
        switch url.pathExtension.lowercased() {
        case "wav": return "audio/wav"
        case "m4a", "mp4", "aac": return "audio/mp4"
        case "mp3": return "audio/mpeg"
        case "ogg", "oga", "opus": return "audio/ogg"
        case "webm": return "audio/webm"
        case "caf": return "audio/x-caf"
        case "aiff", "aif": return "audio/aiff"
        default: return "audio/flac"
        }
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
        // The server's cap today; the fallback stands if the call fails.
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
        // Read now — the next recording resets it.
        let timing = recorder.captureTiming
        // Whatever was typed in the last second goes with the meeting.
        Task { await saveNotesNow() }
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        let meetingTitle = trimmed.isEmpty ? Self.defaultTitle() : trimmed
        // The card and the list should agree on the name while it processes.
        title = meetingTitle
        // The workspace as of recording start: switching mid-meeting must not re-file it.
        let tenantId = boundTenantId ?? app.tenantId
        boundTenantId = nil
        // The context belongs to this recording; the next one starts manual.
        let context = self.context
        self.context = .manual
        pipelineTask = Task {
            await process(fileURL: fileURL, meetingTitle: meetingTitle, tenantId: tenantId, context: context,
                          timing: timing)
        }
    }

    /// The workspace the current recording belongs to, captured when it started.
    private var boundTenantId: String?

    private func process(fileURL: URL, meetingTitle: String, tenantId: String?,
                         context: CaptureContext, timing: CaptureTiming? = nil,
                         contentType: String? = nil) async {
        // Deleted only once the server has it; every other exit moves it to `pending/` with a sidecar.
        var uploaded = false
        let recordedAt = Date()
        defer {
            if uploaded {
                try? FileManager.default.removeItem(at: fileURL)
            } else {
                keep(fileURL, title: meetingTitle, recordedAt: recordedAt, tenantId: tenantId,
                     context: context, timing: timing)
            }
        }
        do {
            phase = .uploading
            let job = try await app.api.submitJob(fileURL: fileURL,
                                                  contentType: contentType ?? recorder.format.contentType,
                                                  language: language, diarize: diarize,
                                                  speakersExpected: speakersExpected,
                                                  context: context,
                                                  vocabularyHint: vocabularyHint,
                                                  captureTiming: timing,
                                                  tenantId: tenantId)
            uploaded = true
            activeJobId = job.id
            // Recording and typed note are one meeting from here on.
            await attachRecording(jobId: job.id)
            app.addRecent(jobId: job.id, title: meetingTitle)
            await follow(job, meetingTitle: meetingTitle, language: language)
        } catch is CancellationError {
            // reset() was called; nothing to do.
        } catch {
            phase = .failed(AuthCopy.message(for: error))
        }
    }

    /// Poll a job already on the server and draft its note; a retried recording joins here.
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
            // When the live note exists the transcript goes INTO it; a second note would split the meeting.
            var finishedNoteId: String?
            if let live = noteId {
                // Idempotent for the same pair; matters only when the bind after upload failed.
                _ = try? await app.api.attachMeetingJob(noteId: live, asrJobId: job.id)
                do {
                    _ = try await app.api.attachTranscript(noteId: live)
                    PendingMeetingNotes.remove(clientCaptureId)
                    finishedNoteId = live
                } catch APIError.http(status: 404, problem: _) {
                    // The live note was binned mid-meeting: the recording gets a fresh note.
                    forgetNote(live)
                }
            }
            if finishedNoteId == nil {
                // The note follows the language the recording was actually in.
                let templateId = await app.meetingTemplateID(
                    language: current.detectedLanguage ?? language)
                finishedNoteId = try await app.api.createNoteFromTranscript(
                    asrJobId: job.id, templateId: templateId, title: meetingTitle).id
            }
            guard let finishedNoteId else { return }
            app.updateRecent(jobId: job.id, status: .complete, noteId: finishedNoteId)
            phase = .done(noteId: finishedNoteId)
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

    /// Keep the recording in `pending/` and say so in the banner.
    private func keep(_ fileURL: URL, title: String, recordedAt: Date, tenantId: String?,
                      context: CaptureContext, timing: CaptureTiming? = nil) {
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
        info.captureTiming = timing
        let kept = PendingCaptures.keep(fileURL, info: info)
        // The typing is kept whatever happened to the audio.
        persistNow()
        guard kept != nil else { return }
        app.refreshPending()
        if case .failed(let message) = phase {
            phase = .failed(message + " The recording was kept on this phone.")
        }
    }

    // MARK: - My notes (Sprint 34)

    /// Recording position in milliseconds; line offsets use this clock, not the wall's.
    private var elapsedMs: Int {
        max(0, Int(Date().timeIntervalSince(recordingStartedAt) * 1000))
    }

    /// The live note is gone: unbind so autosave stops and Stop drafts a fresh
    /// note; the pad stays. New idempotency key, since the old one answers with the trashed note.
    func forgetNote(_ id: String) {
        guard noteId == id else { return }
        noteId = nil
        noteContent = nil
        noteVersion = 0
        PendingMeetingNotes.remove(clientCaptureId)
        clientCaptureId = UUID().uuidString
        if isRecording { persistNow() }
    }

    /// Open the note beside the recording. Never throws or blocks; on failure `attachRecording` opens it at stop.
    private func openMeetingNote() async {
        do {
            let created = try await app.api.startMeeting(
                clientCaptureId: clientCaptureId,
                title: title,
                startedAt: recordingStartedAt,
                language: language == Self.autoLanguage ? nil : language,
                meetingType: meetingType,
                calendar: meetingCalendar)
            noteId = created.id
            await loadNoteContent(created.id)
        } catch {
            // Offline or service down: the meeting matters more; typing is on disk.
            persistNow()
        }
    }

    /// Read the note back as the autosave baseline (and to pick up another device's typing).
    private func loadNoteContent(_ id: String) async {
        guard let env = try? await app.api.fetchNote(id: id), let content = env.content else { return }
        noteContent = content
        noteVersion = env.currentVersionNumber
        let remote = content.section(Self.userNotesSection).text ?? ""
        let merged = PendingMeetingNotes.merge(remote: remote, local: myNotes)
        if merged != myNotes { myNotes = merged }
    }

    /// The section every meeting template carries for the author's lines.
    static let userNotesSection = "user_notes"

    private func notesChanged() {
        notesUnsaved = true
        stampNewLines()
        persistTask?.cancel()
        persistTask = Task { [weak self] in
            // Debounced: a crash loses a sentence, not a meeting.
            try? await Task.sleep(for: .milliseconds(500))
            guard !Task.isCancelled else { return }
            self?.persistNow()
        }
        saveTask?.cancel()
        saveTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(900))
            guard !Task.isCancelled else { return }
            await self?.saveNotes()
        }
    }

    /// Give every line the author has just started its first-keystroke time.
    private func stampNewLines() {
        let at = elapsedMs
        for line in PendingMeetingNotes.lines(of: myNotes) {
            let key = MeetingLineKey.of(line)
            guard !key.isEmpty, lineTimes[key] == nil else { continue }
            lineTimes[key] = at
            unsentLineTimes[key] = at
        }
    }

    /// Write the scratchpad to disk. Synchronous and small: must survive a kill one line later.
    private func persistNow() {
        guard !myNotes.isEmpty || noteId != nil else { return }
        PendingMeetingNotes.save(PendingMeetingNote(
            clientCaptureId: clientCaptureId,
            noteId: noteId,
            title: title,
            language: language,
            meetingType: meetingType.rawValue,
            startedAt: recordingStartedAt,
            text: myNotes,
            lineTimes: lineTimes,
            calendar: meetingCalendar,
            identityId: app.identityId,
            tenantId: boundTenantId ?? app.tenantId,
            updatedAt: Date()))
    }

    /// Autosave into the note; only the author's section changes.
    private func saveNotes() async {
        guard let id = noteId, var content = noteContent else { return }
        let typed = myNotes
        var section = content.section(Self.userNotesSection)
        guard section.text != typed else {
            notesUnsaved = unsentLineTimes.isEmpty ? false : notesUnsaved
            await flushLineTimes(id)
            return
        }
        section.text = typed
        content.upsert(section)
        do {
            let res = try await app.api.updateDraft(id: id, content: content,
                                                    expectedVersion: noteVersion)
            noteContent = content
            noteVersion = res.versionNumber
            notesUnsaved = false
            persistNow()
        } catch {
            // Conflict = another device wrote: re-read and merge. Anything else retries on the next key.
            await loadNoteContent(id)
        }
        await flushLineTimes(id)
    }

    private func flushLineTimes(_ id: String) async {
        guard !unsentLineTimes.isEmpty else { return }
        let batch = unsentLineTimes.map { UserLineTime(lineKey: $0.key, offsetMs: $0.value) }
        do {
            try await app.api.putLineTimes(noteId: id, lines: batch)
            unsentLineTimes.removeAll()
        } catch {
            // Timings are a hint; keep them for the next flush.
        }
    }

    /// Append one line to "My notes" from outside the editor, stamped like a typed line.
    func appendQuickNote(_ line: String) {
        let text = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        myNotes = myNotes.isEmpty ? text : "\(myNotes)\n\(text)"
    }

    /// Save now — at Stop, and before the app goes away.
    func saveNotesNow() async {
        saveTask?.cancel()
        persistTask?.cancel()
        persistNow()
        await saveNotes()
    }

    /// Bind the recording to the note, opening it first if `start` could not.
    private func attachRecording(jobId: String) async {
        if noteId == nil { await openMeetingNote() }
        guard let id = noteId else { return }
        await saveNotes()
        _ = try? await app.api.attachMeetingJob(noteId: id, asrJobId: jobId)
        persistNow()
    }

    /// Replay everything typed offline. Safe to repeat: note creation is idempotent, line times first-wins.
    func syncPendingMeetingNotes() async {
        for pending in PendingMeetingNotes.all(identityId: app.identityId) {
            // The capture in front of the user right now is not "pending".
            guard pending.clientCaptureId != clientCaptureId || !isRecording else { continue }
            guard await syncOne(pending) else { continue }
            PendingMeetingNotes.remove(pending.clientCaptureId)
        }
    }

    private func syncOne(_ pending: PendingMeetingNote) async -> Bool {
        var id = pending.noteId
        if id == nil {
            guard let created = try? await app.api.startMeeting(
                clientCaptureId: pending.clientCaptureId,
                title: pending.title,
                startedAt: pending.startedAt,
                language: pending.language == Self.autoLanguage ? nil : pending.language,
                meetingType: MeetingType(rawValue: pending.meetingType) ?? .auto,
                calendar: pending.calendar)
            else { return false }
            id = created.id
        }
        guard let id,
              let env = try? await app.api.fetchNote(id: id),
              var content = env.content
        else { return false }
        var section = content.section(Self.userNotesSection)
        let merged = PendingMeetingNotes.merge(remote: section.text ?? "", local: pending.text)
        if merged != (section.text ?? "") {
            section.text = merged
            content.upsert(section)
            guard (try? await app.api.updateDraft(id: id, content: content,
                                                  expectedVersion: env.currentVersionNumber)) != nil
            else { return false }
        }
        try? await app.api.putLineTimes(noteId: id, lines: pending.pendingLineTimes)
        return true
    }

    private static func defaultTitle() -> String {
        "\(placeholderPrefix)\(placeholderFormatter().string(from: Date()))"
    }

    /// Whether `title` is a `defaultTitle()` placeholder (today's or the recording day's).
    nonisolated static func isPlaceholderTitle(_ title: String) -> Bool {
        guard title.hasPrefix(placeholderPrefix) else { return false }
        let rest = String(title.dropFirst(placeholderPrefix.count))
        return placeholderFormatter().date(from: rest) != nil
    }

    private nonisolated static let placeholderPrefix = "Meeting "

    private nonisolated static func placeholderFormatter() -> DateFormatter {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter
    }
}

/// The capture screen's "People" choice. Auto and 6+ send no hint; a choice
/// rather than `Int?` so "6+" survives a relaunch.
enum PeopleCount: String, CaseIterable, Hashable, Sendable {
    case auto
    case one = "1", two = "2", three = "3", four = "4", five = "5"
    case sixPlus = "6+"

    var label: String { self == .auto ? "Auto" : rawValue }

    /// `speakers_expected` for the upload, or nil for none.
    var speakersExpected: Int? { Int(rawValue) }
}
