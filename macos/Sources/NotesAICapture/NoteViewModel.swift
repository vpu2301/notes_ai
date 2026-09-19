import AppKit
import Foundation

/// One open note: the envelope, its template's sections, the editable
/// content with debounced autosave, the
/// transcript it came from, and PDF export. Mirrors the web editor page.
@MainActor
final class NoteViewModel: ObservableObject {
    enum SaveState: Equatable {
        case saved, dirty, saving, error

        var label: String {
            switch self {
            case .saved: return "Saved"
            case .dirty: return "Unsaved"
            case .saving: return "Saving…"
            case .error: return "Save failed"
            }
        }
    }

    enum Tab: Hashable { case notes, transcript }

    let noteId: String
    /// Given by the caller (a recording made here) or learnt from the
    /// note itself, so a note made elsewhere still opens its transcript.
    @Published private(set) var jobId: String?

    @Published private(set) var note: NoteEnvelope?
    @Published private(set) var sections: [TemplateSectionDef] = []
    /// The template's display name, for the note's meta line; nil when the
    /// template could not be read (deprecated, or not ours to see).
    @Published private(set) var templateName: String?
    @Published var content: NoteContent?
    @Published private(set) var version = 0
    @Published private(set) var saveState: SaveState = .saved
    @Published private(set) var conflict = false
    /// Set when this is not our note and nobody shared it with us — a
    /// workspace admin opening a colleague's note. Every read is then sent
    /// with this purpose (the server records it) and the screen says so.
    @Published private(set) var readPurpose: ReadPurpose?
    @Published private(set) var loadError: String?
    @Published private(set) var isLoading = true
    @Published private(set) var busy = false
    @Published var actionError: String?
    @Published var tab: Tab = .notes

    /// Sections whose text is the raw transcript (dialogue-shaped): shown
    /// behind the Transcript tab, never among the notes.
    var transcriptSections: [TemplateSectionDef] {
        sections.filter { TranscriptText.isTranscript(content?.section($0.id).text ?? "") }
    }
    var noteSections: [TemplateSectionDef] {
        let hidden = Set(transcriptSections.map(\.id))
        return sections.filter { !hidden.contains($0.id) }
    }
    /// The transcript as text turns, for a note without a readable job.
    var textTurns: [TranscriptText.Turn] {
        transcriptSections.flatMap { TranscriptText.turns(content?.section($0.id).text ?? "") }
    }
    var hasTranscript: Bool { jobId != nil || !transcriptSections.isEmpty }

    /// Who can see the note (0016); loaded lazily the first time the menu asks.
    @Published private(set) var sharing: SharingView?
    /// Set after a successful delete so the view can close itself.
    @Published private(set) var deleted = false
    @Published private(set) var turns: [TranscriptTurn]?
    /// Label → display name for the transcript's speakers (people's names
    /// where given, "Speaker N" elsewhere). Kept apart from `turns` so a
    /// rename repaints every turn of that speaker at once.
    @Published private(set) var speakerNames: [String: String] = [:]
    @Published private(set) var transcriptError: String?
    @Published private(set) var renamingSpeaker = false

    /// "Ask this note": the thread under the document. Lives here only —
    /// the server answers one question at a time and keeps nothing.
    @Published private(set) var chat: [ChatMessage] = []
    @Published private(set) var asking = false
    @Published var askError: String?

    struct ChatMessage: Identifiable, Equatable {
        let id = UUID()
        let role: AskTurn.Role
        let text: String
    }

    private let api: APIClient
    /// The autosave timer (cancelled and restarted on every edit).
    private var saveTask: Task<Void, Never>?
    /// The write on the wire, if one is running.
    private var saveInFlight: Task<Void, Never>?
    private var pending: (content: NoteContent, version: Int)?
    private static let autosaveDelay: Duration = .milliseconds(900)

    init(noteId: String, jobId: String?, api: APIClient) {
        self.noteId = noteId
        self.jobId = jobId
        self.api = api
    }

    /// A note is a living document (ADR-0051): editable until cancelled.
    var isDraft: Bool {
        guard let status = note?.status else { return false }
        return status != .cancelled
    }

