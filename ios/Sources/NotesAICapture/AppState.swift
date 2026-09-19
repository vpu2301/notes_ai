import Foundation
import UIKit

/// Central app state: settings, auth, template cache, recent captures, and
/// the navigation stack. Only base URLs and the email are persisted — never
/// passwords or tokens.
@MainActor
final class AppState: ObservableObject {
    enum AuthState: Equatable {
        case restoring
        case signedOut
        /// There is a session on this phone, behind the biometric gate.
        /// Nothing carrying a token is sent until it is opened.
        case locked
        case signedIn
    }

    private enum Keys {
        static let settings = "backendSettings"
        static let email = "accountEmail"
        static let theme = "themePref"
        /// Pre-0021 local spaces, read once and moved to the server.
        static let legacySpaces = "spaces"
        static let legacySpaceOf = "spaceOfNote"
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
    /// The Settings sheet.
    @Published var settingsPresented = false
    /// Which page the Settings sheet opens on.
    @Published var settingsTab: SettingsTab = .general

    enum SettingsTab: Hashable { case general, connectors, account }

    /// Open Settings on the Connectors page (menus, the home page's prompt).
    func showConnectors() {
        settingsTab = .connectors
        settingsPresented = true
    }

    /// The pages pushed over the home page. Empty = home.
    @Published var path: [Selection] = []

    /// The page on top, if any; nil is the home page.
    var selection: Selection? { path.last }

    /// Push a page (a no-op when it is already on top).
    func show(_ selection: Selection) {
        if path.last != selection { path.append(selection) }
    }

    func goHome() {
        path.removeAll()
    }

    // MARK: Notes list, search, spaces (home page)

    /// Every note in the tenant the user can see, newest first (server search).
    @Published private(set) var notes: [NoteSummary] = []
    @Published private(set) var notesLoading = false
    @Published private(set) var notesError: String?
    /// The search box; runs the server's full-text search, debounced.
    @Published var searchQuery = "" {
        didSet { scheduleSearch() }
    }
    /// nil = every note; otherwise only the notes filed in that space.
    @Published var selectedSpaceId: String?
    let calendar = CalendarService()
    /// Google Calendar connected on the server (shared with the web app).
    private(set) lazy var googleCalendar = GoogleCalendarService(api: api)
    /// Remote MCP servers (HubSpot, Notion, …) connected on this phone.
    let connectors = ConnectorStore()
    private var searchTask: Task<Void, Never>?
    /// Light / dark / follow-system, persisted; applied at the root view.
    @Published var themePref: ThemePref {
        didSet { UserDefaults.standard.set(themePref.rawValue, forKey: Keys.theme) }
    }

    let api: APIClient
    private(set) lazy var capture = CaptureViewModel(app: self)
    private var templateCache: [TemplateSummary]?

    init() {
        let stored = Self.loadSettings()
        self.settings = stored
        self.email = UserDefaults.standard.string(forKey: Keys.email) ?? ""
        // Before the client exists, and so before anything can be sent:
        // the refresh cookie this app used to sign in with is deleted. It
        // is read by nothing — even the Keycloak login hands a native
        // client its token in the body — and a credential nothing reads is
        // one nobody rotates. The saved **password** is deliberately left
        // alone during `dual`; see `SessionMigration`.
        self.signedOutNotice = SessionMigration.run()
        self.api = APIClient(settings: stored)
        // Recents are not loaded here: until `restoreSession` says which
        // identity and which workspace, there is no answer to "whose?" —
        // and IDX-I2's whole point is that the question has an answer.
        self.themePref = ThemePref(rawValue: UserDefaults.standard.string(forKey: Keys.theme) ?? "") ?? .system
        Task { [weak self] in
            guard let api = self?.api else { return }
            await api.onSessionLost { [weak self] reason in
                Task { @MainActor in self?.sessionEnded(reason) }
            }
            await api.onLocked { [weak self] in
                Task { @MainActor in self?.gateShut() }
            }
            await api.onReauthRequired { [weak self] in
                await self?.presentReauth() ?? false
            }
            await self?.restoreSession()
        }
        Task { await connectors.recheck() }
    }

    // MARK: - Auth

