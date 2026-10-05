import AppKit
import Foundation
import SwiftUI

/// Central app state: settings, auth, template cache, recent captures.
/// Only base URLs and the email are persisted — never passwords or tokens.
@MainActor
final class AppState: ObservableObject {
    enum AuthState: Equatable {
        case restoring
        case signedOut
        case signedIn
    }

    enum Keys {
        static let settings = "backendSettings"
        static let email = "accountEmail"
        static let recents = "recentCaptures"
        static let theme = "themePref"
        static let sidebarCollapsed = "sidebarCollapsed"
        /// Pre-0021 local spaces, read once and moved to the server.
        static let legacySpaces = "spaces"
        static let legacySpaceOf = "spaceOfNote"
        /// Who this Mac was last signed in as (ids and an address, never a token), so an offline-expired session still knows whose recordings wait.
        static let lastIdentity = "lastIdentity"
        /// Every identity with local state on this Mac, so Settings can offer to remove another's.
        static let knownIdentities = "knownIdentities"
        /// One-time move of the unscoped keys under the first identity.
        static let migratedV2 = "localStateMigratedV2"
    }

    /// What local state is filed under: identity + workspace, so a second account or a switch never shows the first one's meetings.
    struct LocalScope: Equatable, Codable, Sendable {
        var identityId: String
        var tenantId: String

        func key(_ base: String) -> String { "\(base).\(identityId).\(tenantId)" }
    }

    /// The identity this Mac last had a session for.
    struct LastIdentity: Codable, Equatable, Sendable {
        var identityId: String
        var email: String
        var tenantId: String?
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
    /// Jobs whose speakers are being re-labelled right now. Not persisted.
    @Published private(set) var relabelling: Set<String> = []
    /// The Settings sheet in the main window; the popover's menu sets it too.
    @Published var settingsPresented = false
    /// Which tab the Settings sheet opens on.
    @Published var settingsTab: SettingsTab = .general

    enum SettingsTab: Hashable, CaseIterable {
        case general, vocabulary, connectors, dataAI, billing, account, advanced
    }

    /// Open Settings on the Connectors tab (menus, the home page's prompt).
    func showConnectors() {
        settingsTab = .connectors
        settingsPresented = true
        NotificationCenter.default.post(name: .openMainWindow, object: nil)
    }
    /// What the main window's detail pane shows; nil is the home page.
    @Published var selection: Selection?
    /// What the workspace admin allows. Permissive until known, so an older server changes nothing.
    @Published private(set) var sharingRules: SharingConstraints = .permissive
    /// A note id the popover asked to "Share with client…"; `NoteView` opens the sheet and clears it.
    @Published var pendingClientShare: String?

    /// The sidebar shrunk to an icon rail, persisted like the web app's.
    @Published var sidebarCollapsed: Bool {
        didSet { UserDefaults.standard.set(sidebarCollapsed, forKey: Keys.sidebarCollapsed) }
    }

    func toggleSidebar() {
        withAnimation(.easeOut(duration: 0.18)) { sidebarCollapsed.toggle() }
    }

    /// The "Invite people" sheet in the main window.
    @Published var invitePresented = false

    /// The "New from template…" sheet in the main window.
    @Published var templatePickerPresented = false
    /// A sentence about a sidebar action that failed; the window shows it once as an alert.
    @Published var actionNotice: String?
    /// A note being made by hand (blank or from a template).
    @Published private(set) var creatingNote = false

    // ── notifications (the bell) ─────────────────────────────────────
    @Published var unreadNotifications = 0
    @Published var notificationFeed: [NotificationItem] = []
    @Published var notificationsLoading = false
    @Published var notificationsError: String?
    var notificationTask: Task<Void, Never>?

    func showInvite() {
        invitePresented = true
        NotificationCenter.default.post(name: .openMainWindow, object: nil)
    }

    // MARK: Notes list, search, spaces (home page)

    /// Every note in the tenant the user can see, newest first (server search).
    @Published private(set) var notes: [NoteSummary] = []
    @Published private(set) var notesLoading = false
    @Published private(set) var notesError: String?
    /// The sidebar search box; runs the server's full-text search, debounced.
    @Published var searchQuery = "" {
        didSet { scheduleSearch() }
    }
    /// nil = every note; otherwise only the notes filed in that space.
    @Published var selectedSpaceId: String?
    let calendar = CalendarService()
    /// Google Calendar connected on the server (shared with the web app).
    private(set) lazy var googleCalendar = GoogleCalendarService(api: api)
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
    /// Recordings this Mac is still holding.
    private(set) lazy var pending = PendingUploads(host: self)
    private var templateCache: [TemplateSummary]?

