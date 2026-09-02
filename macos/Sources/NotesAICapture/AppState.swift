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

    let api: APIClient
    private(set) lazy var capture = CaptureViewModel(app: self)
    private var templateCache: [TemplateSummary]?

    init() {
        let stored = Self.loadSettings()
        self.settings = stored
        self.email = UserDefaults.standard.string(forKey: Keys.email) ?? ""
        self.api = APIClient(settings: stored)
        self.recents = Self.loadRecents()
        Task { await restoreSession() }
    }

    // MARK: - Auth

    func restoreSession() async {
        authState = await api.restoreSession() ? .signedIn : .signedOut
    }

    func signIn(email: String, password: String, otp: String?) async throws {
        try await api.login(email: email, password: password, otp: otp)
        self.email = email
        UserDefaults.standard.set(email, forKey: Keys.email)
        authState = .signedIn
    }

    func signOut() async {
        await api.logout()
        templateCache = nil
        authState = .signedOut
    }

    // MARK: - Templates

    /// UUID of the "meeting_notes" template, preferring the capture language.
    /// Returns nil when unavailable — the server then falls back on its own.
    func meetingTemplateID(language: String) async -> String? {
        if templateCache == nil {
            templateCache = try? await api.fetchTemplates()
        }
        guard let templates = templateCache else { return nil }
        let candidates = templates.filter { $0.code == "meeting_notes" }
        return (candidates.first { $0.language == language } ?? candidates.first)?.id
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

    // MARK: - Web app

    func noteURL(_ noteId: String) -> URL? {
        URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "notes/\(noteId)")
    }

    func openNote(_ noteId: String) {
        if let url = noteURL(noteId) {
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
}