    /// "Ada's note" — who this note belongs to, when it is not ours.
    var oversightLabel: String? {
        guard readPurpose != nil else { return nil }
        let name = note?.primaryAuthorName?.trimmingCharacters(in: .whitespaces) ?? ""
        return name.isEmpty ? "A colleague's note" : "\(name)'s note"
    }
    var editable: Bool { isDraft }

    // MARK: - Load

    func load() async {
        loadError = nil
        isLoading = note == nil
        do {
            let envelope: NoteEnvelope
            do {
                envelope = try await api.fetchNote(id: noteId)
                readPurpose = nil
            } catch let error as APIError where error.needsReadPurpose {
                // Not our note: read it as a reviewer, on the record.
                envelope = try await api.fetchNote(id: noteId, purpose: .review)
                readPurpose = .review
            }
            note = envelope
            content = envelope.content
            if jobId == nil, let job = envelope.sourceJobId { jobId = job }
            version = envelope.currentVersionNumber
            saveState = .saved
            conflict = false
            if let templateId = envelope.content?.templateId,
               let template = try? await api.fetchTemplate(id: templateId) {
                templateName = template.name
                sections = template.schemaJsonb.sections.sorted { ($0.order ?? 0) < ($1.order ?? 0) }
            } else {
                // Template unavailable: the envelope's labels as plain text sections.
                templateName = nil
                sections = (envelope.sectionLabels ?? []).map {
                    TemplateSectionDef(id: $0.sectionKey,
                                       name: $0.name["en"] ?? $0.name["uk"] ?? $0.sectionKey,
                                       fieldType: "free_text", required: nil, minChars: nil, order: nil)
                }
            }
        } catch {
            loadError = error.localizedDescription
        }
        isLoading = false
    }

    func loadTranscript() async {
        guard turns == nil, transcriptError == nil, let jobId else { return }
        do {
            let result = try await api.transcript(jobId: jobId)
            speakerNames = result.speakerNames ?? [:]
            turns = result.turns ?? []
        } catch {
            transcriptError = error.localizedDescription
        }
    }

    // MARK: - Speakers

    /// Whether the recording was diarized (anyone was told apart).
    var diarized: Bool { (turns ?? []).contains { $0.speaker != nil } }

    var speakerCount: Int { Set((turns ?? []).compactMap(\.speaker)).count }

    func displayName(for turn: TranscriptTurn) -> String {
        guard let label = turn.speaker else { return unknownSpeakerName }
        return speakerNames[label] ?? turn.name ?? defaultSpeakerName(label)
    }

    /// Rename a speaker everywhere: on the job (so the web app agrees), in
    /// this transcript, and — while the note is live — in the note body,
    /// whose turn lines start with the name. A cancelled note is a record;
    /// its text stays and only the transcript shows the new name.
    func renameSpeaker(label: String, to rawName: String) async {
        // Without a readable job the "label" is the name as it stands in
        // the note text; the rename rewrites the turn prefixes and the note
        // autosaves, so it is on the server either way.
        let textOnly = jobId == nil || transcriptError != nil
        let from = textOnly ? label : (speakerNames[label] ?? defaultSpeakerName(label))
        let trimmed = rawName.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        let to = trimmed.isEmpty ? (textOnly ? from : defaultSpeakerName(label)) : String(trimmed.prefix(80))
        guard to != from else { return }
        guard let jobId, !textOnly else {
            renameSpeakerInNote(from: from, to: to)
            return
        }

        // Only the names people gave are stored; defaults are implied.
        var custom = speakerNames.filter { $0.value != defaultSpeakerName($0.key) }
        if to == defaultSpeakerName(label) { custom.removeValue(forKey: label) } else { custom[label] = to }

        renamingSpeaker = true
        defer { renamingSpeaker = false }
        do {
            let stored = try await api.setSpeakerNames(jobId: jobId, names: custom)
            var merged: [String: String] = [:]
            for l in speakerNames.keys { merged[l] = stored[l] ?? defaultSpeakerName(l) }
            speakerNames = merged
            renameSpeakerInNote(from: from, to: merged[label] ?? to)
        } catch {
            actionError = error.localizedDescription
        }
    }

