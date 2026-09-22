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
    /// Sprint 34 — "My notes": what the author types WHILE the meeting runs.
    /// The highest-value signal there is about what mattered in the room, so
    /// it is the note itself from the first second: autosaved, on every
    /// device, and kept verbatim by everything downstream.
    @Published var myNotes = "" {
        didSet { if myNotes != oldValue { notesChanged() } }
    }
    /// Picks the template family the note is written into. Per meeting, not
    /// a preference: the next one is probably a different kind.
    @Published var meetingType: MeetingType = .auto
    /// The note this capture is typing into, once the server has opened one.
    @Published private(set) var noteId: String?
    /// True while typed text has not reached the server.
    @Published private(set) var notesUnsaved = false

    /// Idempotency key: the same capture retried, resumed offline or picked
    /// up on a second device is ONE note.
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
    /// The invite's people and agenda for this capture, kept so a note
    /// created later (offline at Record) still opens with them.
    private var meetingCalendar: MeetingCalendarContext?
    /// Sprint 35 — the workspace's names and terms, fetched when the
    /// recording starts and sent with the upload so the transcriber has
    /// the spellings before it guesses. A capture never waits for it.
    private var vocabularyHint: String?
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
        saveTask?.cancel()
        persistTask?.cancel()
        phase = .idle
        activeJobId = nil
        limitWarning = nil
        stoppedAtLimit = false
        context = .manual
        // A finished capture's notes are the server's now; the next one
        // starts with a clean pad and a fresh idempotency key.
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
        // `meetingType` is deliberately NOT cleared: it is chosen before
        // the next meeting starts, and most people's meetings come in
        // runs of the same kind.
    }

    /// The one-tap path: clear any finished state and start recording now.
    /// A title (say, from a calendar event) can be handed in.
    ///
    /// Sprint 30: a capture started from a calendar event hands in its
    /// `context` (the invitees as a cap and as names to offer); everything
    /// else is `.manual`.
    ///
    /// Sprint 34: it also OPENS THE NOTE, so there is somewhere to type the
    /// moment the meeting starts. The recorder goes first and the note is
    /// opened beside it — a note we failed to create is recoverable at
    /// stop, a meeting we failed to record is not.
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
        // Whatever was typed in the last second goes with the meeting.
        Task { await saveNotesNow() }
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
                                                  vocabularyHint: vocabularyHint,
                                                  tenantId: tenantId)
            uploaded = true
            activeJobId = job.id
            // The recording and the note the author typed in are one
            // meeting from here on.
            await attachRecording(jobId: job.id)
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
            // Sprint 34: when the note already exists — the author has been
            // typing in it since Record — the transcript goes INTO it. A
            // second note would split the meeting in two.
            var finishedNoteId: String?
            if let live = noteId {
                // Idempotent for the same pair: this only matters when the
                // bind after upload failed, and it beats a `no_job` refusal.
                _ = try? await app.api.attachMeetingJob(noteId: live, asrJobId: job.id)
                do {
                    _ = try await app.api.attachTranscript(noteId: live)
                    PendingMeetingNotes.remove(clientCaptureId)
                    finishedNoteId = live
                } catch APIError.http(status: 404, problem: _) {
                    // The live note was moved to the bin while the meeting
                    // ran (it looked empty). The recording is not in the
                    // bin: it gets a fresh note, like an upload would.
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
        // The typing is kept whatever happened to the audio.
        persistNow()
        guard kept != nil else { return }
        app.refreshPending()
        if case .failed(let message) = phase {
            phase = .failed(message + " The recording was kept on this phone.")
        }
    }

    // MARK: - My notes (Sprint 34)

    /// Where the recording is now, in milliseconds. The line offsets are in
    /// this clock, not the wall's.
    private var elapsedMs: Int {
        max(0, Int(Date().timeIntervalSince(recordingStartedAt) * 1000))
    }

    /// The note this capture was typing into is gone (moved to the bin
    /// here, on another device, or found missing at Stop). Unbind it so
    /// autosave stops writing into a 404 and Stop drafts a fresh note; the
    /// typed text stays on the pad. A new idempotency key, because
    /// `startMeeting` for the old one answers with the trashed note.
    func forgetNote(_ id: String) {
        guard noteId == id else { return }
        noteId = nil
        noteContent = nil
        noteVersion = 0
        PendingMeetingNotes.remove(clientCaptureId)
        clientCaptureId = UUID().uuidString
        if isRecording { persistNow() }
    }

    /// Open the note beside the recording. Never throws and never blocks:
    /// when it fails the capture keeps running and `attachRecording` opens
    /// the note at stop instead.
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
            // Offline, or the service is down. The meeting matters more;
            // what is typed is on disk either way.
            persistNow()
        }
    }

    /// Read the note back so autosave has a baseline to write into — and so
    /// text typed on another device shows up here rather than being
    /// overwritten by this one.
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
            // Debounced so a fast typist does not write the file per key;
            // short enough that a crash loses a sentence, not a meeting.
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

    /// Write the scratchpad to disk. Synchronous and small — this is the
    /// call that has to survive the app being killed one line later.
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

    /// Autosave into the note. The author's text goes in whole; every other
    /// section is left exactly as it was.
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
            // A conflict means another device wrote: re-read and merge
            // rather than overwrite. Anything else retries on the next key.
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
            // Timings are a hint: a line that never gets one still anchors
            // by its words. Keep them for the next flush and move on.
        }
    }

    /// Append one line to "My notes" from somewhere that is not the editor
    /// — the menu-bar quick field. It is stamped with the moment it was
    /// written, exactly like a line typed in the window.
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

    /// Bind the recording to the note, opening the note first if `start`
    /// could not. A capture never ends without one.
    private func attachRecording(jobId: String) async {
        if noteId == nil { await openMeetingNote() }
        guard let id = noteId else { return }
        await saveNotes()
        _ = try? await app.api.attachMeetingJob(noteId: id, asrJobId: jobId)
        persistNow()
    }

    /// Everything typed offline, replayed. Called when a session comes back
    /// and at launch; safe to call repeatedly, because creating the note is
    /// idempotent on `clientCaptureId` and a line time is first-wins.
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

    /// Whether `title` is the placeholder `defaultTitle()` made — today or
    /// on the day a kept recording was made — rather than one a person typed.
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
