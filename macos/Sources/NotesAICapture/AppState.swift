import AppKit
import Foundation

/// Central app state: settings, auth, template cache, recent captures.
/// Only base URLs and the email are persisted — never passwords or tokens.
@MainActor
final class AppState: ObservableObject {
    enum AuthState: Equatable {
        case restoring
        case signedOut
        case signedIn
    }

    private enum Keys {
        static let settings = "backendSettings"
        static let email = "accountEmail"
        static let recents = "recentCaptures"
        static let theme = "themePref"
        static let spaces = "spaces"
        static let spaceOf = "spaceOfNote"
    }

    @Published var settings: BackendSettings {
        didSet {
            persistSettings()
            let snapshot = settings
            Task { await api.update(settings: snapshot) }
        }
    }
    @Published private(set) var email: String
    @Published private(set) var authState: AuthState = .restoring
    @Published private(set) var recents: [RecentCapture] = []
    /// The Settings sheet in the main window; the popover's menu sets it too.
    @Published var settingsPresented = false
    /// Which tab the Settings sheet opens on.
    @Published var settingsTab: SettingsTab = .general

    enum SettingsTab: Hashable { case general, connectors }

    /// Open Settings on the Connectors tab (menus, the home page's prompt).
    func showConnectors() {
        settingsTab = .connectors
        settingsPresented = true
        NotificationCenter.default.post(name: .openMainWindow, object: nil)
    }
    /// What the main window's detail pane shows; nil is the home page.
    @Published var selection: Selection?

    // MARK: Notes list, search, spaces (home page)

    /// Every note in the tenant the user can see, newest first (server search).
    @Published private(set) var notes: [NoteSummary] = []
    @Published private(set) var notesLoading = false
    @Published private(set) var notesError: String?
    /// The sidebar search box; runs the server's full-text search, debounced.
    @Published var searchQuery = "" {
        didSet { scheduleSearch() }
    }
    @Published private(set) var spaces: [Space] = []
    /// note id → space id (local organisation only).
    @Published private(set) var spaceOf: [String: String] = [:]
    /// nil = every note; otherwise only the notes filed in that space.
    @Published var selectedSpaceId: String?
    let calendar = CalendarService()
    /// Remote MCP servers (HubSpot, Notion, …) connected on this Mac.
    let connectors = ConnectorStore()
    private var searchTask: Task<Void, Never>?
    /// Light / dark / follow-system, persisted; applied app-wide as `NSApp.appearance`.
    @Published var themePref: ThemePref {
        didSet {
            UserDefaults.standard.set(themePref.rawValue, forKey: Keys.theme)
            Self.applyAppearance(themePref)
        }
    }

    let api: APIClient
    private(set) lazy var capture = CaptureViewModel(app: self)
    private var templateCache: [TemplateSummary]?

    init() {
        let stored = Self.loadSettings()
        self.settings = stored
        self.email = UserDefaults.standard.string(forKey: Keys.email) ?? ""
        self.api = APIClient(settings: stored)
        self.recents = Self.loadRecents()
        self.spaces = Self.load([Space].self, key: Keys.spaces) ?? []
        self.spaceOf = Self.load([String: String].self, key: Keys.spaceOf) ?? [:]
        self.themePref = ThemePref(rawValue: UserDefaults.standard.string(forKey: Keys.theme) ?? "") ?? .system
        Self.applyAppearance(themePref)
        Task { await restoreSession() }
        Task { await connectors.recheck() }
        Task { [weak self] in
            await self?.api.onSessionLost {
                Task { @MainActor in self?.sessionExpired() }
            }
        }
    }

    /// Set the appearance app-wide (the menu-bar panel included — SwiftUI's
    /// `preferredColorScheme` does not reach a `MenuBarExtra` window).
    private static func applyAppearance(_ pref: ThemePref) {
        switch pref {
        case .system: NSApp.appearance = nil
        case .light: NSApp.appearance = NSAppearance(named: .aqua)
        case .dark: NSApp.appearance = NSAppearance(named: .darkAqua)
        }
    }

    // MARK: - Auth

    func restoreSession() async {
        authState = await api.restoreSession() ? .signedIn : .signedOut
        if authState == .signedIn { await refreshNotes() }
    }

    func signIn(email: String, password: String, otp: String?) async throws {
        try await api.login(email: email, password: password, otp: otp)
        self.email = email
        UserDefaults.standard.set(email, forKey: Keys.email)
        authState = .signedIn
        await refreshNotes()
    }