    init() {
        let stored = Self.loadSettings()
        self.settings = stored
        self.email = UserDefaults.standard.string(forKey: Keys.email) ?? ""
        self.api = APIClient(settings: stored)
        // Recents belong to an identity and a workspace; until the session is restored, the best guess is the last sign-in.
        let store = LocalStore()
        self.local = store
        let last = store.lastIdentity
        self.lastIdentity = last
        if let last, let tenantId = last.tenantId {
            let scope = LocalScope(identityId: last.identityId, tenantId: tenantId)
            self.scope = scope
            self.recents = store.recents(for: scope)
        } else {
            self.recents = []
        }
        self.themePref = ThemePref(rawValue: UserDefaults.standard.string(forKey: Keys.theme) ?? "") ?? .system
        self.sidebarCollapsed = UserDefaults.standard.bool(forKey: Keys.sidebarCollapsed)
        Self.applyAppearance(themePref)
        Task { await restoreSession() }
        Task { await connectors.recheck() }
        urlObserver = NotificationCenter.default.addObserver(
            forName: .openAppURL, object: nil, queue: .main
        ) { [weak self] note in
            guard let url = note.object as? URL else { return }
            MainActor.assumeIsolated { self?.handle(url) }
        }
        Task { [weak self] in
            guard let api = self?.api else { return }
            await api.onSessionLost { [weak self] reason in
                Task { @MainActor in self?.sessionEnded(reason) }
            }
            await api.onReauthRequired { [weak self] in
                await self?.presentReauth() ?? false
            }
        }
    }

    /// Set the appearance app-wide (SwiftUI's `preferredColorScheme` does not reach a `MenuBarExtra` window).
    private static func applyAppearance(_ pref: ThemePref) {
        switch pref {
        case .system: NSApp.appearance = nil
        case .light: NSApp.appearance = NSAppearance(named: .aqua)
        case .dark: NSApp.appearance = NSAppearance(named: .darkAqua)
        }
    }

    // MARK: - Auth

    /// Who is signed in, once the server said so; also written into the sidecar beside a recording that could not be uploaded.
    @Published private(set) var identity: IdentitySummary?
    /// Every workspace this identity can reach, as sign-in knew it.
    @Published private(set) var memberships: [MembershipSummary] = []
    @Published private(set) var tenantId: String?
    /// Signed in from the stored session, unconfirmed by the server; banner shown, no requests until the person acts.
    @Published private(set) var reconnecting = false
    /// Why the app last dropped to the sign-in screen, shown there once.
    @Published var signedOutNotice: String?
    /// The step-up sheet, when an endpoint asks for recent proof.
    @Published var reauth: ReauthPrompt?
    /// "N recordings are not uploaded yet" — shown before signing out.
    @Published var signOutPrompt = false

    // ── workspaces ───────────────────────────────────────────────────

    /// Every workspace this identity can reach, as the server lists it now (`memberships` is what sign-in knew).
    @Published private(set) var workspaces: [Tenant] = []
    /// A switch in flight, so the switcher can show which one.
    @Published private(set) var switchingTo: String?
    /// A workspace this Mac can no longer reach, and why; banner until dismissed, local state stays.
    @Published var workspaceNotice: String?
    /// The session expired while away from the network: nothing lost, nothing sendable.
    @Published private(set) var expiredWhileOffline = false
    private var lastWorkspaceRefresh: Date?

    var activeWorkspace: Tenant? {
        guard let tenantId else { return nil }
        return workspaces.first { $0.id == tenantId }
    }

    /// The name to show for the active workspace before `/tenants` answers.
    var activeWorkspaceName: String {
        if let activeWorkspace { return activeWorkspace.title }
        if let tenantId, let membership = memberships.first(where: { $0.tenantId == tenantId }) {
            return membership.name
        }
        return ""
    }

    /// What a sign-in attempt still owes before the app is signed in.
    enum SignInStep: Equatable {
        case signedIn
        case mfaRequired(challengeId: String, methods: [String])
        /// A brand-new identity: offer to name it before the app opens.
        case welcome
    }

    func restoreSession() async {
        switch await api.restoreSession() {
        case .signedOut:
            authState = .signedOut
        case .signedIn(let stored):
            adopt(stored)
            reconnecting = false
            expiredWhileOffline = false
            authState = .signedIn
            await hydrateIdentity()
            await loadWorkspaceData()
            await retryPendingUploads()
        case .offline(let stored):
            // The server just could not be reached: never wipe a session for a network error.
            adopt(stored)
            reconnecting = true
            authState = .signedIn
        case .expired(let stored):
            // The session is genuinely over, but nothing local goes with it: the recordings are still this person's.
            adopt(stored)
            expiredWhileOffline = true
            authState = .signedOut
            signedOutNotice = pendingCount > 0
                ? "Your session expired while this Mac was offline. \(pendingCount) recording\(pendingCount == 1 ? " is" : "s are") still kept here — sign in to send \(pendingCount == 1 ? "it" : "them")."
                : "Your session expired while this Mac was offline. Sign in to continue."
        }
    }

    private func adopt(_ stored: StoredSession) {
        if !stored.email.isEmpty {
            email = stored.email
            UserDefaults.standard.set(stored.email, forKey: Keys.email)
        }
        identityId = stored.identityId
        tenantId = stored.lastTenantId
        applyScope(identityId: stored.identityId, tenantId: stored.lastTenantId)
    }

