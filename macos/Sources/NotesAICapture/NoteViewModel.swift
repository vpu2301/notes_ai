import AppKit
import Foundation

/// One open note: the envelope, its template's sections, the editable
/// content with debounced autosave (drafts only), finalize / revert, the
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
    let jobId: String?

    @Published private(set) var note: NoteEnvelope?
    @Published private(set) var sections: [TemplateSectionDef] = []
    @Published var content: NoteContent?
    @Published private(set) var version = 0
    @Published private(set) var saveState: SaveState = .saved
    @Published private(set) var conflict = false
    @Published private(set) var loadError: String?
    @Published private(set) var isLoading = true
    @Published private(set) var busy = false
    @Published var actionError: String?
    @Published var tab: Tab = .notes

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

    private let api: APIClient
    private var saveTask: Task<Void, Never>?
    private var pending: (content: NoteContent, version: Int)?
    private static let autosaveDelay: Duration = .milliseconds(900)

    init(noteId: String, jobId: String?, api: APIClient) {
        self.noteId = noteId
        self.jobId = jobId
        self.api = api
    }

    var isDraft: Bool { note?.status == .draft }
    var editable: Bool { isDraft }

    // MARK: - Load

    func load() async {
        loadError = nil
        isLoading = note == nil
        do {
            let envelope = try await api.fetchNote(id: noteId)
            note = envelope
            content = envelope.content
            version = envelope.currentVersionNumber
            saveState = .saved
            conflict = false
            if let templateId = envelope.content?.templateId,
               let template = try? await api.fetchTemplate(id: templateId) {
                sections = template.schemaJsonb.sections.sorted { ($0.order ?? 0) < ($1.order ?? 0) }
            } else {
                // Template unavailable: the envelope's labels as plain text sections.
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
    /// this transcript, and — while the note is still a draft — in the note
    /// body, whose turn lines start with the name. A finalized note is a
    /// record; its text stays and only the transcript shows the new name.
    func renameSpeaker(label: String, to rawName: String) async {
        let from = speakerNames[label] ?? defaultSpeakerName(label)
        let trimmed = rawName.split(whereSeparator: \.isWhitespace).joined(separator: " ")
        let to = trimmed.isEmpty ? defaultSpeakerName(label) : String(trimmed.prefix(80))
        guard to != from, let jobId else { return }

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

    /// Write the pending content now (also called before finalize).
    func flush() async {
        saveTask?.cancel()
        guard let snapshot = pending else { return }
        pending = nil
        saveState = .saving
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

    // MARK: - Lifecycle actions

    func finalize() async {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            await flush()
            guard saveState != .error else { return }
            try await api.finalizeNote(id: noteId, expectedVersion: version)
            await load()
        } catch {
            actionError = error.localizedDescription
        }
    }

    func revertToDraft() async {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            try await api.revertToDraft(id: noteId)
            await load()
        } catch {
            actionError = error.localizedDescription
        }
    }

    /// Fetch the PDF and let the user pick where to keep it.
    func exportPDF() async {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            let data = try await api.notePDF(id: noteId)
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

    /// Returns false when the address belongs to nobody in the workspace.
    func share(email: String) async -> Bool {
        busy = true
        actionError = nil
        defer { busy = false }
        do {
            sharing = try await api.shareWithMember(id: noteId, email: email)
            return true
        } catch let APIError.http(status, _) where status == 404 {
            return false
        } catch {
            actionError = error.localizedDescription
            return false
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