    func signOut() async {
        await api.logout()
        templateCache = nil
        notes = []
        selection = nil
        authState = .signedOut
    }

    /// The refresh cookie expired or was revoked server-side: drop to the
    /// sign-in form (the popover and the window both key off `authState`).
    private func sessionExpired() {
        guard authState == .signedIn else { return }
        templateCache = nil
        notes = []
        selection = nil
        authState = .signedOut
    }

    // MARK: - Notes list & search

    /// Reload the notes list (optionally for the current search query).
    func refreshNotes() async {
        guard authState == .signedIn else { return }
        notesLoading = true
        notesError = nil
        do {
            let query = searchQuery.trimmingCharacters(in: .whitespaces)
            notes = try await api.searchNotes(query: query.isEmpty ? nil : query).hits
        } catch {
            notesError = error.localizedDescription
        }
        notesLoading = false
    }

    private func scheduleSearch() {
        searchTask?.cancel()
        searchTask = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(300))
            guard !Task.isCancelled else { return }
            await self?.refreshNotes()
        }
    }

    /// The notes for the home page: the current search, narrowed to the
    /// selected space.
    var visibleNotes: [NoteSummary] {
        guard let space = selectedSpaceId else { return notes }
        return notes.filter { spaceOf[$0.noteId] == space }
    }

    /// Soft-delete on the server, then drop every local trace.
    func moveToTrash(noteId: String) async throws {
        try await api.deleteNote(id: noteId)
        noteDeleted(noteId)
    }

    /// The note is gone (deleted here or from the note view): forget it.
    func noteDeleted(_ noteId: String) {
        notes.removeAll { $0.noteId == noteId }
        spaceOf[noteId] = nil
        persist(spaceOf, key: Keys.spaceOf)
        let jobs = Set(recents.filter { $0.noteId == noteId }.map(\.jobId))
        recents.removeAll { jobs.contains($0.jobId) }
        persistRecents()
        if case .note(let id) = selection, id == noteId { selection = nil }
        if case .capture(let job) = selection, jobs.contains(job) { selection = nil }
    }

    // MARK: - Spaces

    @discardableResult
    func addSpace(named name: String) -> Space? {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let space = Space(id: UUID().uuidString, name: trimmed, createdAt: Date())
        spaces.append(space)
        persist(spaces, key: Keys.spaces)
        return space
    }

    func renameSpace(_ id: String, to name: String) {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let index = spaces.firstIndex(where: { $0.id == id }) else { return }
        spaces[index].name = trimmed
        persist(spaces, key: Keys.spaces)
    }

    /// Remove the space; its notes go back to "All notes".
    func deleteSpace(_ id: String) {
        spaces.removeAll { $0.id == id }
        spaceOf = spaceOf.filter { $0.value != id }
        if selectedSpaceId == id { selectedSpaceId = nil }
        persist(spaces, key: Keys.spaces)
        persist(spaceOf, key: Keys.spaceOf)
    }

    func file(noteId: String, in spaceId: String?) {
        spaceOf[noteId] = spaceId
        persist(spaceOf, key: Keys.spaceOf)
    }

    // MARK: - Templates

    /// UUID of the meeting-notes template in `language` (an ISO 639-1
    /// code). Returns nil when the catalogue is unreachable or the
    /// language is not yet known ("auto") — the server then picks a
    /// template in the transcript's own language.
    func meetingTemplateID(language: String) async -> String? {
        if language == CaptureViewModel.autoLanguage { return nil }
        if templateCache == nil {
            templateCache = try? await api.fetchTemplates()
        }
        guard let templates = templateCache else { return nil }
        // Per-language copies share the "meeting_notes" code prefix
        // ("meeting_notes", "meeting_notes_uk", …).
        let candidates = templates.filter { $0.code.hasPrefix("meeting_notes") }
        return candidates.first { $0.language == language }?.id
    }

    // MARK: - Recent captures

    func addRecent(jobId: String, title: String) {
        recents.insert(
            RecentCapture(jobId: jobId, title: title, createdAt: Date(),
                          status: .queued, noteId: nil, errorMessage: nil),
            at: 0)
        if recents.count > 10 { recents = Array(recents.prefix(10)) }
        persistRecents()
    }

    func updateRecent(jobId: String, status: JobStatus? = nil, noteId: String? = nil, errorMessage: String? = nil) {
        guard let index = recents.firstIndex(where: { $0.jobId == jobId }) else { return }
        if let status { recents[index].status = status }
        if let noteId { recents[index].noteId = noteId }
        if let errorMessage { recents[index].errorMessage = errorMessage }
        persistRecents()
    }

    func removeRecents(jobIds: Set<String>) {
        recents.removeAll { jobIds.contains($0.jobId) }
        if case .capture(let job) = selection, jobIds.contains(job) { selection = nil }
        persistRecents()
    }

    /// Drop every capture that already reached a terminal state.
    func clearFinishedRecents() {
        let finished = Set(recents.filter { $0.status?.isTerminal ?? false }.map(\.jobId))
        removeRecents(jobIds: finished)
    }

    /// Re-fetch the status of any capture that is not yet in a terminal state.
    func refreshRecents() async {
        guard authState == .signedIn else { return }
        for recent in recents where !(recent.status?.isTerminal ?? false) {
            guard let job = try? await api.jobStatus(id: recent.jobId) else { continue }
            updateRecent(jobId: recent.jobId,
                         status: job.status,
                         errorMessage: job.status == .failed ? job.failureText : nil)
        }
    }

    /// Draft the note for a capture whose transcript finished without one
    /// (the app was quit mid-pipeline, or the note request failed).
    func draftNote(for capture: RecentCapture) async {
        guard capture.status == .complete, capture.noteId == nil,
              !drafting.contains(capture.jobId) else { return }
        drafting.insert(capture.jobId)
        defer { drafting.remove(capture.jobId) }
        do {
            // The job knows what language it heard; the app's current
            // setting may be "auto" or have changed since.
            let job = try? await api.jobStatus(id: capture.jobId)
            let templateId = await meetingTemplateID(
                language: job?.detectedLanguage ?? self.capture.language)
            let note = try await api.createNoteFromTranscript(
                asrJobId: capture.jobId, templateId: templateId, title: capture.title)
            updateRecent(jobId: capture.jobId, noteId: note.id, errorMessage: "")
            openNote(note.id)
        } catch {
            updateRecent(jobId: capture.jobId, errorMessage: error.localizedDescription)
        }
    }

    @Published private(set) var drafting: Set<String> = []

    // MARK: - Opening notes

    /// Show the meeting in the main window (opening the window if needed).
    func select(jobId: String) {
        selection = .capture(jobId: jobId)
        NotificationCenter.default.post(name: .openMainWindow, object: nil)
    }

    /// Open a note inside this app. A note that came from one of this
    /// Mac's captures opens as that capture (so the transcript tab is there).
    func openNote(_ noteId: String) {
        if let recent = recents.first(where: { $0.noteId == noteId }) {
            selection = .capture(jobId: recent.jobId)
        } else {
            selection = .note(noteId: noteId)
        }
        NotificationCenter.default.post(name: .openMainWindow, object: nil)
    }

    /// The note id behind the current selection, if it has one.
    var selectedNoteId: String? {
        switch selection {
        case .note(let id): return id
        case .capture(let job): return recents.first { $0.jobId == job }?.noteId
        case nil: return nil
        }
    }

    // MARK: - Web app

    func noteURL(_ noteId: String) -> URL? {
        URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "notes/\(noteId)")
    }

    func openNoteInBrowser(_ noteId: String) {
        if let url = noteURL(noteId) {
            NSWorkspace.shared.open(url)
        }
    }

    func openWebApp() {
        if let url = URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces)) {
            NSWorkspace.shared.open(url)
        }
    }

    // MARK: - Persistence

    private static func loadSettings() -> BackendSettings {
        guard let data = UserDefaults.standard.data(forKey: Keys.settings),
              let settings = try? JSONDecoder().decode(BackendSettings.self, from: data)
        else { return .default }
        return settings
    }

    private func persistSettings() {
        if let data = try? JSONEncoder().encode(settings) {
            UserDefaults.standard.set(data, forKey: Keys.settings)
        }
    }

    private static func loadRecents() -> [RecentCapture] {
        guard let data = UserDefaults.standard.data(forKey: Keys.recents),
              let recents = try? JSONDecoder().decode([RecentCapture].self, from: data)
        else { return [] }
        return recents
    }

    private func persistRecents() {
        if let data = try? JSONEncoder().encode(recents) {
            UserDefaults.standard.set(data, forKey: Keys.recents)
        }
    }

    private static func load<T: Decodable>(_ type: T.Type, key: String) -> T? {
        guard let data = UserDefaults.standard.data(forKey: key) else { return nil }
        return try? JSONDecoder().decode(type, from: data)
    }

    private func persist<T: Encodable>(_ value: T, key: String) {
        if let data = try? JSONEncoder().encode(value) {
            UserDefaults.standard.set(data, forKey: key)
        }
    }
}