    /// Send whatever is waiting. Called after sign-in and reconnect — never on a timer.
    func retryPendingUploads() async {
        guard authState == .signedIn, !reconnecting else { return }
        pending.reload()
        guard !pending.isEmpty else { return }
        await pending.retryAll()
    }

    /// A kept recording reached the server: file it under its own workspace, not necessarily the active one.
    func adoptUploaded(job: TranscriptionJob, capture: PendingCapture) {
        let recent = RecentCapture(jobId: job.id, title: capture.info.title,
                                   createdAt: capture.info.recordedAt,
                                   status: job.status, noteId: nil, errorMessage: nil)
        guard let tenantId = capture.info.tenantId, tenantId != self.tenantId else {
            recents.insert(recent, at: 0)
            if recents.count > 10 { recents = Array(recents.prefix(10)) }
            persistRecents()
            return
        }
        // Another workspace's meeting: write it into that workspace's list.
        local.addRecent(recent, to: LocalScope(identityId: identityId, tenantId: tenantId))
    }

    /// Poll the job, then draft its note, in the workspace it was recorded in. Returns as soon as polling starts.
    func continuePipeline(jobId: String, capture: PendingCapture) async {
        let tenant = capture.info.tenantId
        let title = capture.info.title
        Task { [weak self] in
            guard let self else { return }
            var status: JobStatus = .queued
            // About half an hour at three seconds a turn; the recents list picks up anything slower.
            for _ in 0..<600 {
                try? await Task.sleep(for: .seconds(3))
                guard let job = try? await self.api.jobStatus(id: jobId, tenant: tenant) else {
                    continue
                }
                status = job.status
                self.updateRecent(jobId: jobId, status: status)
                if status.isTerminal { break }
            }
            guard status == .complete else { return }
            let templateId = await self.meetingTemplateID(language: capture.info.language)
            guard let note = try? await self.api.createNoteFromTranscript(
                asrJobId: jobId, templateId: templateId, title: title, tenant: tenant)
            else { return }
            self.updateRecent(jobId: jobId, status: .complete, noteId: note.id)
            if tenant == nil || tenant == self.tenantId {
                await self.refreshNotes()
            }
        }
    }

    /// A `notesai://` link arrived. OAuth and calendar callbacks are intercepted earlier, so in practice this is invitations.
    func handle(_ url: URL) {
        switch AppURL.parse(url) {
        case .invite(let token):
            pendingInviteToken = token
            NotificationCenter.default.post(name: .openMainWindow, object: nil)
            // No server can issue or redeem an invitation yet; say so rather than render a sheet that lies.
            workspaceNotice = "This link is an invitation, but the server does not support invitations yet."
        case .calendarConnected, .oauthCallback, .none:
            // Handled by the session that started them.
            break
        }
    }

    /// Recordings kept on this Mac for whoever is (or was last) signed in.
    var pendingCount: Int {
        let identity = identityId.isEmpty ? (lastIdentity?.identityId ?? "") : identityId
        guard !identity.isEmpty else { return PendingCaptures.count() }
        return PendingCaptures.all().filter { $0.info.identityId == identity }.count
    }

    /// Try the server again after a "Reconnecting…" banner.
    func reconnect() async {
        guard reconnecting else { return }
        await restoreSession()
    }

    /// Sign out, unless recordings are still unsent — then ask first.
    func requestSignOut() {
        if pendingCount > 0 {
        // The prompt lives on the main window; from the popover there may be none yet.
            NotificationCenter.default.post(name: .openMainWindow, object: nil)
            signOutPrompt = true
        } else {
            Task { await signOut() }
        }
    }

    // ── the sign-in flows ────────────────────────────────────────────

    /// Mail a one-time code. The reply never says whether the address is known.
    func startEmailCode(email address: String) async throws -> EmailChallenge {
        try await api.startEmailCode(email: address, language: Locale.preferredLanguageCode)
    }

    func signIn(withCode code: String, challengeId: String, email address: String) async throws -> SignInStep {
        let result = try await api.verifyEmailCode(challengeId: challengeId, code: code)
        return await complete(result, email: address)
    }

    func signIn(email address: String, password: String, otp: String?) async throws -> SignInStep {
        let result = try await api.login(email: address, password: password, otp: otp)
        return await complete(result, email: address)
    }

    func completeMFA(challengeId: String, method: String, code: String,
                     email address: String) async throws -> SignInStep {
        let result = try await api.verifyMFA(challengeId: challengeId, method: method, code: code)
        return await complete(result, email: address)
    }

    private func complete(_ result: AuthResult, email address: String) async -> SignInStep {
        switch result {
        case .mfaRequired(let challengeId, let methods, _):
            return .mfaRequired(challengeId: challengeId, methods: methods)
        case .authenticated(let session):
            email = session.identity?.email ?? address
            UserDefaults.standard.set(email, forKey: Keys.email)
            identity = session.identity
            identityId = session.identity?.id ?? ""
            memberships = session.memberships
            tenantId = session.tenantId
            signedOutNotice = nil
            reconnecting = false
            expiredWhileOffline = false
            authState = .signedIn
            applyScope(identityId: identityId, tenantId: session.tenantId)
            await loadWorkspaceData()
            await retryPendingUploads()
            return session.isNewIdentity ? .welcome : .signedIn
        }
    }

