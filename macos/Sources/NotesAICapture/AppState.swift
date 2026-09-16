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
        /// IDX-M2: who this Mac was last signed in as, so a session that
        /// expired while offline still knows whose recordings are waiting.
        /// Identifiers and an address — never a token.
        static let lastIdentity = "lastIdentity"
        /// Every identity that has local state on this Mac, so Settings can
        /// offer to remove somebody else's.
        static let knownIdentities = "knownIdentities"
        /// One-time move of the unscoped keys under the first identity.
        static let migratedV2 = "localStateMigratedV2"
    }

    /// What local state is filed under. Before IDX-M2 there was one
    /// bucket, so a second account signing in on the same Mac saw the
    /// first one's meetings — and a workspace switch showed the wrong
    /// workspace's list until the next refresh.
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
    /// The Settings sheet in the main window; the popover's menu sets it too.
    @Published var settingsPresented = false
    /// Which tab the Settings sheet opens on.
    @Published var settingsTab: SettingsTab = .general

    enum SettingsTab: Hashable, CaseIterable { case general, connectors, account, advanced }

    /// Open Settings on the Connectors tab (menus, the home page's prompt).
    func showConnectors() {
        settingsTab = .connectors
        settingsPresented = true
        NotificationCenter.default.post(name: .openMainWindow, object: nil)
    }
    /// What the main window's detail pane shows; nil is the home page.
    @Published var selection: Selection?

    /// The sidebar shrunk to an icon rail, persisted like the web app's.
    @Published var sidebarCollapsed: Bool {
        didSet { UserDefaults.standard.set(sidebarCollapsed, forKey: Keys.sidebarCollapsed) }
    }

    func toggleSidebar() {
        withAnimation(.easeOut(duration: 0.18)) { sidebarCollapsed.toggle() }
    }

    /// The "Invite people" sheet in the main window.
    @Published var invitePresented = false

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
    /// Recordings this Mac is still holding (IDX-M2).
    private(set) lazy var pending = PendingUploads(host: self)
    private var templateCache: [TemplateSummary]?

    init() {
        let stored = Self.loadSettings()
        self.settings = stored
        self.email = UserDefaults.standard.string(forKey: Keys.email) ?? ""
        self.api = APIClient(settings: stored)
        // Recents belong to an identity and a workspace (IDX-M2). Until the
        // session is restored the best guess is where this Mac was last
        // signed in — which is also what a session that expired offline
        // still has to show.
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

    /// Who is signed in, once the server has said so. Kept for the account
    /// screen and for the sidecar written beside a recording that could
    /// not be uploaded — a file on disk should say whose it is.
    @Published private(set) var identity: IdentitySummary?
    /// Every workspace this identity can reach. Read-only until IDX-M2:
    /// there is no endpoint to switch between them yet.
    @Published private(set) var memberships: [MembershipSummary] = []
    @Published private(set) var tenantId: String?
    /// Signed in from the stored session, but the server has not confirmed
    /// it yet (the Mac woke up on a plane). The window shows a banner and
    /// the app makes no requests until the person does something.
    @Published private(set) var reconnecting = false
    /// Why the app last dropped to the sign-in screen, shown there once.
    @Published var signedOutNotice: String?
    /// The step-up sheet, when an endpoint asks for recent proof.
    @Published var reauth: ReauthPrompt?
    /// "N recordings are not uploaded yet" — shown before signing out.
    @Published var signOutPrompt = false

    // ── workspaces (IDX-M2) ──────────────────────────────────────────

    /// Every workspace this identity can reach, newest membership list
    /// from the server; `memberships` is what sign-in knew, this is what
    /// is true now.
    @Published private(set) var workspaces: [Tenant] = []
    /// A switch in flight, so the switcher can show which one.
    @Published private(set) var switchingTo: String?
    /// A workspace this Mac can no longer reach, and why. Shown as a
    /// banner until dismissed; its local state stays on disk.
    @Published var workspaceNotice: String?
    /// Set when the session expired while this Mac was away from the
    /// network: nothing is lost, but nothing can be sent either.
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
            // The session is real; the server just could not be reached to
            // prove it. Never wipe a session for a network error — that
            // turns a flaky connection into a sign-out.
            adopt(stored)
            reconnecting = true
            authState = .signedIn
        case .expired(let stored):
            // Thirty days offline, or a Mac that spent the month in a bag.
            // The session is genuinely over, but nothing local goes with
            // it: the recordings waiting here are still this person's, and
            // signing in as them picks them up where they were.
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

    /// Send whatever is waiting, if there is anything and anyone to send
    /// it as. Called after a sign-in and after reconnecting — never on a
    /// timer, so a Mac that is offline for a week does not spend the week
    /// retrying.
    func retryPendingUploads() async {
        guard authState == .signedIn, !reconnecting else { return }
        pending.reload()
        guard !pending.isEmpty else { return }
        await pending.retryAll()
    }

    /// A kept recording finally reached the server: file it under the
    /// workspace it belongs to, which is not necessarily the active one.
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
        // Another workspace's meeting: write it into that workspace's list
        // without disturbing the one on screen.
        local.addRecent(recent, to: LocalScope(identityId: identityId, tenantId: tenantId))
    }

    /// Carry a re-sent recording the rest of the way: poll the job, then
    /// draft its note, in the workspace it was recorded in.
    ///
    /// Returns as soon as the polling is started — the next kept recording
    /// should not wait for this one's transcript.
    func continuePipeline(jobId: String, capture: PendingCapture) async {
        let tenant = capture.info.tenantId
        let title = capture.info.title
        Task { [weak self] in
            guard let self else { return }
            var status: JobStatus = .queued
            // Roughly half an hour at three seconds a turn; a job still
            // running after that is one the recents list will pick up.
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

    /// A `notesai://` link arrived. The OAuth and calendar callbacks are
    /// intercepted before they reach here (`ASWebAuthenticationSession`
    /// and a loopback listener), so in practice this is invitations.
    func handle(_ url: URL) {
        switch AppURL.parse(url) {
        case .invite(let token):
            pendingInviteToken = token
            NotificationCenter.default.post(name: .openMainWindow, object: nil)
            // IDX-B1 has not been built: no server in this estate can issue
            // or redeem an invitation. Saying so is the honest answer; a
            // preview sheet built against an endpoint that returns 404
            // would be a screen that renders and lies.
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

    /// Sign out, unless there are recordings that have not been sent yet —
    /// then ask first. "Sign out" and "throw away this morning's meeting"
    /// should never be the same click.
    func requestSignOut() {
        if pendingCount > 0 {
            // The prompt lives on the main window; from the popover there
            // may not be one on screen yet.
            NotificationCenter.default.post(name: .openMainWindow, object: nil)
            signOutPrompt = true
        } else {
            Task { await signOut() }
        }
    }

    // ── the sign-in flows (IDX-M1 F) ─────────────────────────────────

    /// Mail a one-time code. The reply says nothing about whether the
    /// address is known — by design, upstream.
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

    /// The welcome step's one field. Skipping it is fine: the server has
    /// already defaulted the display name to the address's local part.
    func setDisplayName(_ name: String) async {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        identity = try? await api.setDisplayName(trimmed)
    }

    /// Fill in who is signed in after a restart. `GET /auth/me` still
    /// answers the pre-IDX `{claims, db_user}` shape (`routers/me.py` is
    /// IDX-B2's to extend), so this is a no-op today and the account screen
    /// falls back to the address the Keychain item carries.
    private func hydrateIdentity() async {
        guard let response = try? await api.me() else { return }
        if let identity = response.identity { self.identity = identity }
        if let memberships = response.memberships { self.memberships = memberships }
    }

    func signOut() async {
        await api.logout()
        clearSignedInState()
        signedOutNotice = nil
        authState = .signedOut
    }

    /// The session is gone for good (expired, revoked, replayed): drop to
    /// the sign-in form with the reason, which is the one thing the person
    /// needs to know and the one thing a bare "sign in" screen never says.
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

    // ── step-up (plumbing; IDX-M2 uses it) ───────────────────────────

    /// Ask the person to prove it is them, and answer whether they did.
    ///
    /// Called from the API client's actor, so it hops to the main actor,
    /// puts a sheet up, and waits for the sheet to answer — the request
    /// that triggered it is retried once on `true`.
    func presentReauth() async -> Bool {
        guard authState == .signedIn else { return false }
        let options = try? await api.startReauth()
        // The sheet lives in the main window; from the menu-bar popover
        // there may be no window to put it in, so ask for one.
        NotificationCenter.default.post(name: .openMainWindow, object: nil)
        return await withCheckedContinuation { continuation in
            // Resumed exactly once, by whichever comes first: the sheet, or
            // the deadline. A continuation that is never resumed would hang
            // the request that asked — and every request queued behind it.
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

    /// The identity id behind the current session, for the sidecar written
    /// beside a recording that could not be uploaded.
    private(set) var identityId: String = ""
    /// Which identity + workspace local state is currently filed under.
    private(set) var scope: LocalScope?
    /// Where that state actually lives.
    private let local: LocalStore
    private var urlObserver: NSObjectProtocol?
    /// An invitation token from a `notesai://invite/…` link, held in memory
    /// for as long as it takes to use it — never written anywhere (IDX-M2 G).
    private(set) var pendingInviteToken: String?
    /// Who this Mac was last signed in as. Survives an expired session, so
    /// the recordings kept for that person can still be found and named.
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

    /// The notes for the home page: the current search, narrowed to the
    /// selected space.
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

    /// Reload the spaces from the server. The first time after this
    /// device's local spaces (pre-0021) are found, they are moved up.
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

    /// Move the spaces this device kept in UserDefaults to the server —
    /// once. Returns the server list afterwards, nil when there was
    /// nothing to move.
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

    /// The web app's password-reset page. Resetting a password is a
    /// browser flow end to end (the link the server mails lands there), so
    /// the app hands it over rather than half-implementing it.
    func openPasswordReset() {
        guard let url = URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "reset") else { return }
        NSWorkspace.shared.open(url)
    }

    /// Password, two-factor and email changes: the web app owns those
    /// screens, and a second implementation of them on the Mac would be a
    /// second thing to keep correct about somebody's account.
    func openSecuritySettings() {
        guard let url = URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "settings/security") else { return }
        NSWorkspace.shared.open(url)
    }

    /// MAC-0: where a new person creates an account.
    ///
    /// The Mac does not carry a signup form of its own. An account is more
    /// than a row in `users` — terms, the confirmation mail, whatever the
    /// plan turns out to be — and every one of those is a page the web app
    /// already owns and would have to be kept in step with a second time
    /// here. The Mac's job is to get the person to it and to be ready when
    /// they come back.
    var signupURL: URL? {
        URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "signup")
    }

    func openSignup() {
        if let signupURL { NSWorkspace.shared.open(signupURL) }
    }

    /// Ask for another confirmation code, for the account that just told
    /// us it has not confirmed one. Throws so the screen can say why it
    /// failed (rate limits, mostly) rather than silently doing nothing.
    func resendSignupVerification(email address: String) async throws {
        try await api.resendSignupVerification(
            email: address.trimmingCharacters(in: .whitespaces))
    }

    /// Where an invited colleague signs in — the web app's login page.
    var inviteURL: URL? {
        URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?.appending(path: "login")
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

    /// Point local state at an identity and a workspace, loading what is
    /// filed there and leaving what was filed elsewhere alone.
    func applyScope(identityId: String, tenantId: String?) {
        guard !identityId.isEmpty, let tenantId, !tenantId.isEmpty else { return }
        let next = LocalScope(identityId: identityId, tenantId: tenantId)
        guard next != scope else { return }
        local.migrateLegacyRecents(into: next)
        scope = next
        recents = local.recents(for: next)
        local.remember(identityId: identityId, email: email, tenantId: tenantId)
        lastIdentity = local.lastIdentity
        // The template catalogue is per workspace: a template id from
        // another one is a 404 waiting to happen.
        templateCache = nil
    }

    /// Identities other than the current one with local state on this Mac.
    var otherLocalIdentities: [(id: String, email: String)] {
        local.otherIdentities(besides: identityId)
    }

    /// Delete one identity's local state. Local only — nothing on the
    /// server is touched.
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

/// A workspace is the boundary everything else is drawn inside: the notes
/// a search returns, the spaces in the sidebar, the meetings in the list,
/// and the `tid` claim every service filters rows by. Switching is
/// therefore not a display preference — it is a new token, minted by the
/// server after it has re-read the membership, and everything local is
/// re-read with it.
///
/// (Same file as `AppState` on purpose: this reaches its private state,
/// and widening that access for the sake of a second file would be the
/// tail wagging the dog.)
extension AppState {

    /// Reload the list of workspaces, at most once every five minutes.
    ///
    /// Invitations accepted elsewhere, a role changed by an admin and a
    /// membership removed all show up here. The server stays the authority
    /// on every actual switch, so this list only has to be roughly fresh.
    func refreshWorkspaces(force: Bool = false) async {
        guard authState == .signedIn, !reconnecting else { return }
        if !force, let last = lastWorkspaceRefresh, last.timeIntervalSinceNow > -300 { return }
        guard let list = try? await api.workspaces() else { return }
        lastWorkspaceRefresh = Date()
        workspaces = list
        // The active workspace vanishing from the list is a removal
        // somebody else made. Find out properly rather than letting the
        // next request the person makes fail in front of them.
        if let tenantId, !list.isEmpty, !list.contains(where: { $0.id == tenantId }) {
            await moveToAnotherWorkspace(reason: nil)
        }
    }

    /// Move this Mac to another workspace.
    ///
    /// Mint first (the server may refuse), then swap the local state, then
    /// reload. Nothing local is thrown away — the other workspace's
    /// meetings stay filed under its own key.
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
                // A network failure on a switch changes nothing: the person
                // stays where they were and is told the attempt failed.
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

    /// Leave the active workspace for one that still works.
    ///
    /// The personal workspace first — the server self-heals every identity
    /// into one — otherwise whatever membership is left. Being signed in
    /// with nowhere to be is a state worth never producing; if there is
    /// genuinely nowhere, the banner says so and the local state stays put.
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
    /// Sending needs a session and a server; either missing means the
    /// files simply wait, which is the whole point of keeping them.
    var canSendUploads: Bool { authState == .signedIn && !reconnecting }

    /// Whose recordings to show: whoever is signed in, or — when a session
    /// expired offline — whoever was.
    var uploadIdentityId: String {
        identityId.isEmpty ? (lastIdentity?.identityId ?? "") : identityId
    }

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
