import Foundation
import UIKit

/// Central app state. Only base URLs and the email are persisted here — never tokens.
@MainActor
final class AppState: ObservableObject {
    enum AuthState: Equatable {
        case restoring
        case signedOut
        /// A session behind the biometric gate; nothing carrying a token is sent until it opens.
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

    enum SettingsTab: Hashable { case general, connectors, dataAI, account }

    /// Open Settings on the Connectors page (menus, the home page's prompt).
    func showConnectors() {
        settingsTab = .connectors
        settingsPresented = true
    }

    /// Open Settings on Data & AI (from a note with no acknowledged processor).
    func showDataAndAI() {
        settingsTab = .dataAI
        settingsPresented = true
    }

    /// The invite sheet (avatar menu › Invite people…).
    @Published var invitePresented = false
    /// "New from template…" (the + menu).
    @Published var newNotePresented = false
    /// The bell's feed.
    @Published var notificationsPresented = false
    /// A note could not be created; the home page shows it.
    @Published var creationError: String?
    /// The bell: unread count and the feed.
    private(set) lazy var notifications = NotificationsModel(api: api)

    /// Only owners and admins may add members.
    var canManageMembers: Bool {
        if let role = activeWorkspace?.myRole { return role == "owner" || role == "admin" }
        guard let tenantId, let membership = memberships.first(where: { $0.tenantId == tenantId }) else {
            return false
        }
        return membership.role == "owner" || membership.role == "admin"
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
    /// All notes, mine, or shared with me (W3); the server filters.
    @Published var noteScope: NoteScope = .all {
        didSet { if noteScope != oldValue { Task { await refreshNotes() } } }
    }
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
        // Before anything can be sent: delete the legacy refresh cookie. The
        // saved password is deliberately left alone during `dual` (`SessionMigration`).
        self.signedOutNotice = SessionMigration.run()
        self.api = APIClient(settings: stored)
        // Recents load only once `restoreSession` knows the identity and workspace.
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
            await api.onTenantMoved { [weak self] tenantId in
                Task { @MainActor in await self?.sessionMoved(to: tenantId) }
            }
            await self?.restoreSession()
        }
        Task { await connectors.recheck() }
    }

    // MARK: - Auth

    /// Who is signed in; also written to the sidecar of a kept recording.
    @Published private(set) var identity: IdentitySummary?
    /// Every workspace this identity can reach.
    @Published private(set) var memberships: [MembershipSummary] = []
    @Published private(set) var tenantId: String?
    /// The identity id behind the current session, for the kept-recording sidecar.
    private(set) var identityId: String = ""
    /// Signed in from the stored session, not yet confirmed by the server (offline boot).
    @Published private(set) var reconnecting = false
    /// Why the app last dropped to the sign-in screen, shown there once.
    @Published var signedOutNotice: String?
    /// The step-up sheet, when an endpoint asks for recent proof.
    @Published var reauth: ReauthPrompt?
    /// Which issuer minted the session (ADR-0047): decides password saving, switcher, gate.
    @Published private(set) var sessionKind: SessionKind?
    /// Whether "Require Face ID to open" is on, for the Settings toggle.
    @Published private(set) var gateOn = false

    /// Whether the biometric gate is offered in Settings. Off during `dual`:
    /// a Keycloak session cannot be gated, so the toggle would do nothing for half the users.
    static let gateOffered = false

    /// Whether the session could carry the gate — native sessions only.
    @Published private(set) var canGate = false
    /// Set while the unlock prompt is up (no second prompt behind the first).
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
            // Ask straight away on a cold start with the gate on.
            await unlock()
        case .offline(let summary):
            // Never wipe a session for a network error.
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

    // ── the biometric gate ───────────────────────────────────────────