    /// The welcome step's one field; skipping it is fine (server-defaulted).
    func setDisplayName(_ name: String) async {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        identity = try? await api.setDisplayName(trimmed)
    }

    /// True for an account younger than a day that has not dismissed the "record your first meeting" card on this device.
    @Published var isFirstRun = false

    private static let firstRunSeenKey = "notesai.first_run_seen"

    func dismissFirstRun() {
        isFirstRun = false
        UserDefaults.standard.set(true, forKey: Self.firstRunSeenKey)
    }

    private func detectFirstRun(_ identity: IdentitySummary) {
        guard let created = identity.createdAt,
              Date().timeIntervalSince(created) < 24 * 3600,
              !UserDefaults.standard.bool(forKey: Self.firstRunSeenKey) else { return }
        isFirstRun = true
    }

    private func hydrateIdentity() async {
        guard let response = try? await api.me() else { return }
        if let identity = response.identity {
            self.identity = identity
            detectFirstRun(identity)
        }
        if let memberships = response.memberships { self.memberships = memberships }
    }

    func signOut() async {
        let signedOut = identityId
        await api.logout()
        clearSignedInState()
        // The names the account brought to kept recordings and the per-job answers go with it; the recordings stay.
        SignOutCleanup.run(identityId: signedOut)
        capture.forgetContext()
        pending.reload()
        signedOutNotice = nil
        authState = .signedOut
    }

    /// The session is gone for good: drop to the sign-in form with the reason.
    private func sessionEnded(_ reason: SessionLostReason) {
        guard authState == .signedIn else { return }
        clearSignedInState()
        signedOutNotice = reason.message
        authState = .signedOut
    }

    private func clearSignedInState() {
        googleCalendar.reset()
        templateCache = nil
        notes = []
        setSpaces([])
        selection = nil
        identity = nil
        memberships = []
        tenantId = nil
        identityId = ""
        reconnecting = false
        reauth = nil
    }

    // ── step-up ──────────────────────────────────────────────────────

    /// Ask the person to prove it is them. Called from the API client's actor: hops to main, shows a sheet, waits; the request retries once on `true`.
    func presentReauth() async -> Bool {
        guard authState == .signedIn else { return false }
        let options = try? await api.startReauth()
        // The sheet lives in the main window; from the popover ask for one.
        NotificationCenter.default.post(name: .openMainWindow, object: nil)
        return await withCheckedContinuation { continuation in
            // Resumed exactly once (sheet or deadline); an unresumed continuation would hang every queued request.
            let answered = Answered()
            let finish: @MainActor (Bool) -> Void = { [weak self] ok in
                guard answered.claim() else { return }
                self?.reauth = nil
                continuation.resume(returning: ok)
            }
            reauth = ReauthPrompt(
                methods: options?.methods ?? ["email_code"],
                challengeId: options?.challengeId,
                answer: finish)
            Task {
                try? await Task.sleep(for: .seconds(120))
                finish(false)
            }
        }
    }

    /// One-shot latch, so a continuation is resumed once and only once.
    private final class Answered {
        private var done = false
        func claim() -> Bool {
            if done { return false }
            done = true
            return true
        }
    }

    /// The identity id behind the current session, for the sidecar beside an un-uploaded recording.
    private(set) var identityId: String = ""
    /// Which identity + workspace local state is currently filed under.
    private(set) var scope: LocalScope?
    /// Where that state actually lives.
    private let local: LocalStore
    private var urlObserver: NSObjectProtocol?
    /// An invitation token from a `notesai://invite/…` link, held in memory only.
    private(set) var pendingInviteToken: String?
    /// Who this Mac was last signed in as; survives an expired session so kept recordings can be found.
    private(set) var lastIdentity: LastIdentity?

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

    /// The current search, narrowed to the selected space.
    var visibleNotes: [NoteSummary] {
        guard let space = selectedSpaceId else { return notes }
        return notes.filter { spaceOf[$0.noteId] == space }
    }

    /// Private ↔ workspace, from the list's access pill.
    func setVisibility(noteId: String, workspace: Bool) async throws {
        applySharing(try await api.setVisibility(id: noteId, visibility: workspace ? "workspace" : "private"))
    }