    /// Who is signed in, once the server has said so. Kept for the account
    /// screen and for the sidecar written beside a recording that could
    /// not be uploaded — a file on disk should say whose it is.
    @Published private(set) var identity: IdentitySummary?
    /// Every workspace this identity can reach. Read-only until IDX-I2:
    /// there is no endpoint to switch between them yet.
    @Published private(set) var memberships: [MembershipSummary] = []
    @Published private(set) var tenantId: String?
    /// The identity id behind the current session, for the sidecar written
    /// beside a recording that could not be uploaded.
    private(set) var identityId: String = ""
    /// Signed in from the stored session, but the server has not confirmed
    /// it yet (the phone woke up on a plane). A banner says so, and the app
    /// makes no requests until the person does something.
    @Published private(set) var reconnecting = false
    /// Why the app last dropped to the sign-in screen, shown there once.
    @Published var signedOutNotice: String?
    /// The step-up sheet, when an endpoint asks for recent proof.
    @Published var reauth: ReauthPrompt?
    /// Which issuer minted the session this phone is holding (ADR-0047).
    /// Drives three things the person can see: whether there is a password
    /// worth saving, whether the workspace switcher works, and whether the
    /// gate can be offered at all.
    @Published private(set) var sessionKind: SessionKind?
    /// Whether "Require Face ID to open" is on, for the Settings toggle.
    @Published private(set) var gateOn = false

    /// Whether the biometric gate is offered in Settings at all.
    ///
    /// **Off for this batch (IOS-1).** The machinery is built and tested
    /// (IDX-I1 I1-01) and the gate can be turned on, but during `dual` a
    /// phone can hold either kind of session and a toggle that silently
    /// does nothing for half the user base is worse than no toggle. It
    /// comes back with I1-05, once A4/A5 has made every session native.
    static let gateOffered = false