    private func renameSpeakerInNote(from: String, to: String) {
        guard editable, var next = content, let sections = next.sections else { return }
        next.sections = sections.map { section in
            guard let text = section.text, !text.isEmpty else { return section }
            var copy = section
            copy.text = Self.renameSpeaker(in: text, from: from, to: to)
            return copy
        }
        commit(next)
    }

    /// "Speaker 2: …" → "Olena: …" at the start of lines only — the
    /// from-transcript note puts the name at the head of each turn.
    static func renameSpeaker(in text: String, from: String, to: String) -> String {
        let pattern = "(^|\\n)" + NSRegularExpression.escapedPattern(for: from) + ": "
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return text }
        let template = "$1" + NSRegularExpression.escapedTemplate(for: to) + ": "
        return regex.stringByReplacingMatches(in: text, range: NSRange(text.startIndex..., in: text),
                                              withTemplate: template)
    }

    // MARK: - Ask this note

    /// The server sees the last few turns for context; it caps the thread.
    private static let historyLimit = 12

    func ask(_ question: String) async {
        let text = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !asking else { return }
        askError = nil
        let history = chat.suffix(Self.historyLimit).map { AskTurn(role: $0.role, text: $0.text) }
        chat.append(ChatMessage(role: .user, text: text))
        asking = true
        defer { asking = false }
        do {
            let reply = try await api.askNote(id: noteId, question: text, history: Array(history))
            chat.append(ChatMessage(role: .assistant, text: reply.answer))
        } catch {
            // The question stays in the thread so it can be retried by eye.
            askError = error.localizedDescription
        }
    }

    func clearChat() {
        chat = []
        askError = nil
    }

    // MARK: - Editing (drafts autosave; other states are read-only here)

    func setTitle(_ title: String) {
        guard var next = content else { return }
        next.title = title
        commit(next)
    }

    func setSectionText(_ key: String, _ text: String) {
        guard var next = content else { return }
        var section = next.section(key)
        section.text = text
        next.upsert(section)
        commit(next)
    }

    private func commit(_ next: NoteContent) {
        guard editable, next != content else { return }
        content = next
        pending = (next, version)
        saveState = .dirty
        saveTask?.cancel()
        saveTask = Task { [weak self] in
            try? await Task.sleep(for: Self.autosaveDelay)
            guard !Task.isCancelled else { return }
            await self?.flush()
        }
    }

    /// Write the pending content now.
    func flush() async {
        // Stop the timer. When flush() runs *inside* the timer task this
        // cancels the current task too, and a cancelled task makes
        // URLSession fail with "cancelled" before anything is sent — so the
        // write below runs in its own task, out of reach of that cancellation.
        saveTask?.cancel()
        saveTask = nil
        if let inFlight = saveInFlight { await inFlight.value }
        guard let snapshot = pending else { return }
        pending = nil
        saveState = .saving
        let write = Task { [weak self] in
            guard let self else { return }
            await self.write(snapshot)
        }
        saveInFlight = write
        await write.value
        if saveInFlight == write { saveInFlight = nil }
    }

    private func write(_ snapshot: (content: NoteContent, version: Int)) async {
        do {
            let result = try await api.updateDraft(id: noteId, content: snapshot.content,
                                                   expectedVersion: snapshot.version)
            version = result.versionNumber
            saveState = pending == nil ? .saved : .dirty
        } catch let error as APIError where error.isConflict {
            conflict = true
            saveState = .error
        } catch {
            saveState = .error
            actionError = error.localizedDescription
        }
    }

    /// Fetch the PDF and let the user pick where to keep it.
    func exportPDF() async {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            let data = try await api.notePDF(id: noteId, purpose: readPurpose == nil ? nil : .export)
            let panel = NSSavePanel()
            panel.nameFieldStringValue = "\(note?.code ?? "note").pdf"
            panel.allowedContentTypes = [.pdf]
            panel.canCreateDirectories = true
            NSApp.activate(ignoringOtherApps: true)
            if panel.runModal() == .OK, let url = panel.url {
                try data.write(to: url)
            }
        } catch {
            actionError = error.localizedDescription
        }
    }

    // MARK: - Delete, visibility, sharing (0016)

    func loadSharing() async {
        sharing = try? await api.sharing(id: noteId)
    }

    var isWorkspaceVisible: Bool {
        (sharing?.visibility ?? note?.visibility) == "workspace"
    }

    func setWorkspaceVisible(_ on: Bool) async {
        await sharingAction { try await self.api.setVisibility(id: self.noteId, visibility: on ? "workspace" : "private") }
    }

    /// The public "anyone with the link" URL, creating the link on first use.
    func publicLinkURL(webAppURL: String) async -> URL? {
        if sharing?.publicLink == nil {
            await sharingAction { try await self.api.createPublicLink(id: self.noteId) }
        }
        guard let path = sharing?.publicLink?.path,
              let root = URL(string: webAppURL.trimmingCharacters(in: .whitespaces)) else { return nil }
        return root.appending(path: String(path.dropFirst()))
    }

    func revokePublicLink() async {
        await sharingAction { try await self.api.revokePublicLink(id: self.noteId) }
    }

    // MARK: - Per-recipient links (Sprint 19)

    var recipientLinks: [LinkView] { sharing?.recipientLinks ?? [] }

    /// Sprint 23: the note's sharing view carries the workspace rules.
    var rules: SharingConstraints { sharing?.constraints ?? .permissive }

    /// Mint a link for one recipient and hand back its full URL, or nil
    /// when the call failed (the reason is on `actionError`).
    /// The last link the product mailed from this screen, for the sheet's notice.
    @Published var lastSent: LinkView?

    func createRecipientLink(label: String, email: String, expiresInDays: Int,
                             webAppURL: String, send: Bool = false, message: String = "",
                             source: String = "native") async -> URL? {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            let link = try await api.createLink(id: noteId, label: label,
                                                recipientEmail: email.isEmpty ? nil : email,
                                                expiresInDays: expiresInDays,
                                                mail: send, personalMessage: message, source: source)
            if send { lastSent = link }
            await loadSharing()
            guard let root = URL(string: webAppURL.trimmingCharacters(in: .whitespaces)) else { return nil }
            return root.appending(path: String(link.path.dropFirst()))
        } catch {
            actionError = error.localizedDescription
            return nil
        }
    }

    /// Sprint 22: mail (again). The outcome lands on the link row; a
    /// refusal (opted out, cap) is the error the sheet shows.
    func sendLink(_ link: LinkView, message: String = "") async {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            lastSent = try await api.sendLink(id: noteId, linkId: link.id, personalMessage: message)
            await loadSharing()
        } catch APIError.http(_, let problem) where problem?.code == "recipient_opted_out" {
            actionError = "This recipient asked not to receive e-mails. Copy the link instead."
            await loadSharing()
        } catch {
            actionError = error.localizedDescription
        }
    }

    func revokeLink(_ link: LinkView) async {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            try await api.revokeLink(id: noteId, linkId: link.id)
            await loadSharing()
        } catch {
            actionError = error.localizedDescription
        }
    }


    // MARK: - Action items + recipient responses (Sprint 20)

    @Published private(set) var items: [ActionItem] = []
    @Published private(set) var responses: [ItemResponse] = []

    /// Items are derived from the note text on read. Read-only cache: nothing
    /// user-authored lives here, so nothing can be lost offline.
    func loadItems() async {
        guard isDraft else {
            items = []
            responses = []
            return
        }
        async let i = api.items(noteId: noteId)
        async let r = api.responses(noteId: noteId)
        items = (try? await i) ?? []
        responses = (try? await r) ?? []
    }

    var liveDisputes: Int { responses.filter { $0.kind == .dispute && $0.clearedAt == nil }.count }

    /// Optimistic; reverts on failure.
    func setStatus(_ item: ActionItem, _ status: ActionItemStatus) async {
        guard let idx = items.firstIndex(where: { $0.id == item.id }) else { return }
        let before = items[idx].status
        items[idx].status = status
        actionError = nil
        do {
            items[idx] = try await api.setItemStatus(noteId: noteId, itemId: item.id, status: status)
        } catch {
            items[idx].status = before
            actionError = error.localizedDescription
        }
    }

    func markDone(_ item: ActionItem) async {
        await setStatus(item, item.status == .done ? .open : .done)
    }

    /// One-click sender action: everything confirmed and undisputed is done.
    func markAllConfirmedDone() async {
        for item in items where item.status == .open && item.counts.confirms > 0 && item.counts.disputes == 0 {
            await setStatus(item, .done)
        }
    }

    func clear(_ response: ItemResponse) async {
        let beforeResponses = responses
        let beforeItems = items
        responses.removeAll { $0.id == response.id }
        if let idx = items.firstIndex(where: { $0.itemKey == response.itemKey }) {
            items[idx].responses.removeAll { $0.id == response.id }
            items[idx].counts = ItemCounts(
                confirms: items[idx].counts.confirms - (response.kind == .confirm ? 1 : 0),
                dones: items[idx].counts.dones - (response.kind == .done ? 1 : 0),
                disputes: items[idx].counts.disputes - (response.kind == .dispute ? 1 : 0))
        }
        actionError = nil
        do {
            try await api.clearResponse(noteId: noteId, responseId: response.id)
        } catch {
            responses = beforeResponses
            items = beforeItems
            actionError = error.localizedDescription
        }
    }

    func linkURL(_ link: LinkView, webAppURL: String) -> URL? {
        URL(string: webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: String(link.path.dropFirst()))
    }

    /// Mail the note to the people named, from the server.
    ///
    /// Returns the per-recipient outcomes, or nil when the call itself
    /// failed (the reason is on `actionError`). Members are granted
    /// access as a side effect, so the sharing view is refreshed from
    /// the reply rather than re-fetched.
    func sendShareEmail(recipients: [String], message: String) async -> [ShareEmailOutcome]? {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            let result = try await api.shareByEmail(
                id: noteId,
                recipients: recipients,
                message: message,
                // The sender's language. The recipient's is unknowable —
                // half of them have no account here — and people share
                // within a team.
                lang: Locale.current.language.languageCode?.identifier ?? "en")
            sharing = result.sharing
            return result.results
        } catch {
            actionError = error.localizedDescription
            return nil
        }
    }

    func delete() async {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            try await api.deleteNote(id: noteId)
            deleted = true
        } catch {
            actionError = error.localizedDescription
        }
    }

    private func sharingAction(_ work: () async throws -> SharingView) async {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            sharing = try await work()
        } catch {
            actionError = error.localizedDescription
        }
    }

    /// The note as Markdown, for "Download Markdown".
    func markdown() -> String {
        guard let content else { return "" }
        var lines = ["# \((content.title ?? "").isEmpty ? "Untitled note" : content.title!)", ""]
        if let note {
            lines.append("_\(note.code) · \(note.updatedAt.formatted(date: .abbreviated, time: .shortened))_")
            lines.append("")
        }
        for def in sections {
            let text = (content.section(def.id).text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if text.isEmpty { continue }
            lines.append("## \(def.name)")
            lines.append("")
            lines.append(text)
            lines.append("")
        }
        return lines.joined(separator: "\n")
    }

    func exportMarkdown() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "\(note?.code ?? "note").md"
        panel.canCreateDirectories = true
        NSApp.activate(ignoringOtherApps: true)
        if panel.runModal() == .OK, let url = panel.url {
            try? markdown().write(to: url, atomically: true, encoding: .utf8)
        }
    }

    // MARK: - Copy

    func transcriptText() -> String {
        let diarized = self.diarized
        return (turns ?? []).map { turn in
            let body = turn.paragraphs.joined(separator: "\n")
            return diarized ? "\(displayName(for: turn)): \(body)" : body
        }.joined(separator: "\n\n")
    }
}