    /// The note's public link, minted on first use.
    func publicLink(noteId: String) async throws -> URL? {
        let sharing = try await api.createPublicLink(id: noteId)
        applySharing(sharing)
        guard let path = sharing.publicLink?.path,
              let root = URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces)) else { return nil }
        return root.appending(path: String(path.dropFirst()))
    }

    func revokePublicLink(noteId: String) async throws {
        applySharing(try await api.revokePublicLink(id: noteId))
    }

    /// Show a sharing change on the list row without reloading the list.
    private func applySharing(_ sharing: SharingView) {
        guard let index = notes.firstIndex(where: { $0.noteId.lowercased() == sharing.noteId.lowercased() })
        else { return }
        notes[index].access = NoteAccess(sharing)
    }

    /// Soft-delete on the server, then drop every local trace.
    func moveToTrash(noteId: String) async throws {
        try await api.deleteNote(id: noteId)
        noteDeleted(noteId)
    }

    /// The note is gone (deleted here or from the note view): forget it.
    func noteDeleted(_ noteId: String) {
        capture.forgetNote(noteId)
        notes.removeAll { $0.noteId == noteId }
        var list = spaces
        for index in list.indices { list[index].noteIds.removeAll { $0 == noteId } }
        setSpaces(list)
        let jobs = Set(recents.filter { $0.noteId == noteId }.map(\.jobId))
        recents.removeAll { jobs.contains($0.jobId) }
        persistRecents()
        if case .note(let id) = selection, id == noteId { selection = nil }
        if case .capture(let job) = selection, jobs.contains(job) { selection = nil }
    }

    // MARK: - Spaces (server-side, 0021)

    /// The user's spaces from the server, in creation order.
    @Published private(set) var spaces: [Space] = []
    /// note id → space id, derived from `spaces`.
    private(set) var spaceOf: [String: String] = [:]
    @Published private(set) var spacesError: String?

    private func setSpaces(_ list: [Space]) {
        spaces = list
        var map: [String: String] = [:]
        for space in list {
            for noteId in space.noteIds { map[noteId] = space.id }
        }
        spaceOf = map
        if let selected = selectedSpaceId, !list.contains(where: { $0.id == selected }) {
            selectedSpaceId = nil
        }
    }

    /// Reload the spaces; the first time pre-0021 local spaces are found they are moved up.
    func refreshSpaces() async {
        guard authState == .signedIn else { return }
        do {
            var list = try await api.fetchSpaces()
            if let imported = await importLegacySpaces(into: list) { list = imported }
            setSpaces(list)
            spacesError = nil
        } catch {
            spacesError = error.localizedDescription
        }
    }

    /// Move this device's UserDefaults spaces to the server, once. Nil when there was nothing to move.
    private func importLegacySpaces(into current: [Space]) async -> [Space]? {
        guard let legacy = Self.load([LegacySpace].self, key: Keys.legacySpaces), !legacy.isEmpty else {
            UserDefaults.standard.removeObject(forKey: Keys.legacySpaces)
            UserDefaults.standard.removeObject(forKey: Keys.legacySpaceOf)
            return nil
        }
        let legacyOf = Self.load([String: String].self, key: Keys.legacySpaceOf) ?? [:]
        var newIds: [String: String] = [:]
        for old in legacy {
            // Same name already up there (made from another device): reuse it.
            if let existing = current.first(where: { $0.name == old.name }) {
                newIds[old.id] = existing.id
                continue
            }
            guard let created = try? await api.createSpace(name: old.name) else { return nil }
            newIds[old.id] = created.id
        }
        for (noteId, oldSpace) in legacyOf {
            guard let spaceId = newIds[oldSpace] else { continue }
            try? await api.fileNote(id: noteId, spaceId: spaceId)
        }
        UserDefaults.standard.removeObject(forKey: Keys.legacySpaces)
        UserDefaults.standard.removeObject(forKey: Keys.legacySpaceOf)
        return try? await api.fetchSpaces()
    }

    @discardableResult
    func addSpace(named name: String) async -> Space? {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        do {
            let space = try await api.createSpace(name: trimmed)
            setSpaces(spaces + [space])
            spacesError = nil
            return space
        } catch {
            spacesError = error.localizedDescription
            return nil
        }
    }

    func renameSpace(_ id: String, to name: String) {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let index = spaces.firstIndex(where: { $0.id == id }) else { return }
        var list = spaces
        list[index].name = trimmed
        setSpaces(list)
        Task {
            do {
                _ = try await api.renameSpace(id: id, name: trimmed)
            } catch {
                spacesError = error.localizedDescription
                await refreshSpaces()
            }
        }
    }

    /// Remove the space; its notes go back to "All notes".
    func deleteSpace(_ id: String) {
        setSpaces(spaces.filter { $0.id != id })
        Task {
            do {
                try await api.deleteSpace(id: id)
            } catch {
                spacesError = error.localizedDescription
                await refreshSpaces()
            }
        }
    }

    func file(noteId: String, in spaceId: String?) {
        var list = spaces
        for index in list.indices {
            list[index].noteIds.removeAll { $0 == noteId }
            if list[index].id == spaceId { list[index].noteIds.append(noteId) }
        }
        setSpaces(list)
        Task {
            do {
                try await api.fileNote(id: noteId, spaceId: spaceId)
            } catch {
                spacesError = error.localizedDescription
                await refreshSpaces()
            }
        }
    }

    // MARK: - Templates

    /// UUID of the meeting-notes template in `language`; nil when the catalogue is unreachable or the language is "auto" (the server then picks).
    func meetingTemplateID(language: String) async -> String? {
        if language == CaptureViewModel.autoLanguage { return nil }
        if templateCache == nil {
            templateCache = try? await api.fetchTemplates()
        }
        guard let templates = templateCache else { return nil }
        // Per-language copies share the "meeting_notes" code prefix.
        let candidates = templates.filter { $0.code.hasPrefix("meeting_notes") }
        return candidates.first { $0.language == language }?.id
    }

    // MARK: - Recent captures

    func addRecent(jobId: String, title: String, meetingNoteId: String? = nil) {
        recents.insert(
            RecentCapture(jobId: jobId, title: title, createdAt: Date(),
                          status: .queued, noteId: nil, errorMessage: nil,
                          meetingNoteId: meetingNoteId),
            at: 0)
        if recents.count > 10 { recents = Array(recents.prefix(10)) }
        persistRecents()
    }

    func updateRecent(jobId: String, status: JobStatus? = nil, noteId: String? = nil, errorMessage: String? = nil,
                      title: String? = nil) {
        guard let index = recents.firstIndex(where: { $0.jobId == jobId }) else { return }
        if let title, !title.isEmpty { recents[index].title = title }
        if let status { recents[index].status = status }
        if let noteId { recents[index].noteId = noteId }
        if let errorMessage { recents[index].errorMessage = errorMessage }
        persistRecents()
    }

    func setRelabelling(jobId: String, _ running: Bool) {
        if running { relabelling.insert(jobId) } else { relabelling.remove(jobId) }
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
        await resumeUnfinishedCaptures()
    }

    /// Captures whose transcript finished while nothing waited (app quit mid-transcription) are picked up: transcript into the meeting note.
    private func resumeUnfinishedCaptures() async {
        for recent in recents where recent.status == .complete && recent.noteId == nil
            && (recent.errorMessage ?? "").isEmpty {
            // The capture in front of the user finishes on its own.
            if recent.jobId == capture.activeJobId, capture.phase.isBusy { continue }
            if let live = recent.meetingNoteId {
                do {
                    try await finishMeeting(noteId: live)
                    updateRecent(jobId: recent.jobId, noteId: live)
                } catch APIError.http(status: 404, problem: _) {
                    // The live note went to the bin: draft a fresh one.
                    await draftNote(for: recent, open: false)
                } catch {
                    // Offline or the service is down: the next refresh tries again.
                }
            } else {
                await draftNote(for: recent, open: false)
            }
        }
    }

    /// Hand a finished transcript to its meeting note — unless it was already written up meanwhile (a second run would start).
    private func finishMeeting(noteId: String) async throws {
        if (try? await api.generation(noteId: noteId)) != nil { return }
        _ = try await api.attachTranscript(noteId: noteId)
    }

    /// Draft the note for a capture whose transcript finished without one.
    func draftNote(for capture: RecentCapture, open: Bool = true) async {
        guard capture.status == .complete, capture.noteId == nil,
              !drafting.contains(capture.jobId) else { return }
        drafting.insert(capture.jobId)
        defer { drafting.remove(capture.jobId) }
        do {
            // The job knows what language it heard; the setting may be "auto" or changed since.
            let job = try? await api.jobStatus(id: capture.jobId)
            let templateId = await meetingTemplateID(
                language: job?.detectedLanguage ?? self.capture.language)
            let note = try await api.createNoteFromTranscript(
                asrJobId: capture.jobId, templateId: templateId, title: capture.title)
            updateRecent(jobId: capture.jobId, noteId: note.id, errorMessage: "")
            if open { openNote(note.id) }
        } catch APIError.http(status: 409, problem: let problem) where problem?.noteId != nil {
            // The transcript already has a note (bound at upload, or drafted on the web): finish the meeting on it.
            let noteId = problem?.noteId ?? ""
            try? await finishMeeting(noteId: noteId)
            updateRecent(jobId: capture.jobId, noteId: noteId, errorMessage: "")
            if open { openNote(noteId) }
        } catch {
            updateRecent(jobId: capture.jobId, errorMessage: error.localizedDescription)
        }
    }

    @Published private(set) var drafting: Set<String> = []

    // MARK: - A note by hand (blank, or from a template)

    /// The template a bare "new note" starts from: meeting notes, English first.
    nonisolated static func defaultTemplate(_ list: [TemplateSummary], language: String = "en") -> TemplateSummary? {
        let live = list.filter { !$0.isArchived }
        return live.first { $0.code.hasPrefix("meeting_notes") && $0.language == language }
            ?? live.first { $0.code.hasPrefix("meeting_notes") }
            ?? live.first
    }

    /// Every template the workspace offers, live ones only.
    func templates() async throws -> [TemplateSummary] {
        if templateCache == nil { templateCache = try await api.fetchTemplates() }
        return (templateCache ?? []).filter { !$0.isArchived }
    }

    /// A note from the default template, opened at once.
    func createBlankNote() async {
        guard !creatingNote else { return }
        creatingNote = true
        defer { creatingNote = false }
        do {
            guard let template = Self.defaultTemplate(try await templates()) else {
                actionNotice = "Your workspace has no note templates yet."
                return
            }
            try await create(fromTemplate: template.id)
        } catch {
            actionNotice = AuthCopy.message(for: error)
        }
    }

    /// A note from the chosen template, opened at once.
    func createNote(fromTemplate id: String) async {
        guard !creatingNote else { return }
        creatingNote = true
        defer { creatingNote = false }
        do {
            try await create(fromTemplate: id)
            templatePickerPresented = false
        } catch {
            actionNotice = AuthCopy.message(for: error)
        }
    }

    private func create(fromTemplate id: String) async throws {
        // The full definition, so sections seed from their defaults.
        let detail = try await api.fetchTemplate(id: id)
        let created = try await api.createNote(content: detail.blankContent())
        await refreshNotes()
        openNote(created.id)
    }

    /// A recording made elsewhere, through the same pipeline. The file is copied first: the pipeline deletes what it uploads.
    func uploadRecording() {
        let panel = NSOpenPanel()
        panel.title = "Upload a recording"
        panel.prompt = "Upload"
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [.audio, .mpeg4Audio, .mp3, .wav, .aiff, .movie, .mpeg4Movie]
        NSApp.activate(ignoringOtherApps: true)
        guard panel.runModal() == .OK, let url = panel.url else { return }
        capture.upload(fileURL: url)
        NotificationCenter.default.post(name: .openMainWindow, object: nil)
    }

    /// Stop a transcription; the recents row says "Cancelled" at once.
    func cancelCapture(jobId: String) async {
        do {
            try await api.cancelJob(id: jobId)
            updateRecent(jobId: jobId, status: .cancelled)
        } catch {
            actionNotice = AuthCopy.message(for: error)
        }
    }

    // MARK: - Opening notes

    /// Show the meeting in the main window (opening the window if needed).
    func select(jobId: String) {
        selection = .capture(jobId: jobId)
        NotificationCenter.default.post(name: .openMainWindow, object: nil)
    }

    /// The fastest post-meeting path: open the note and go straight to the per-recipient link sheet.
    func shareWithClient(noteId: String) {
        pendingClientShare = noteId
        openNote(noteId)
    }

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

    /// The web app's password-reset page; a browser flow end to end.
    func openPasswordReset() {
        guard let url = URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "reset") else { return }
        NSWorkspace.shared.open(url)
    }

    /// Password, two-factor and email changes: the web app owns those screens.
    func openSecuritySettings() {
        guard let url = URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "settings/security") else { return }
        NSWorkspace.shared.open(url)
    }

    /// Where a new person creates an account: the web app owns signup (terms, confirmation mail, plan).
    var signupURL: URL? {
        // `/join` picks signup or the lead form by the server's config.
        URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "join")
    }

    func openSignup() {
        if let signupURL { NSWorkspace.shared.open(signupURL) }
    }

    /// Ask for another confirmation code. Throws so the screen can say why (rate limits, mostly).
    func resendSignupVerification(email address: String) async throws {
        try await api.resendSignupVerification(
            email: address.trimmingCharacters(in: .whitespaces))
    }

    /// Where an invited colleague signs in — the web app's login page.
    var inviteURL: URL? {
        URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?.appending(path: "login")
    }

    /// Settings › Data & AI in the web app, where the tier and the processor acknowledgement are changed.
    func openWebSettingsData() {
        if let url = URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "settings/data") {
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

    private func persistRecents() {
        guard let scope else { return }
        local.setRecents(recents, for: scope)
    }

    // MARK: - Local state, per identity and workspace (IDX-M2)

    /// Point local state at an identity and a workspace, leaving what was filed elsewhere alone.
    func applyScope(identityId: String, tenantId: String?) {
        guard !identityId.isEmpty, let tenantId, !tenantId.isEmpty else { return }
        let next = LocalScope(identityId: identityId, tenantId: tenantId)
        guard next != scope else { return }
        local.migrateLegacyRecents(into: next)
        scope = next
        recents = local.recents(for: next)
        local.remember(identityId: identityId, email: email, tenantId: tenantId)
        lastIdentity = local.lastIdentity
        // The template catalogue is per workspace: another's template id is a 404.
        templateCache = nil
    }

    /// Identities other than the current one with local state on this Mac.
    var otherLocalIdentities: [(id: String, email: String)] {
        local.otherIdentities(besides: identityId)
    }

    /// Delete one identity's local state. Local only.
    func removeLocalData(identityId: String) {
        local.removeLocalData(identityId: identityId)
        if lastIdentity?.identityId == identityId { lastIdentity = nil }
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


// MARK: - Workspaces (IDX-M2)

/// A workspace is the boundary everything is drawn inside (notes, spaces, meetings,
/// the `tid` claim). Switching is a new token minted by the server after it re-read
/// the membership, and everything local is re-read with it. Same file as `AppState`
/// on purpose: this reaches its private state.
extension AppState {

    /// Reload the list of workspaces, at most once every five minutes. The server stays the authority on every actual switch.
    func refreshWorkspaces(force: Bool = false) async {
        guard authState == .signedIn, !reconnecting else { return }
        if !force, let last = lastWorkspaceRefresh, last.timeIntervalSinceNow > -300 { return }
        guard let list = try? await api.workspaces() else { return }
        lastWorkspaceRefresh = Date()
        workspaces = list
        // The active workspace vanished from the list: find out properly rather than let the next request fail.
        if let tenantId, !list.isEmpty, !list.contains(where: { $0.id == tenantId }) {
            await moveToAnotherWorkspace(reason: nil)
        }
    }

    /// Move this Mac to another workspace: mint first (the server may refuse), then swap local state, then reload. Nothing local is thrown away.
    func switchWorkspace(to tenantId: String) async {
        guard tenantId != self.tenantId, switchingTo == nil else { return }
        switchingTo = tenantId
        defer { switchingTo = nil }
        do {
            let token = try await api.activateWorkspace(tenantId)
            workspaceNotice = nil
            adoptWorkspace(token.tenantId)
            await loadWorkspaceData()
        } catch let error as APIError {
            if let loss = WorkspaceLoss(code: error.code) {
                await noteWorkspaceLoss(loss, tenantId: tenantId)
            } else {
                // A network failure on a switch changes nothing.
                workspaceNotice = AuthCopy.message(for: error)
            }
        } catch {
            workspaceNotice = error.localizedDescription
        }
    }

    /// Take a workspace as the active one; local state follows it.
    func adoptWorkspace(_ tenantId: String) {
        self.tenantId = tenantId
        applyScope(identityId: identityId, tenantId: tenantId)
        selection = nil
        selectedSpaceId = nil
        notes = []
        setSpaces([])
    }

    func loadWorkspaceData() async {
        if let rules = try? await api.sharingConstraints() { sharingRules = rules }
        // Anything typed while offline goes up now. Idempotent on the capture id.
        await capture.syncPendingMeetingNotes()
        await refreshNotes()
        await refreshSpaces()
        await googleCalendar.refresh(force: true)
        await refreshWorkspaces(force: true)
    }

    /// A workspace refused us: say which and why, then move somewhere real.
    func noteWorkspaceLoss(_ loss: WorkspaceLoss, tenantId: String) async {
        let name = displayName(ofWorkspace: tenantId)
        workspaces.removeAll { $0.id == tenantId }
        memberships.removeAll { $0.tenantId == tenantId }
        await api.forgetToken(for: tenantId)
        if self.tenantId == tenantId {
            await moveToAnotherWorkspace(reason: loss.message(workspace: name))
        } else {
            workspaceNotice = loss.message(workspace: name)
        }
    }

    func displayName(ofWorkspace tenantId: String) -> String {
        workspaces.first { $0.id == tenantId }?.title
            ?? memberships.first { $0.tenantId == tenantId }?.name
            ?? "that workspace"
    }

    /// Leave the active workspace for one that still works: the personal one first, else any membership left; if none, the banner says so.
    private func moveToAnotherWorkspace(reason: String?) async {
        let previous = tenantId.map { displayName(ofWorkspace: $0) } ?? "that workspace"
        let personal = memberships.first { $0.kind == "personal" }?.tenantId
        let next = workspaces.first { $0.id == personal } ?? workspaces.first
        guard let next else {
            workspaceNotice = reason
                ?? "You no longer have access to \(previous), and this account has no other workspace."
            return
        }
        guard (try? await api.activateWorkspace(next.id)) != nil else {
            workspaceNotice = reason ?? "You no longer have access to \(previous)."
            return
        }
        adoptWorkspace(next.id)
        workspaceNotice = (reason ?? "You no longer have access to \(previous).")
            + " Switched to \(next.title)."
        await loadWorkspaceData()
    }
}


// MARK: - Holding the recordings that have not been sent

extension AppState: PendingUploadsHost {
    /// Sending needs a session and a server; either missing means the files wait.
    var canSendUploads: Bool { authState == .signedIn && !reconnecting }

    /// Whose recordings to show: whoever is signed in, or whoever was when the session expired offline.
    var uploadIdentityId: String {
        identityId.isEmpty ? (lastIdentity?.identityId ?? "") : identityId
    }

    var uploadLocalSpeakerName: String? { LocalSpeakerName.normalized(identity?.displayName) }

    func workspaceName(_ tenantId: String?) -> String {
        guard let tenantId else { return "that workspace" }
        return displayName(ofWorkspace: tenantId)
    }

    func uploaded(job: TranscriptionJob, capture: PendingCapture) async {
        adoptUploaded(job: job, capture: capture)
        await continuePipeline(jobId: job.id, capture: capture)
    }

    func workspaceLost(_ loss: WorkspaceLoss, tenantId: String) async {
        await noteWorkspaceLoss(loss, tenantId: tenantId)
    }
}