    /// Whether this phone's session could carry the gate if it were
    /// offered — native sessions only.
    @Published private(set) var canGate = false
    /// Set while the unlock prompt is up, so the locked screen does not
    /// offer a second one behind the first.
    @Published private(set) var unlocking = false

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
            gateOn = await api.isGateOn()
            sessionKind = nil
            canGate = false
            authState = .signedOut
        case .signedIn(let summary):
            adopt(summary)
            reconnecting = false
            authState = .signedIn
            await hydrateIdentity()
            await loadWorkspace()
        case .locked(let summary):
            adopt(summary)
            authState = .locked
            // Ask straight away: a cold start with the gate on should show
            // Face ID, not a screen with a button that shows Face ID.
            await unlock()
        case .offline(let summary):
            // The session is real; the server just could not be reached to
            // prove it. Never wipe a session for a network error — that
            // turns a flaky connection into a sign-out.
            adopt(summary)
            reconnecting = true
            authState = .signedIn
        }
    }

    private func adopt(_ summary: SessionSummary) {
        if !summary.email.isEmpty {
            email = summary.email
            UserDefaults.standard.set(summary.email, forKey: Keys.email)
        }
        identityId = summary.identityId
        tenantId = summary.lastTenantId
        gateOn = summary.gated
        sessionKind = summary.kind
        canGate = summary.kind.canGate
        applyScope()
    }

    /// Try the server again after a "Reconnecting…" banner.
    func reconnect() async {
        guard reconnecting else { return }
        await restoreSession()
    }

    // ── the biometric gate (IDX-I1 D, F) ─────────────────────────────

    /// Open the gate and carry on into the app. A cancelled prompt leaves
    /// the locked screen up; a changed face empties the Keychain item and
    /// says so, because nothing on this phone can read that session again.
    func unlock() async {
        guard authState == .locked, !unlocking else { return }
        unlocking = true
        defer { unlocking = false }
        do {
            guard try await api.unlock() else { return }
            await restoreSession()
        } catch SessionStoreError.gateLost {
            clearSignedInState()
            gateOn = false
            signedOutNotice = SessionLostReason.biometryChanged.message
            authState = .signedOut
        } catch {
            signedOutNotice = error.localizedDescription
        }
    }

    /// Turn "Require Face ID to open" on or off.
    func setGate(enabled: Bool) async -> String? {
        guard canGate else {
            return SessionStoreError.gateUnavailable.errorDescription
        }
        do {
            try await api.setGate(enabled: enabled)
            gateOn = await api.isGateOn()
            return nil
        } catch {
            gateOn = await api.isGateOn()
            return error.localizedDescription
        }
    }

    /// Something needed the refresh token while the gate was shut.
    private func gateShut() {
        guard authState == .signedIn else { return }
        authState = .locked
    }

    // ── the sign-in flows (IDX-I1 F) ─────────────────────────────────

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
            applyScope()
            gateOn = await api.isGateOn()
            sessionKind = await api.sessionKind
            canGate = await api.canGate()
            signedOutNotice = nil
            reconnecting = false
            authState = .signedIn
            await loadWorkspace()
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
    /// Sprint 21: true for an account younger than a day that has not
    /// dismissed the "record your first meeting" card on this device.
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

    /// Sprint 23: what the workspace admin allows. Permissive until known,
    /// so an older server changes nothing.
    @Published private(set) var sharingRules: SharingConstraints = .permissive

    private func loadWorkspace() async {
        if let rules = try? await api.sharingConstraints() { sharingRules = rules }
        await refreshWorkspaces(force: true)
        refreshPending()
        await refreshNotes()
        await refreshSpaces()
        await googleCalendar.refresh(force: true)
    }

    func signOut() async {
        await api.logout()
        clearSignedInState()
        gateOn = await api.isGateOn()
        signedOutNotice = nil
        authState = .signedOut
    }

    /// The session is gone for good (expired, revoked, replayed, or behind
    /// a face that no longer exists): drop to the sign-in form with the
    /// reason, which is the one thing the person needs to know and the one
    /// thing a bare "sign in" screen never says.
    private func sessionEnded(_ reason: SessionLostReason) {
        guard authState == .signedIn || authState == .locked else { return }
        clearSignedInState()
        signedOutNotice = reason.message
        authState = .signedOut
    }

    private func clearSignedInState() {
        googleCalendar.reset()
        templateCache = nil
        notes = []
        setSpaces([])
        path = []
        settingsPresented = false
        identity = nil
        memberships = []
        tenantId = nil
        identityId = ""
        reconnecting = false
        reauth = nil
        workspaces = []
        workspaceLost = false
        lastWorkspaceRefresh = nil
        // The recents stay on disk under their scope; only this session's
        // view of them is dropped. Signing back in brings them back, and
        // Settings › Account is where they are actually removed.
        scope = nil
        recents = []
        pending = []
        sessionKind = nil
        canGate = false
    }

    /// Where an account is created: the web app, in Safari.
    ///
    /// Signup is a web flow (BE-0) and stays one. It needs a confirmable
    /// mailbox, terms to accept and a workspace name — a form with more
    /// text in it than this screen has room for, on a device where typing
    /// an address twice is a chore. The app's job is to hand the person
    /// over and to sign them in afterwards, which it already does: a BE-0
    /// account is an ordinary password account here.
    func openSignup() {
        // Sprint 21: `/join` picks signup or the lead form by the server's
        // config, so the app never has to know which one is on.
        guard let url = URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "join") else { return }
        UIApplication.shared.open(url)
    }

    /// Mail the confirmation link again, for an account that has not
    /// followed it yet. Returns the sentence to show either way — this is
    /// the one place in the sign-in flow where nothing visible happens on
    /// success, so silence would read as a broken button.
    func resendVerification(to address: String) async -> String {
        do {
            try await api.resendVerification(email: address)
            return "Sent. Check your inbox — and your spam folder."
        } catch {
            return AuthCopy.message(for: error)
        }
    }

    /// Where a forgotten password is reset: the web app, in Safari. There
    /// is no reset flow in the app, and there should not be one — the
    /// mailed code already signs anybody in without a password.
    func openPasswordReset() {
        guard let url = URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "reset") else { return }
        UIApplication.shared.open(url)
    }

    // ── step-up (plumbing; IDX-I2 uses it) ───────────────────────────

    /// Ask the person to prove it is them, and answer whether they did.
    ///
    /// Called from the API client's actor, so it hops to the main actor,
    /// puts a sheet up, and waits for the sheet to answer — the request
    /// that triggered it is retried once on `true`.
    func presentReauth() async -> Bool {
        guard authState == .signedIn else { return false }
        let options = try? await api.startReauth()
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

    // MARK: - Links into the app (IDX-I2 I2-04)

    /// A link that opens the app.
    ///
    /// `notesai://` for now. Universal links on the web host (I2-04) are
    /// **not** built: invitations have no server — no table in any
    /// migration, no router in auth-service, no `/invite/:token` page in
    /// the web app — and IDX-W1 and IDX-W2 recorded the same gate before
    /// this sprint. The parsing is here so that when IDX-B1 lands, the
    /// only new work is the preview sheet and the entitlement.
    enum AppLink: Equatable {
        case invite(token: String)
        case note(id: String)

        init?(_ url: URL) {
            guard url.scheme?.lowercased() == "notesai" else { return nil }
            // notesai://invite/<token> parses as host "invite", path "/<token>".
            let parts = ([url.host()] + url.pathComponents.filter { $0 != "/" })
                .compactMap { $0 }
            guard parts.count >= 2 else { return nil }
            switch parts[0] {
            case "invite": self = .invite(token: parts[1])
            case "notes": self = .note(id: parts[1])
            default: return nil
            }
        }
    }

    /// Something to say about the link that was just opened, shown once on
    /// the home page.
    @Published var linkNotice: String?

    /// Handle a link. OAuth callbacks (`notesai://oauth/callback`,
    /// `notesai://calendar/connected`) never reach here — the
    /// `ASWebAuthenticationSession` that started them intercepts its own
    /// redirect, which is what keeps a callback from being replayable by
    /// anything else that can open a URL.
    func handle(_ url: URL) {
        guard let link = AppLink(url) else { return }
        switch link {
        case .note(let id):
            guard authState == .signedIn else { return }
            openNote(id)
        case .invite:
            // The token is deliberately not kept: there is nothing that
            // can redeem it, and an unredeemable credential sitting in
            // memory is only a liability.
            linkNotice = "This invitation link cannot be opened yet. Ask whoever sent it to add you to their workspace from Notes AI instead."
        }
    }

    // MARK: - Workspaces (IDX-I2)

    /// Every workspace this identity belongs to, newest reading of the
    /// membership table. Empty until the first `GET /tenants` answers.
    @Published private(set) var workspaces: [Workspace] = []
    /// True when the workspace this session is in is no longer one of
    /// them — someone removed the membership while the app was open, or
    /// while it was in a pocket. Everything local becomes read-only and
    /// the pending recordings need somewhere else to go.
    @Published private(set) var workspaceLost = false
    /// Set while `POST /auth/token` is in flight, so the switcher can
    /// show which row is being moved to.
    @Published private(set) var switchingTo: String?
    private var lastWorkspaceRefresh: Date?
    /// How often the membership list is re-read on foreground activation.
    private static let workspaceRefreshInterval: TimeInterval = 300

    var activeWorkspace: Workspace? {
        guard let tenantId else { return nil }
        return workspaces.first { $0.id == tenantId }
    }

    /// The workspaces this identity can still send a recording to.
    var availableWorkspaces: [Workspace] {
        workspaces.filter { $0.isActive && $0.status == "active" }
    }

    /// Re-read the membership list.
    ///
    /// `GET /tenants`, not `GET /auth/me` — the pack asks for the latter,
    /// but `routers/me.py` still answers the pre-IDX `{claims, db_user}`
    /// shape and carries no memberships at all (IDX-B2 debt). The tenant
    /// list is the same fact from the table that would have fed it.
    func refreshWorkspaces(force: Bool = false) async {
        guard authState == .signedIn else { return }
        if !force, let last = lastWorkspaceRefresh,
           Date().timeIntervalSince(last) < Self.workspaceRefreshInterval { return }
        do {
            let list = try await api.workspaces()
            lastWorkspaceRefresh = Date()
            workspaces = list
            // A membership that has gone is the only thing this call can
            // discover that the rest of the app cannot.
            if let tenantId, !list.contains(where: { $0.id == tenantId }) {
                workspaceLost = true
            } else {
                workspaceLost = false
            }
        } catch {
            // Offline, or a 5xx: the list the app has is the last one the
            // server confirmed, and it is better than none. A membership
            // is never dropped on a failed request.
        }
    }

    /// Move this session to another workspace.
    ///
    /// The local state moves with it: recents are re-read from the new
    /// scope, notes and spaces from the server under the new token. In
    /// between there is a moment with neither, which is honest — the app
    /// genuinely does not know yet.
    /// Whether this session can switch workspace at all.
    ///
    /// `POST /auth/token` re-mints an access token for another `tid`, and
    /// auth-service cannot re-mint a Keycloak token without Keycloak's
    /// key — so during the dual-issuer period the switch is a native-only
    /// capability and a Keycloak session gets `409 legacy_session`
    /// (ADR-0047, recorded there up front). Better to say so on the button
    /// than to let the tap earn a 409.
    var canSwitchWorkspace: Bool { sessionKind?.canGate ?? false }

    func switchWorkspace(to workspace: Workspace) async {
        guard workspace.id != tenantId, switchingTo == nil else { return }
        guard canSwitchWorkspace else {
            notesError = AuthCopy.message(status: 409, problem: Problem(title: nil, detail: nil, status: 409, code: "legacy_session"))
            return
        }
        switchingTo = workspace.id
        defer { switchingTo = nil }
        do {
            let switched = try await api.switchWorkspace(to: workspace.id)
            tenantId = switched.tenantId
            workspaceLost = false
            applyScope()
            // Anything on screen belongs to the workspace being left.
            path = []
            selectedSpaceId = nil
            searchQuery = ""
            notes = []
            setSpaces([])
            templateCache = nil
            refreshPending()
            await refreshNotes()
            await refreshSpaces()
            await googleCalendar.refresh(force: true)
            await refreshWorkspaces(force: true)
        } catch {
            notesError = AuthCopy.message(for: error)
        }
    }

    // MARK: - Local state, per identity and workspace

    /// Which identity's and which workspace's data this app is showing.
    /// Nil when signed out, and then nothing local is written.
    private(set) var scope: StateScope?

    /// Point the local state at the current identity and workspace.
    private func applyScope() {
        let next = StateScope.of(identityId: identityId, tenantId: tenantId)
        guard next != scope else { return }
        scope = next
        guard let next else {
            recents = []
            return
        }
        // The first identity to sign in after the update inherits the
        // unscoped recents this app used to keep. Once.
        ScopedDefaults.migrateLegacy(into: next)
        recents = RecentsStore(scope: next).load()
    }

    /// Scopes on this phone that belong to somebody else, or to a
    /// workspace this identity has left. Offered for removal in Settings;
    /// never removed automatically — it is the person's data, and a phone
    /// that quietly forgets things is worse than one that asks.
    var otherScopes: [StateScope] {
        ScopedDefaults.allScopes()
            .filter { $0 != scope }
            .sorted { $0.suffix < $1.suffix }
    }

    func removeLocalData(for scopes: [StateScope]) {
        for scope in scopes where scope != self.scope {
            ScopedDefaults.removeAll(for: scope)
        }
        objectWillChange.send()
    }

    // MARK: - Recordings waiting to be uploaded (IDX-I2 I2-03)

    /// The recordings IDX-I1 kept when their upload failed, this
    /// identity's only.
    @Published private(set) var pending: [PendingCapture] = []
    /// Ids with a retry in flight.
    @Published private(set) var retrying: Set<String> = []
    /// Why the last retry failed, by capture id.
    @Published private(set) var pendingErrors: [String: String] = [:]

    func refreshPending() {
        pending = identityId.isEmpty ? [] : PendingCaptures.all(identityId: identityId)
    }

    /// Recordings left by an identity that is not signed in here any more.
    var oldPending: [PendingCapture] {
        PendingCaptures.old(excluding: identityId)
    }

    /// Whether this recording can be sent at all: its workspace has to be
    /// one this identity is still in. The client never uploads to a
    /// workspace it already knows it left.
    func canRetry(_ capture: PendingCapture) -> Bool {
        !PendingCaptures.needsWorkspace(capture, memberships: availableWorkspaces.map(\.id))
    }

    /// Upload a kept recording and turn it into a note.
    ///
    /// The file is deleted only once the server has a job for it —
    /// `submitJob` returning is the first moment at which the recording
    /// exists anywhere but this phone.
    func retryPending(_ capture: PendingCapture) async {
        guard authState == .signedIn, !retrying.contains(capture.id) else { return }
        retrying.insert(capture.id)
        pendingErrors[capture.id] = nil
        defer { retrying.remove(capture.id) }
        do {
            let job = try await api.submitJob(
                fileURL: capture.audioURL,
                contentType: contentType(of: capture.audioURL),
                language: capture.info.language,
                diarize: capture.info.diarize,
                tenantId: capture.info.tenantId)
            // On the server now: the file may go.
            PendingCaptures.delete(capture)
            refreshPending()
            addRecent(jobId: job.id, title: capture.info.title)
            show(.capture(jobId: job.id))
            await self.capture.follow(jobId: job.id, title: capture.info.title,
                                      language: capture.info.language)
        } catch {
            pendingErrors[capture.id] = AuthCopy.message(for: error)
            refreshPending()
        }
    }

    /// Send this recording to another workspace instead.
    func retargetPending(_ capture: PendingCapture, to workspace: Workspace) {
        _ = PendingCaptures.retarget(capture, to: workspace.id)
        pendingErrors[capture.id] = nil
        refreshPending()
    }

    /// Delete a kept recording. Only ever called from a confirmation.
    func deletePending(_ capture: PendingCapture) {
        PendingCaptures.delete(capture)
        pendingErrors[capture.id] = nil
        refreshPending()
    }

    private func contentType(of url: URL) -> String {
        switch url.pathExtension.lowercased() {
        case "wav": return "audio/wav"
        case "m4a": return "audio/mp4"
        default: return "audio/flac"
        }
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
            notesError = nil
        } catch {
            notesError = AuthCopy.message(for: error)
            // The usual way a removed membership announces itself is that
            // the workspace's own data stops being served. Ask the
            // membership table rather than guessing from one 403.
            if (error as? APIError)?.status == 403 {
                await refreshWorkspaces(force: true)
            }
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

    /// The note is gone (deleted here or from the note page): forget it.
    func noteDeleted(_ noteId: String) {
        notes.removeAll { $0.noteId == noteId }
        var list = spaces
        for index in list.indices { list[index].noteIds.removeAll { $0 == noteId } }
        setSpaces(list)
        let jobs = Set(recents.filter { $0.noteId == noteId }.map(\.jobId))
        recents.removeAll { jobs.contains($0.jobId) }
        persistRecents()
        path.removeAll { page in
            switch page {
            case .note(let id): return id == noteId
            case .capture(let job): return jobs.contains(job)
            }
        }
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
        if recents.count > RecentsStore.limit { recents = Array(recents.prefix(RecentsStore.limit)) }
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
        path.removeAll { page in
            if case .capture(let job) = page { return jobIds.contains(job) }
            return false
        }
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

    /// Show the meeting's page.
    func select(jobId: String) {
        show(.capture(jobId: jobId))
    }

    /// Open a note inside this app. A note that came from one of this
    /// phone's captures opens as that capture (so the transcript tab is there).
    func openNote(_ noteId: String) {
        if let recent = recents.first(where: { $0.noteId == noteId }) {
            show(.capture(jobId: recent.jobId))
        } else {
            show(.note(noteId: noteId))
        }
    }

    /// The note id behind the current page, if it has one.
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
            UIApplication.shared.open(url)
        }
    }

    func openWebApp() {
        if let url = URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces)) {
            UIApplication.shared.open(url)
        }
    }

    /// Passwords, second factors and account deletion are the web app's:
    /// they are rare, they are typed, and none of them belongs behind a
    /// thumb on a train.
    func openSecuritySettings() {
        guard let url = URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "settings/security") else { return }
        UIApplication.shared.open(url)
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

    /// Recents are written under the current scope, and nowhere when
    /// there is none: a signed-out app has nobody to write for.
    private func persistRecents() {
        guard let scope else { return }
        RecentsStore(scope: scope).save(recents)
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

/// Copy to the clipboard.
@MainActor
func copyToPasteboard(_ text: String) {
    UIPasteboard.general.string = text
}