    /// Open the gate. Cancelled = locked screen stays; changed biometry = session wiped and said so.
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
            applyScope()
            gateOn = await api.isGateOn()
            sessionKind = await api.sessionKind
            canGate = await api.canGate()
            signedOutNotice = nil
            reconnecting = false
            authState = .signedIn
            await loadWorkspace()
            if !session.joinedTenantIds.isEmpty {
                // Signed up from an invitation: the server accepted it and landed the session there.
                pendingInvitation = nil
                let names = workspaces.filter { session.joinedTenantIds.contains($0.id) }.map(\.title)
                if !names.isEmpty { linkNotice = "You joined \(names.joined(separator: ", "))." }
            } else if let pending = pendingInvitation {
                // The link was opened signed out: accept it now, as the address that just proved itself.
                pendingInvitation = nil
                invitation = pending
                await joinInvitation()
            }
            return session.isNewIdentity ? .welcome : .signedIn
        }
    }

    /// The welcome step's one field; skipping it is fine (server default).
    func setDisplayName(_ name: String) async {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        identity = try? await api.setDisplayName(trimmed)
    }

    /// True for an account younger than a day that has not dismissed the first-run card here.
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

    /// What the workspace admin allows. Permissive until known.
    @Published private(set) var sharingRules: SharingConstraints = .permissive

    private func loadWorkspace() async {
        if let rules = try? await api.sharingConstraints() { sharingRules = rules }
        await refreshWorkspaces(force: true)
        announceMove()
        await refreshMyInvitations(force: true)
        refreshPending()
        // Anything typed offline goes up now; idempotent on the capture id.
        await capture.syncPendingMeetingNotes()
        await refreshNotes()
        await refreshSpaces()
        await googleCalendar.refresh(force: true)
    }

    func signOut() async {
        let signedOut = identityId
        await api.logout()
        clearSignedInState()
        // The account's names and per-job answers go; the recordings stay.
        SignOutCleanup.run(identityId: signedOut)
        capture.forgetContext()
        gateOn = await api.isGateOn()
        signedOutNotice = nil
        authState = .signedOut
    }

    /// The session is gone for good: drop to the sign-in form with the reason.
    private func sessionEnded(_ reason: SessionLostReason) {
        guard authState == .signedIn || authState == .locked else { return }
        clearSignedInState()
        signedOutNotice = reason.message
        authState = .signedOut
    }

    private func clearSignedInState() {
        notifications.forget()
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
        myInvitations = []
        lastInvitationsRefresh = nil
        movedTo = nil
        inviteFirstTeammate = nil
        // Recents stay on disk under their scope; only this session's view is dropped.
        scope = nil
        recents = []
        pending = []
        orphanedMeetingNotes = []
        sessionKind = nil
        canGate = false
    }

    /// Where an account is created: the web app, in Safari (signup stays a web flow).
    func openSignup() {
        // `/join` picks signup or the lead form by the server's config.
        guard let url = URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "join") else { return }
        UIApplication.shared.open(url)
    }

    /// Mail the confirmation link again. Returns the sentence to show either way.
    func resendVerification(to address: String) async -> String {
        do {
            try await api.resendVerification(email: address)
            return "Sent. Check your inbox — and your spam folder."
        } catch {
            return AuthCopy.message(for: error)
        }
    }

    /// Where a forgotten password is reset: the web app, in Safari.
    func openPasswordReset() {
        guard let url = URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "reset") else { return }
        UIApplication.shared.open(url)
    }

    // ── step-up ──────────────────────────────────────────────────────

    /// Ask the person to prove it is them (sheet on the main actor); the
    /// triggering request is retried once on `true`.
    func presentReauth() async -> Bool {
        guard authState == .signedIn else { return false }
        let options = try? await api.startReauth()
        return await withCheckedContinuation { continuation in
            // Resumed exactly once, by the sheet or the deadline; never-resumed would hang the request.
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

    /// A link that opens the app (`notesai://`; universal links are not wired: the web host is runtime-configurable).
    enum AppLink: Equatable {
        case invite(token: String)
        /// `workspace`: the `?ws=` the link carries, the workspace the note lives in.
        case note(id: String, workspace: String? = nil)

        init?(_ url: URL) {
            guard url.scheme?.lowercased() == "notesai" else { return nil }
            // notesai://invite/<token> parses as host "invite", path "/<token>".
            let parts = ([url.host()] + url.pathComponents.filter { $0 != "/" })
                .compactMap { $0 }
            guard parts.count >= 2 else { return nil }
            switch parts[0] {
            case "invite": self = .invite(token: parts[1])
            case "notes":
                let ws = URLComponents(url: url, resolvingAgainstBaseURL: false)?
                    .queryItems?.first { $0.name == "ws" }?.value
                self = .note(id: parts[1], workspace: ws?.isEmpty == false ? ws : nil)
            default: return nil
            }
        }
    }

    /// Something to say about the link just opened, shown once on the home page.
    @Published var linkNotice: String?

    /// Handle a link. OAuth callbacks never reach here: `ASWebAuthenticationSession`
    /// intercepts its own redirect (so a callback is not replayable).
    func handle(_ url: URL) {
        guard let link = AppLink(url) else { return }
        switch link {
        case .note(let id, let workspace):
            guard authState == .signedIn else { return }
            Task { await openLinkedNote(id, workspace: workspace) }
        case .invite(let token):
            Task { await openInvitation(token: token) }
        }
    }

    // MARK: - Invitations (W2)

    /// The invitation link on screen; the landing sheet follows it. The token stays in memory only.
    @Published var invitation: InvitationLanding?
    /// A link opened signed out: the sign-in screen names the address, and it is accepted right after sign-in.
    @Published private(set) var pendingInvitation: InvitationLanding?
    /// Open invitations addressed to this person (the picker's "Invitations (n)").
    @Published private(set) var myInvitations: [MyInvitation] = []
    private var lastInvitationsRefresh: Date?

    /// Show what the link is (anonymous lookup, so it works signed out too).
    func openInvitation(token: String) async {
        settingsPresented = false
        invitePresented = false
        invitation = InvitationLanding(token: token)
        let state: InvitationLandingState
        do {
            state = .ready(try await api.lookupInvitation(token: token))
        } catch let error as APIError where error.status == 404 {
            state = .invalid
        } catch {
            state = .failed(nil, message: AuthCopy.message(for: error))
        }
        if invitation?.token == token { invitation?.state = state }
    }

    /// Join from the landing sheet; signed out, remember it and let the sign-in screen take over.
    func joinInvitation() async {
        guard let landing = invitation, let lookup = landing.state.lookup else { return }
        guard authState == .signedIn else {
            pendingInvitation = InvitationLanding(token: landing.token, state: .ready(lookup))
            invitation = nil
            return
        }
        invitation?.state = .joining(lookup)
        do {
            let accepted = try await api.acceptInvitation(token: landing.token)
            invitation = nil
            await joined(accepted.tenantId, name: lookup.workspaceName)
        } catch let error as APIError where error.code == "invitation_email_mismatch" {
            invitation?.state = .mismatch(lookup, signedInAs: email)
        } catch let error as APIError where error.status == 404 {
            invitation?.state = .invalid
        } catch {
            invitation?.state = .failed(lookup, message: AuthCopy.message(for: error))
        }
    }

    /// Signed in as the wrong address: sign out, keep the invitation for the right one.
    func signOutForInvitation() async {
        guard let landing = invitation, let lookup = landing.state.lookup else { return }
        pendingInvitation = InvitationLanding(token: landing.token, state: .ready(lookup))
        invitation = nil
        await signOut()
    }

    /// The sign-in screen's "not now".
    func forgetPendingInvitation() {
        pendingInvitation = nil
    }

    /// Re-read this person's open invitations, at most every five minutes unless forced.
    func refreshMyInvitations(force: Bool = false) async {
        guard authState == .signedIn else { return }
        if !force, let last = lastInvitationsRefresh,
           Date().timeIntervalSince(last) < Self.workspaceRefreshInterval { return }
        guard let list = try? await api.myInvitations() else { return }
        lastInvitationsRefresh = Date()
        myInvitations = list
    }

    /// Accept from the in-app list. Returns what went wrong, or nil.
    func accept(_ invite: MyInvitation) async -> String? {
        do {
            let accepted = try await api.acceptInvitation(id: invite.id)
            await joined(accepted.tenantId, name: invite.workspaceName)
            return nil
        } catch {
            return AuthCopy.message(for: error)
        }
    }

    func decline(_ invite: MyInvitation) async -> String? {
        do {
            try await api.declineInvitation(id: invite.id)
            myInvitations.removeAll { $0.id == invite.id }
            return nil
        } catch {
            return AuthCopy.message(for: error)
        }
    }

    /// The server put the session into a workspace just joined; follow it. A Keycloak-era
    /// session cannot be moved (no token came back): the membership is there, the switch is not.
    private func joined(_ tenantId: String, name: String) async {
        pendingInvitation = nil
        if await api.tenantId == tenantId {
            await enterWorkspace(tenantId)
        } else {
            await refreshWorkspaces(force: true)
        }
        await refreshMyInvitations(force: true)
        linkNotice = "You joined \(name)."
    }

    /// Accept from a `workspace.invited` notification. Returns what went wrong, or nil.
    func acceptInvitation(id: String) async -> String? {
        if !myInvitations.contains(where: { $0.id == id }) { await refreshMyInvitations(force: true) }
        guard let invite = myInvitations.first(where: { $0.id == id }) else {
            return "This invitation is no longer valid. Ask the person who invited you for a new one."
        }
        return await accept(invite)
    }

    /// Create a team workspace and switch into it. Returns what went wrong, or nil.
    func createWorkspace(named name: String) async -> String? {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let created: Workspace
        do {
            created = try await api.createWorkspace(name: trimmed)
        } catch {
            return AuthCopy.message(for: error)
        }
        await refreshWorkspaces(force: true)
        await switchWorkspace(to: created)
        guard tenantId == created.id else {
            return "\(created.title) was created, but switching to it failed. Pick it from the list."
        }
        inviteFirstTeammate = created.id
        return nil
    }

    /// The workspace just created here, until its "Invite your first teammate" card is used or dismissed.
    @Published var inviteFirstTeammate: String?

    /// Leave a workspace; the server moves the session to Personal. Returns the server's reason when it refuses.
    func leave(_ workspace: Workspace) async -> String? {
        let movedTo: String?
        do {
            movedTo = try await api.leaveWorkspace(tenantId: workspace.id)
        } catch {
            return AuthCopy.message(for: error)
        }
        if let movedTo {
            // It was the open one: the session is in Personal now; back to the home page there.
            settingsPresented = false
            await enterWorkspace(movedTo)
        } else {
            await refreshWorkspaces(force: true)
        }
        linkNotice = "You left \(workspace.title)."
        return nil
    }

    /// Dissolve the open workspace (owner, nobody else in it, name typed back). Returns what went wrong, or nil.
    func dissolve(_ workspace: Workspace, confirmName: String) async -> String? {
        do {
            try await api.dissolveWorkspace(tenantId: workspace.id, confirmName: confirmName)
        } catch {
            return AuthCopy.message(for: error)
        }
        // The server moved this session to Personal and sent its token (adopted by the client).
        if let now = await api.tenantId, now != tenantId {
            settingsPresented = false
            await enterWorkspace(now)
        } else {
            await refreshWorkspaces(force: true)
            if tenantId == workspace.id, let personal = personalWorkspace {
                // An older server without the token: move now rather than wait for a refresh to heal it.
                settingsPresented = false
                await switchWorkspace(to: personal)
            }
        }
        linkNotice = "\(workspace.title) was dissolved."
        return nil
    }

    /// What a note link asks for, given where the session is and which workspaces this identity has.
    enum LinkRoute: Equatable {
        case open
        case switchTo(Workspace)
        case notAMember
    }

    nonisolated static func route(linkWorkspace: String?, active: String?, workspaces: [Workspace]) -> LinkRoute {
        guard let linkWorkspace, linkWorkspace != active else { return .open }
        guard let target = workspaces.first(where: { $0.id == linkWorkspace }) else { return .notAMember }
        return .switchTo(target)
    }

    /// A note link from another workspace: switch there first if this identity is a member, else say so.
    private func openLinkedNote(_ id: String, workspace: String?) async {
        if let workspace, workspace != tenantId, !workspaces.contains(where: { $0.id == workspace }) {
            await refreshWorkspaces(force: true)
        }
        switch Self.route(linkWorkspace: workspace, active: tenantId, workspaces: workspaces) {
        case .open:
            break
        case .notAMember:
            linkNotice = AuthCopy.notAMember
            return
        case .switchTo(let target):
            await switchWorkspace(to: target)
            // A refused or failed switch has said why; never open the note in the wrong workspace.
            guard tenantId == target.id else { return }
        }
        openNote(id)
    }

    // MARK: - Workspaces (IDX-I2)

    /// Every workspace this identity belongs to; empty until the first `GET /tenants` answers.
    @Published private(set) var workspaces: [Workspace] = []
    /// The session's workspace is no longer a membership: local state is read-only, pending recordings need another home.
    @Published private(set) var workspaceLost = false
    /// Set while `POST /auth/token` is in flight.
    @Published private(set) var switchingTo: String?
    private var lastWorkspaceRefresh: Date?
    /// How often the membership list is re-read on foreground activation.
    private static let workspaceRefreshInterval: TimeInterval = 300

    /// What the shell offers in this workspace; a guest reaches only the notes they were given.
    var capabilities: WorkspaceCapabilities { WorkspaceCapabilities(role: activeWorkspace?.myRole) }

    var activeWorkspace: Workspace? {
        guard let tenantId else { return nil }
        return workspaces.first { $0.id == tenantId }
    }

    /// The picker's order: Personal first, then the server's order.
    var pickerWorkspaces: [Workspace] {
        workspaces.filter(\.isPersonal) + workspaces.filter { !$0.isPersonal }
    }

    /// The workspaces this identity can still send a recording to.
    var availableWorkspaces: [Workspace] {
        workspaces.filter { $0.isActive && $0.status == "active" }
    }

    /// Re-read the membership list (`GET /tenants`; `/auth/me` carries no memberships).
    func refreshWorkspaces(force: Bool = false) async {
        guard authState == .signedIn else { return }
        if !force, let last = lastWorkspaceRefresh,
           Date().timeIntervalSince(last) < Self.workspaceRefreshInterval { return }
        do {
            let list = try await api.workspaces()
            lastWorkspaceRefresh = Date()
            workspaces = list
            // A gone membership is the one thing only this call can discover.
            if let tenantId, !list.contains(where: { $0.id == tenantId }) {
                workspaceLost = true
            } else {
                workspaceLost = false
            }
        } catch {
            // Offline or 5xx: keep the last confirmed list; never drop a membership on a failed request.
        }
    }

    /// Native sessions only: a Keycloak session gets `409 legacy_session` (ADR-0047).
    var canSwitchWorkspace: Bool { sessionKind?.canGate ?? false }

    /// Move this session to another workspace; local state is re-read under the new scope.
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
            await enterWorkspace(switched.tenantId)
        } catch {
            notesError = AuthCopy.message(for: error)
        }
    }

    /// A refresh came back in another workspace: the session was moved elsewhere (left, removed,
    /// dissolved on another device). One app is one session, so the app follows and says so once.
    private var movedTo: String?

    func sessionMoved(to newTenantId: String) async {
        movedTo = newTenantId
        // Signing in or restoring adopts the stored workspace itself; only a live session is moved here.
        if authState == .signedIn, tenantId != nil, newTenantId != tenantId {
            await enterWorkspace(newTenantId)
        }
        announceMove()
    }

    /// The one-time "Switched to {name}" once the workspace list knows the name.
    private func announceMove() {
        guard let movedTo, movedTo == tenantId, let workspace = activeWorkspace else { return }
        self.movedTo = nil
        linkNotice = AuthCopy.workspaceMoved(workspace.title)
    }

    /// The session is now in `tenantId` (switched, joined, or moved by a leave): re-read everything under it.
    private func enterWorkspace(_ tenantId: String) async {
        self.tenantId = tenantId
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
        announceMove()
    }

    // MARK: - Local state, per identity and workspace

    /// Which identity's and workspace's data is shown; nil when signed out (nothing local is written).
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
        // The first identity to sign in inherits the old unscoped recents. Once.
        ScopedDefaults.migrateLegacy(into: next)
        recents = RecentsStore(scope: next).load()
    }

    /// Scopes belonging to somebody else or a left workspace; offered for removal, never removed automatically.
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

    /// Recordings kept when their upload failed, this identity's only.
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

    /// Sendable only when its workspace is still one this identity is in.
    func canRetry(_ capture: PendingCapture) -> Bool {
        !PendingCaptures.needsWorkspace(capture, memberships: availableWorkspaces.map(\.id))
    }

    /// Upload a kept recording and turn it into a note; the file is deleted only once the server has a job.
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
                speakersExpected: capture.info.speakersExpected,
                context: capture.info.captureContext,
                captureTiming: capture.info.captureTiming,
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

    /// Meeting notes typed offline whose workspace refused them (`not_a_member`, `tenant_dissolved`); still on disk.
    @Published private(set) var orphanedMeetingNotes: [PendingMeetingNote] = []

    func setOrphanedMeetingNotes(_ notes: [PendingMeetingNote]) {
        orphanedMeetingNotes = notes
    }

    /// The personal workspace, once `GET /tenants` said which one it is.
    var personalWorkspace: Workspace? { workspaces.first { $0.isPersonal } }

    /// Send a refused meeting note to Personal instead, then replay it.
    func moveMeetingNoteToPersonal(_ note: PendingMeetingNote) async {
        guard let personal = personalWorkspace else { return }
        PendingMeetingNotes.retarget(note, to: personal.id)
        await capture.syncPendingMeetingNotes()
    }

    /// Throw away a refused meeting note's typing. Only ever called from a confirmation.
    func deleteMeetingNote(_ note: PendingMeetingNote) {
        PendingMeetingNotes.remove(note.clientCaptureId)
        orphanedMeetingNotes.removeAll { $0.clientCaptureId == note.clientCaptureId }
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
            notes = try await api.searchNotes(query: query.isEmpty ? nil : query,
                                             scope: capabilities.isGuest ? .all : noteScope).hits
            notesError = nil
        } catch {
            notesError = AuthCopy.message(for: error)
            // A 403 may be a removed membership: ask the membership table rather than guess.
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

    /// The note is gone (deleted here or from the note page): forget it.
    func noteDeleted(_ noteId: String) {
        capture.forgetNote(noteId)
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

    /// Reload the spaces; pre-0021 local spaces are moved up once.
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

    /// Move UserDefaults spaces to the server, once; nil when nothing to move.
    private func importLegacySpaces(into current: [Space]) async -> [Space]? {
        guard let legacy = Self.load([LegacySpace].self, key: Keys.legacySpaces), !legacy.isEmpty else {
            UserDefaults.standard.removeObject(forKey: Keys.legacySpaces)
            UserDefaults.standard.removeObject(forKey: Keys.legacySpaceOf)
            return nil
        }
        let legacyOf = Self.load([String: String].self, key: Keys.legacySpaceOf) ?? [:]
        var newIds: [String: String] = [:]
        for old in legacy {
            // Same name already up there: reuse it.
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

    /// UUID of the meeting-notes template in `language`; nil when unreachable or "auto" (server picks).
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

    /// A note typed from scratch; the new note's id, or nil after telling the home page why not.
    func createBlankNote(templateId: String? = nil) async -> String? {
        creationError = nil
        do {
            var id = templateId
            if id == nil {
                if templateCache == nil { templateCache = try await api.fetchTemplates() }
                let language = capture.language == CaptureViewModel.autoLanguage ? "en" : capture.language
                guard let template = TemplateSummary.defaultTemplate(templateCache ?? [], language: language) else {
                    creationError = "Your workspace has no note templates yet."
                    return nil
                }
                id = template.id
            }
            guard let id else { return nil }
            let detail = try await api.fetchTemplate(id: id)
            let created = try await api.createNote(content: detail.blankContent())
            await refreshNotes()
            return created.id
        } catch {
            creationError = AuthCopy.message(for: error)
            return nil
        }
    }

    /// Stop a queued or running transcription; the recording is not deleted.
    func cancelCapture(jobId: String) async {
        do {
            try await api.cancelJob(id: jobId)
            updateRecent(jobId: jobId, status: .cancelled, errorMessage: "")
        } catch {
            creationError = AuthCopy.message(for: error)
        }
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

    func updateRecent(jobId: String, status: JobStatus? = nil, noteId: String? = nil, errorMessage: String? = nil,
                      title: String? = nil) {
        guard let index = recents.firstIndex(where: { $0.jobId == jobId }) else { return }
        if let title, !title.isEmpty { recents[index].title = title }
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

    /// Draft the note for a capture whose transcript finished without one.
    func draftNote(for capture: RecentCapture) async {
        guard capture.status == .complete, capture.noteId == nil,
              !drafting.contains(capture.jobId) else { return }
        drafting.insert(capture.jobId)
        defer { drafting.remove(capture.jobId) }
        do {
            // The job knows what language it heard.
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

    /// Open a note; one from this phone's captures opens as that capture.
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

    /// Settings › Data & AI in the web app (where tier and acknowledgement are changed).
    func openWebSettingsData() {
        if let url = URL(string: settings.webAppURL.trimmingCharacters(in: .whitespaces))?
            .appending(path: "settings/data") {
            UIApplication.shared.open(url)
        }
    }

    /// Passwords, second factors and account deletion are the web app's.
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

    /// Recents are written under the current scope, nowhere when signed out.
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
