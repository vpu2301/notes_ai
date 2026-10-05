import Foundation

/// Async URLSession client for the Notes AI backends. Native session: refresh
/// token in the Keychain (optionally behind Face ID), sent in the body of
/// `POST /auth/refresh`, rotated on every call; no cookie store.
///
/// - Every request sends `X-Client-Type: ios` and a fresh `X-Request-Id`.
/// - Access token in memory only; refreshed once on a 401 or near expiry.
/// - Refreshes are SINGLE-FLIGHT: a re-used refresh token is a replay and
///   revokes the session.
/// - The rotated token is written to the Keychain BEFORE it is published in
///   memory, so a crash in between cannot leave a retired token on disk.
/// - The KEEPALIVE is armed for Keycloak sessions only (30-minute idle);
///   native tokens (`nrt_` prefix, ADR-0047) idle for 30 days. Both refresh
///   once before a long upload (`ensureFreshToken`).
actor APIClient {
    private var settings: BackendSettings
    private var accessToken: String?
    private var tokenExpiry: Date?
    /// The workspace and roles the current access token is scoped to.
    private(set) var tenantId: String?
    private(set) var roles: [String] = []
    private let session: URLSession
    private let store: SessionStore
    /// Which issuer minted the session; nil while signed out.
    private(set) var sessionKind: SessionKind?
    /// The refresh currently in flight, if any; joiners await it.
    private var refreshInFlight: Task<Void, Error>?
    /// The background refresh for a Keycloak session; nil otherwise.
    private var keepAlive: Task<Void, Never>?
    /// Called once when the session is gone for good.
    private var sessionLostHandler: (@Sendable (SessionLostReason) -> Void)?
    /// Called when the gate is shut and something needs the token.
    private var lockedHandler: (@Sendable () -> Void)?
    /// Presents the step-up sheet, so a `403 reauth_required` can be retried once.
    private var reauthHandler: (@Sendable () async -> Bool)?

    init(settings: BackendSettings,
         store: SessionStore = SessionStore(),
         configuration: URLSessionConfiguration? = nil) {
        self.settings = settings
        self.store = store
        let config = configuration ?? URLSessionConfiguration.ephemeral
        // No cookie jar: the refresh token is the app's to hold and rotate.
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        config.httpCookieAcceptPolicy = .never
        config.timeoutIntervalForRequest = 120
        self.session = URLSession(configuration: config)
        // One-time cleanup of the cookie the app used to sign in with.
        LegacyCookies.purge()
    }

    func update(settings: BackendSettings) {
        self.settings = settings
    }

    func onSessionLost(_ handler: @escaping @Sendable (SessionLostReason) -> Void) {
        sessionLostHandler = handler
    }

    func onLocked(_ handler: @escaping @Sendable () -> Void) {
        lockedHandler = handler
    }

    func onReauthRequired(_ handler: @escaping @Sendable () async -> Bool) {
        reauthHandler = handler
    }

    // MARK: - Signing in

    /// `POST /auth/email/start` — mail a one-time code. 202 whether or not
    /// the address exists (no enumeration); the app must not tell them apart.
    func startEmailCode(email: String, language: String? = nil) async throws -> EmailChallenge {
        var body: [String: Any] = ["email": email]
        if let language { body["lang"] = language }
        let data = try await send(
            base: \.authBaseURL, path: "/auth/email/start", method: "POST",
            jsonBody: try JSONSerialization.data(withJSONObject: body),
            authorized: false)
        return try decode(EmailChallenge.self, from: data)
    }

    /// `POST /auth/email/verify` — the code, for a session.
    func verifyEmailCode(challengeId: String, code: String) async throws -> AuthResult {
        let body = try JSONSerialization.data(withJSONObject: [
            "challenge_id": challengeId, "code": code,
        ])
        return try await authenticate(path: "/auth/email/verify", body: body)
    }

    /// `POST /auth/login` — email and password. A 404 means the server has
    /// no password grant; the caller offers the emailed code instead.
    func login(email: String, password: String, otp: String? = nil) async throws -> AuthResult {
        var body: [String: String] = ["email": email, "password": password]
        if let otp, !otp.isEmpty { body["otp"] = otp }
        return try await authenticate(
            path: "/auth/login",
            body: try JSONSerialization.data(withJSONObject: body))
    }

    /// `POST /auth/signup/resend` — mail the confirmation link again (after a
    /// `403 email_not_verified`). Unauthorised; answer independent of whether the address is known.
    func resendVerification(email: String) async throws {
        _ = try await send(
            base: \.authBaseURL, path: "/auth/signup/resend", method: "POST",
            jsonBody: try JSONSerialization.data(withJSONObject: ["email": email]),
            authorized: false)
    }

    /// `POST /auth/mfa/verify` — the second factor owed by `mfaRequired`.
    func verifyMFA(challengeId: String, method: String, code: String) async throws -> AuthResult {
        let body = try JSONSerialization.data(withJSONObject: [
            "challenge_id": challengeId, "method": method, "code": code,
        ])
        return try await authenticate(path: "/auth/mfa/verify", body: body)
    }

    private func authenticate(path: String, body: Data) async throws -> AuthResult {
        let data = try await send(base: \.authBaseURL, path: path, method: "POST",
                                  jsonBody: body, authorized: false)
        let result = try decode(AuthResultDTO.self, from: data).result()
        if case .authenticated(let session) = result {
            try await adopt(session)
        }
        return result
    }

    /// Take a freshly minted session: Keychain first, memory second.
    private func adopt(_ session: AuthSession) async throws {
        guard let refreshToken = session.refreshToken else {
            // Refresh token went into a cookie (server took us for a browser): nothing to keep.
            throw APIError.noNativeSession
        }
        let kind = SessionKind(refreshToken: refreshToken)
        // Keycloak sends `refresh_expires_in` (~30 min); the 30-day fallback is for native tokens.
        let ttl = session.refreshExpiresIn ?? 30 * 24 * 60 * 60
        try await store.save(StoredSession(
            refreshToken: refreshToken,
            refreshExpiresAt: Date().addingTimeInterval(TimeInterval(ttl)),
            identityId: session.identity?.id ?? "",
            email: session.identity?.email ?? "",
            lastTenantId: session.tenantId.isEmpty ? nil : session.tenantId))
        sessionKind = kind
        publish(accessToken: session.accessToken,
                expiresIn: session.expiresIn,
                tenantId: session.tenantId,
                roles: session.roles)
    }

    private func publish(accessToken: String, expiresIn: Int, tenantId: String, roles: [String]) {
        self.accessToken = accessToken
        // Expiry from `expires_in` at receipt, so a wrong phone clock does not matter.
        self.tokenExpiry = Date().addingTimeInterval(TimeInterval(expiresIn))
        if !tenantId.isEmpty { self.tenantId = tenantId }
        if !roles.isEmpty { self.roles = roles }
        scheduleKeepAlive(expiresIn: expiresIn)
    }

    // MARK: - The keepalive (Keycloak sessions only)

    /// Refresh a minute before expiry while holding a Keycloak session: each
    /// refresh pushes Keycloak's idle timeout out. Native sessions are left alone.
    private func scheduleKeepAlive(expiresIn: Int) {
        // A minute before expiry, never in the past (a spent token refreshes at once).
        scheduleKeepAlive(in: max(1, TimeInterval(expiresIn) - 60))
    }

    private func scheduleKeepAlive(in delay: TimeInterval) {
        keepAlive?.cancel()
        keepAlive = nil
        guard sessionKind?.needsKeepAlive == true else { return }
        keepAlive = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled, let self else { return }
            await self.keepAliveTick()
        }
    }

    private func keepAliveTick() async {
        guard sessionKind?.needsKeepAlive == true else { return }
        do {
            try await refresh()
            // `publish` inside the refresh has already armed the next tick.
        } catch APIError.sessionRevoked {
            sessionLost(.securityRevoked)
        } catch APIError.notAuthenticated {
            // Idled out while suspended: say so now.
            sessionLost(.expired)
        } catch {
            // Transient: retry in a fixed minute (the token's own cadence is in the past and would spin).
            scheduleKeepAlive(in: 60)
        }
    }

    // MARK: - The session across launches

    /// What the app knows about its session at boot.
    enum Restore: Equatable {
        case signedOut
        case signedIn(SessionSummary)
        /// A session behind the biometric gate; nothing carrying a token is sent until it opens.
        case locked(SessionSummary)
        /// A session the server could not be reached to prove: stay signed in and say so.
        case offline(SessionSummary)
    }

    func restoreSession() async -> Restore {
        guard let summary = await store.summary() else { return .signedOut }
        // Before the first request, so `publish` can arm the keepalive on the restoring refresh.
        sessionKind = summary.kind
        if summary.isExpired {
            await wipe()
            return .signedOut
        }
        if summary.gated, await !store.isUnlocked { return .locked(summary) }
        do {
            try await refresh()
            return .signedIn(summary)
        } catch let error as APIError {
            switch error {
            case .notAuthenticated, .sessionRevoked:
                // `refresh()` has already cleared the Keychain item.
                return .signedOut
            case .sessionLocked:
                return .locked(summary)
            default:
                return .offline(summary)
            }
        } catch SessionStoreError.gateLost {
            return .signedOut
        } catch {
            return .offline(summary)
        }
    }

    /// The session as stored, without touching the network or the gate.
    func storedSummary() async -> SessionSummary? {
        await store.summary()
    }

    // MARK: - The biometric gate

    /// Whether the gate is on for this phone.
    func isGateOn() async -> Bool {
        await store.isGateOn
    }

    /// Whether the session can carry the gate; false for a Keycloak session.
    func canGate() async -> Bool {
        (await store.kind ?? .native).canGate
    }

    func isUnlocked() async -> Bool {
        await store.isUnlocked
    }

    /// Show the biometric prompt. `false` = cancelled; `gateLost` = biometry changed, session wiped.
    func unlock(reason: String = "Unlock Notes AI") async throws -> Bool {
        do {
            try await store.unlock(reason: reason)
            return true
        } catch SessionStoreError.locked {
            return false
        } catch SessionStoreError.gateLost {
            forgetToken()
            throw SessionStoreError.gateLost
        }
    }

    /// Turn the gate on or off; only while unlocked.
    func setGate(enabled: Bool) async throws {
        try await store.setGate(enabled: enabled)
    }

    func logout() async {
        let token = try? await store.load()?.refreshToken
        var body: [String: String] = [:]
        if let token { body["refresh_token"] = token }
        _ = try? await send(
            base: \.authBaseURL, path: "/auth/logout", method: "POST",
            jsonBody: try? JSONSerialization.data(withJSONObject: body),
            authorized: true, allowRefresh: false, signalsSessionLoss: false)
        await wipe()
    }

    /// Rotate the refresh token and mint a new access token. Concurrent callers
    /// join the refresh in flight: two requests with the same token look like a replay.
    private func refresh() async throws {
        if let inFlight = refreshInFlight {
            return try await inFlight.value
        }
        let task = Task<Void, Error> { try await performRefresh() }
        refreshInFlight = task
        defer { refreshInFlight = nil }
        try await task.value
    }

    private func performRefresh() async throws {
        let stored: StoredSession?
        do {
            stored = try await store.load()
        } catch SessionStoreError.locked {
            lockedHandler?()
            throw APIError.sessionLocked
        } catch SessionStoreError.gateLost {
            forgetToken()
            sessionLost(.biometryChanged)
            throw APIError.notAuthenticated
        }
        guard let stored else {
            forgetToken()
            throw APIError.notAuthenticated
        }
        let body = try JSONSerialization.data(withJSONObject: [
            "refresh_token": stored.refreshToken,
        ])
        let data: Data
        do {
            data = try await send(base: \.authBaseURL, path: "/auth/refresh", method: "POST",
                                  jsonBody: body, authorized: false)
        } catch let error as APIError {
            switch error.code {
            case "auth_refresh_replay":
                await wipe()
                throw APIError.sessionRevoked
            case "session_expired", "no_refresh_token", "session_revoked",
                 "account_disabled", "no_workspace":
                await wipe()
                throw APIError.notAuthenticated
            default:
                // A 401 from a server that answered: the session is over.
                // Transient failures leave the session alone.
                if error.status == 401 {
                    await wipe()
                    throw APIError.notAuthenticated
                }
                throw error
            }
        }

        let response = try decode(AuthResultDTO.self, from: data)
        guard let rotated = response.refreshToken, !response.accessToken.isEmpty else {
            // No refresh token in the body: the server answered as if to a browser.
            throw APIError.noNativeSession
        }
        // Persist BEFORE publishing: see the note at the top of the file.
        let ttl = response.refreshExpiresIn ?? 30 * 24 * 60 * 60
        try await store.rotate(refreshToken: rotated,
                               expiresAt: Date().addingTimeInterval(TimeInterval(ttl)),
                               tenantId: response.tenantId.isEmpty ? nil : response.tenantId)
        // After the write, before `publish` arms the keepalive: follow the token actually held.
        sessionKind = SessionKind(refreshToken: rotated)
        publish(accessToken: response.accessToken,
                expiresIn: response.expiresIn,
                tenantId: response.tenantId,
                roles: response.roles)
    }

    /// Refresh now if the access token has less than `minimum` seconds left (before a long upload).
    func ensureFreshToken(minimum: TimeInterval = 300) async throws {
        guard let expiry = tokenExpiry else {
            if accessToken == nil { try await refresh() }
            return
        }
        if expiry.timeIntervalSinceNow < minimum {
            try await refresh()
        }
    }

    private func forgetToken() {
        accessToken = nil
        tokenExpiry = nil
        tenantId = nil
        roles = []
        sessionKind = nil
        keepAlive?.cancel()
        keepAlive = nil
    }

    private func wipe() async {
        await store.clear()
        forgetToken()
    }

    /// 401 that a refresh did not fix: sign out rather than show the server's wording.
    private func sessionLost(_ reason: SessionLostReason) {
        forgetToken()
        sessionLostHandler?(reason)
    }

    // MARK: - Account (IDX-A5 `/auth/me`, step-up)

    func me() async throws -> MeResponse {
        let data = try await send(base: \.authBaseURL, path: "/auth/me", method: "GET",
                                  authorized: true)
        return try decode(MeResponse.self, from: data)
    }

    /// Name a brand-new identity (the welcome step); the server already defaulted it.
    @discardableResult
    func setDisplayName(_ name: String) async throws -> IdentitySummary {
        let body = try JSONSerialization.data(withJSONObject: ["display_name": name])
        let data = try await send(base: \.authBaseURL, path: "/auth/me", method: "PATCH",
                                  jsonBody: body, authorized: true)
        return try decode(IdentitySummary.self, from: data)
    }

    /// `POST /auth/reauth/start` — the server picks the methods and mails a code if needed.
    func startReauth() async throws -> ReauthOptions {
        let data = try await send(base: \.authBaseURL, path: "/auth/reauth/start", method: "POST",
                                  authorized: true, allowRefresh: true)
        return try decode(ReauthOptions.self, from: data)
    }

    func reauth(method: String, code: String, challengeId: String?) async throws {
        var body: [String: Any] = ["method": method, "code": code]
        if let challengeId { body["challenge_id"] = challengeId }
        _ = try await send(base: \.authBaseURL, path: "/auth/reauth", method: "POST",
                           jsonBody: try JSONSerialization.data(withJSONObject: body),
                           authorized: true)
    }

    // MARK: - Workspaces (auth-service /tenants, POST /auth/token)

    /// Every workspace this identity belongs to (`GET /tenants`, re-read from
    /// the database on every call; `/auth/me` carries no memberships).
    func workspaces() async throws -> [Workspace] {
        let data = try await send(base: \.authBaseURL, path: "/tenants", method: "GET",
                                  authorized: true)
        return try decode(WorkspaceList.self, from: data).items
    }

    /// Move this session to another workspace: new access token published, refresh
    /// token untouched, stored `lastTenantId` follows.
    @discardableResult
    func switchWorkspace(to tenantId: String) async throws -> SwitchedToken {
        let switched = try await mintToken(tenantId: tenantId, activate: true)
        try? await store.rotateTenant(tenantId: switched.tenantId)
        publish(accessToken: switched.accessToken,
                expiresIn: switched.expiresIn,
                tenantId: switched.tenantId,
                roles: switched.roles)
        return switched
    }

    /// A token for one request against another workspace, without moving the session.
    func borrowToken(for tenantId: String) async throws -> String {
        try await mintToken(tenantId: tenantId, activate: false).accessToken
    }

    private func mintToken(tenantId: String, activate: Bool) async throws -> SwitchedToken {
        let body = try JSONSerialization.data(withJSONObject: [
            "tenant_id": tenantId, "activate": activate,
        ])
        let data = try await send(base: \.authBaseURL, path: "/auth/token", method: "POST",
                                  jsonBody: body, authorized: true)
        return try decode(SwitchedToken.self, from: data)
    }

    // MARK: - Sessions (auth-service /auth/sessions)

    /// Where this account is signed in; the row with `current` is this phone.
    func sessions() async throws -> [DeviceSession] {
        let data = try await send(base: \.authBaseURL, path: "/auth/sessions", method: "GET",
                                  authorized: true)
        return try decode([DeviceSession].self, from: data)
    }

    func revokeSession(id: String) async throws {
        _ = try await send(base: \.authBaseURL, path: "/auth/sessions/\(id)", method: "DELETE",
                           authorized: true)
    }

    /// End every session but this one. The server asks for recent proof
    /// (`403 reauth_required`); `send` answers with the step-up sheet and one retry.
    @discardableResult
    func revokeOtherSessions() async throws -> Int {
        let data = try await send(base: \.authBaseURL, path: "/auth/sessions/revoke-others",
                                  method: "POST", authorized: true)
        return try decode(RevokedOthers.self, from: data).revoked
    }

    // MARK: - Workspace membership (auth-service /tenants)

    /// The workspace this session is signed into, with the caller's role.
    func currentTenant() async throws -> Tenant {
        let data = try await send(base: \.authBaseURL, path: "/tenants/current", method: "GET",
                                  authorized: true)
        return try decode(Tenant.self, from: data)
    }

    func tenantMembers(tenantId: String) async throws -> [TenantMember] {
        let data = try await send(base: \.authBaseURL, path: "/tenants/\(tenantId)/members", method: "GET",
                                  authorized: true)
        return try decode(TenantMembersResponse.self, from: data).items
    }

    /// Add someone to the workspace: 404 when nobody signed up with the address, 403 when not owner/admin.
    @discardableResult
    func addTenantMember(tenantId: String, email: String, role: String) async throws -> TenantMember {
        let body = try JSONSerialization.data(withJSONObject: ["email": email, "role": role])
        let data = try await send(base: \.authBaseURL, path: "/tenants/\(tenantId)/members", method: "POST",
                                  jsonBody: body, authorized: true)
        return try decode(TenantMember.self, from: data)
    }

    // MARK: - Notifications (notification-service)

    func unreadNotifications() async throws -> UnreadCount {
        let data = try await send(base: \.notificationBaseURL, path: "/v1/notifications/unread-count",
                                  method: "GET", authorized: true)
        return try decode(UnreadCount.self, from: data)
    }

    func notifications(limit: Int = 15) async throws -> NotificationFeed {
        let data = try await send(base: \.notificationBaseURL, path: "/v1/notifications", method: "GET",
                                  query: [("limit", String(limit))], authorized: true)
        return try decode(NotificationFeed.self, from: data)
    }

    func markNotificationRead(id: String) async throws -> UnreadCount {
        let data = try await send(base: \.notificationBaseURL, path: "/v1/notifications/\(id)/read",
                                  method: "POST", authorized: true)
        return try decode(UnreadCount.self, from: data)
    }

    func markAllNotificationsRead() async throws -> UnreadCount {
        let data = try await send(base: \.notificationBaseURL, path: "/v1/notifications/read-all",
                                  method: "POST", authorized: true)
        return try decode(UnreadCount.self, from: data)
    }

    // MARK: - Calendar connections (note-service, 0019)

    func calendarConnections() async throws -> CalendarConnectionsResponse {
        let data = try await send(base: \.noteBaseURL, path: "/v1/calendar/connections", method: "GET",
                                  authorized: true)
        return try decode(CalendarConnectionsResponse.self, from: data)
    }

    /// Google's consent page for a new connection; Google returns to `returnTo` (the app's URL scheme).
    func startGoogleCalendarConnect(returnTo: String, loginHint: String?) async throws -> URL {
        var body: [String: Any] = ["return_to": returnTo]
        if let loginHint, !loginHint.isEmpty { body["login_hint"] = loginHint }
        let data = try await send(base: \.noteBaseURL, path: "/v1/calendar/google/connect", method: "POST",
                                  jsonBody: try JSONSerialization.data(withJSONObject: body), authorized: true)
        let response = try decode(CalendarConnectResponse.self, from: data)
        guard let url = URL(string: response.authorizeUrl) else { throw APIError.badURL }
        return url
    }

    /// Add a calendar by its private iCal address; the server fetches the feed once before answering.
    func connectCalendarLink(url: String, label: String?) async throws -> CalendarConnection {
        var body: [String: Any] = ["url": url]
        if let label, !label.isEmpty { body["label"] = label }
        let data = try await send(base: \.noteBaseURL, path: "/v1/calendar/ics/connect", method: "POST",
                                  jsonBody: try JSONSerialization.data(withJSONObject: body), authorized: true)
        return try decode(CalendarConnection.self, from: data)
    }

    func disconnectCalendar(id: String) async throws {
        _ = try await send(base: \.noteBaseURL, path: "/v1/calendar/connections/\(id)", method: "DELETE",
                           authorized: true)
    }

    func remoteCalendars(connectionId: String) async throws -> RemoteCalendarsResponse {
        let data = try await send(base: \.noteBaseURL, path: "/v1/calendar/connections/\(connectionId)/calendars",
                                  method: "GET", authorized: true)
        return try decode(RemoteCalendarsResponse.self, from: data)
    }

    func setHiddenCalendars(connectionId: String, hidden: [String]) async throws -> CalendarConnection {
        let body = try JSONSerialization.data(withJSONObject: ["hidden_calendar_ids": hidden])
        let data = try await send(base: \.noteBaseURL, path: "/v1/calendar/connections/\(connectionId)/calendars",
                                  method: "PUT", jsonBody: body, authorized: true)
        return try decode(CalendarConnection.self, from: data)
    }

    func upcomingEvents(days: Int = 7) async throws -> UpcomingEventsResponse {
        let data = try await send(base: \.noteBaseURL, path: "/v1/calendar/events", method: "GET",
                                  query: [("days", String(days))], authorized: true)
        return try decode(UpcomingEventsResponse.self, from: data)
    }

    // MARK: - Spaces (note-service, 0021)

    func fetchSpaces() async throws -> [Space] {
        let data = try await send(base: \.noteBaseURL, path: "/v1/spaces", method: "GET", authorized: true)
        return try decode(SpacesResponse.self, from: data).spaces
    }

    func createSpace(name: String) async throws -> Space {
        let body = try JSONSerialization.data(withJSONObject: ["name": name])
        let data = try await send(base: \.noteBaseURL, path: "/v1/spaces", method: "POST",
                                  jsonBody: body, authorized: true)
        return try decode(Space.self, from: data)
    }

    func renameSpace(id: String, name: String) async throws -> Space {
        let body = try JSONSerialization.data(withJSONObject: ["name": name])
        let data = try await send(base: \.noteBaseURL, path: "/v1/spaces/\(id)", method: "PUT",
                                  jsonBody: body, authorized: true)
        return try decode(Space.self, from: data)
    }

    func deleteSpace(id: String) async throws {
        _ = try await send(base: \.noteBaseURL, path: "/v1/spaces/\(id)", method: "DELETE", authorized: true)
    }

    /// File the note in a space; nil takes it out of its space.
    func fileNote(id: String, spaceId: String?) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["space_id": spaceId as Any])
        _ = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/space", method: "PUT",
                           jsonBody: body, authorized: true)
    }

    // MARK: - Templates & notes (note-service)

    func fetchTemplates() async throws -> [TemplateSummary] {
        let data = try await send(base: \.noteBaseURL, path: "/templates", method: "GET",
                                  authorized: true)
        return try decode([TemplateSummary].self, from: data)
    }

    func createNoteFromTranscript(asrJobId: String, templateId: String?, title: String) async throws -> FromTranscriptResponse {
        // The "Meeting <date>" placeholder is sent empty so the server names the note.
        let request = FromTranscriptRequest(asrJobId: asrJobId, templateId: templateId,
                                            title: CaptureViewModel.isPlaceholderTitle(title) ? "" : title)
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/from-transcript", method: "POST",
                                  jsonBody: try JSONEncoder().encode(request), authorized: true)
        return try decode(FromTranscriptResponse.self, from: data)
    }


    /// `POST /v1/notes` — a note typed from scratch, sections pre-filled from the template.
    func createNote(content: NoteContent) async throws -> NoteCreatedResponse {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes", method: "POST",
                                  jsonBody: try JSONEncoder().encode(CreateNoteRequest(content: content)),
                                  authorized: true)
        return try decode(NoteCreatedResponse.self, from: data)
    }

    // MARK: - History

    func versions(noteId: String, purpose: ReadPurpose? = nil) async throws -> [NoteVersionSummary] {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/versions", method: "GET",
                                  query: purpose.map { [("purpose", $0.rawValue)] } ?? [], authorized: true)
        return try decode([NoteVersionSummary].self, from: data)
    }

    func version(noteId: String, number: Int, purpose: ReadPurpose? = nil) async throws -> NoteVersionDetail {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/versions/\(number)",
                                  method: "GET",
                                  query: purpose.map { [("purpose", $0.rawValue)] } ?? [], authorized: true)
        return try decode(NoteVersionDetail.self, from: data)
    }

    // MARK: - Series, carry-over and the client version (Sprint 36)

    /// What is still open from the previous meeting in this series; 404 = no series.
    func carried(noteId: String) async throws -> CarriedView {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/carried", method: "GET",
                                  authorized: true)
        return try decode(CarriedView.self, from: data)
    }

    /// Tick a carried item off (`done_marked`), re-open it, or drop it.
    @discardableResult
    func setCarriedState(noteId: String, itemKey: String, state: String) async throws -> CarriedItem {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/carried/\(itemKey)",
                                  method: "POST",
                                  jsonBody: try JSONEncoder().encode(CarriedStateRequest(state: state)),
                                  authorized: true)
        return try decode(CarriedItem.self, from: data)
    }

    /// Exactly what a client would see. 409 for a 1:1 or an interview.
    func clientVersion(noteId: String) async throws -> ClientVersion {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/client-version",
                                  method: "GET", authorized: true)
        return try decode(ClientVersion.self, from: data)
    }

    func clientVersionCheck(noteId: String) async throws -> ClientVersionCheck {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/client-version/check",
                                  method: "GET", authorized: true)
        return try decode(ClientVersionCheck.self, from: data)
    }

    // MARK: - Evidence (Summary Engine v2, Q5)

    /// Every line the engine wrote, with its evidence, for the run being read.
    func generatedItems(noteId: String) async throws -> [GeneratedItem] {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/generated-items",
                                  method: "GET", query: [("generation", "current")], authorized: true)
        return try decode([GeneratedItem].self, from: data)
    }

    /// Accept or reject a name the engine respelled.
    @discardableResult
    func correctName(noteId: String, itemKey: String, request: NameCorrectionRequest) async throws -> CorrectionResponse {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/items/by-key/\(itemKey)",
                                  method: "PATCH", jsonBody: try JSONEncoder().encode(request),
                                  authorized: true)
        return try decode(CorrectionResponse.self, from: data)
    }

    // MARK: - The live meeting note (Sprint 34, ADR-0055)

    /// Open the note as Record is pressed. Idempotent on `clientCaptureId`.
    /// Must never block or stop a recording.
    func startMeeting(clientCaptureId: String, title: String, startedAt: Date,
                      language: String?, meetingType: MeetingType,
                      calendar: MeetingCalendarContext?) async throws -> StartMeetingResponse {
        let request = StartMeetingRequest(
            clientCaptureId: clientCaptureId,
            title: title.isEmpty ? nil : title,
            startedAt: ISO8601DateFormatter().string(from: startedAt),
            language: language,
            meetingType: meetingType.rawValue,
            calendar: calendar)
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/meeting", method: "POST",
                                  jsonBody: try JSONEncoder().encode(request), authorized: true)
        return try decode(StartMeetingResponse.self, from: data)
    }

    /// When each typed line was first touched. First report per key wins, so re-sending is safe.
    func putLineTimes(noteId: String, lines: [UserLineTime]) async throws {
        guard !lines.isEmpty else { return }
        let body = try JSONEncoder().encode(["lines": lines])
        _ = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/my-notes/timing",
                           method: "PUT", jsonBody: body, authorized: true)
    }

    /// The recording reached asr-service: bind the job to the note.
    @discardableResult
    func attachMeetingJob(noteId: String, asrJobId: String) async throws -> MeetingInfo {
        let body = try JSONSerialization.data(withJSONObject: ["asr_job_id": asrJobId])
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/meeting/job",
                                  method: "POST", jsonBody: body, authorized: true)
        return try decode(MeetingInfo.self, from: data)
    }

    /// The transcription finished: put it in the note. Idempotent, from any device of the author.
    @discardableResult
    func attachTranscript(noteId: String) async throws -> AttachTranscriptResponse {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/transcript",
                                  method: "POST", authorized: true)
        return try decode(AttachTranscriptResponse.self, from: data)
    }

    /// The recording was discarded or never happened; the note (and what was typed) stays.
    @discardableResult
    func markMeetingNoAudio(noteId: String) async throws -> MeetingInfo {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/meeting/no-audio",
                                  method: "POST", authorized: true)
        return try decode(MeetingInfo.self, from: data)
    }

    /// 404 when the note is not a live capture (an upload, or typed by hand).
    func meeting(noteId: String) async throws -> MeetingInfo {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/meeting",
                                  method: "GET", authorized: true)
        return try decode(MeetingInfo.self, from: data)
    }


    // MARK: - The workspace glossary (Sprint 35)

    func glossary() async throws -> [GlossaryTerm] {
        let data = try await send(base: \.noteBaseURL, path: "/v1/glossary", method: "GET",
                                  authorized: true)
        return try decode([GlossaryTerm].self, from: data)
    }

    /// Remember one term; a duplicate merges the new mishearing. `noteId` is
    /// where the correction was made. 422 `term_not_vocabulary`: a role label, refused.
    @discardableResult
    func rememberTerm(_ term: String, kind: GlossaryKind = .person,
                      heardAs: [String] = [], noteId: String? = nil) async throws -> GlossaryTerm {
        let request = RememberTermRequest(term: term, kind: kind.rawValue,
                                          heardAs: heardAs.filter { !$0.isEmpty },
                                          noteId: noteId)
        let data = try await send(base: \.noteBaseURL, path: "/v1/glossary", method: "POST",
                                  jsonBody: try JSONEncoder().encode(request), authorized: true)
        return try decode(GlossaryTerm.self, from: data)
    }

    func forgetTerm(id: String) async throws {
        _ = try await send(base: \.noteBaseURL, path: "/v1/glossary/\(id)", method: "DELETE",
                           authorized: true)
    }

    /// The workspace's terms as a `vocabulary_hint`.
    func glossaryHint() async throws -> GlossaryHint {
        let data = try await send(base: \.noteBaseURL, path: "/v1/glossary/hint", method: "GET",
                                  authorized: true)
        return try decode(GlossaryHint.self, from: data)
    }

    // MARK: - Model tiers and processors (Sprint 37)

    /// Who processes this workspace's meetings. Every member may read it.
    func aiSettings() async throws -> AISettings {
        let data = try await send(base: \.noteBaseURL, path: "/v1/ai/settings", method: "GET",
                                  authorized: true)
        return try decode(AISettings.self, from: data)
    }

    // MARK: - Notes (note-service): open, edit, export

    // MARK: - Generation (Sprint 33)

    /// 404 when the note was never written up by the engine.
    func generation(noteId: String) async throws -> GenerationView {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/generation",
                                  method: "GET", authorized: true)
        return try decode(GenerationView.self, from: data)
    }

    /// *Generate Summary*. 409 with a code (off, over budget, already running); 429 after ten runs a day.
    @discardableResult
    func regenerate(noteId: String) async throws -> GenerationStarted {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/generation",
                                  method: "POST", authorized: true)
        return try decode(GenerationStarted.self, from: data)
    }

    /// `purpose` is required for an oversight read (`APIError.needsReadPurpose`).
    func fetchNote(id: String, purpose: ReadPurpose? = nil) async throws -> NoteEnvelope {
        var query = [("include_content", "true")]
        if let purpose { query.append(("purpose", purpose.rawValue)) }
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)", method: "GET",
                                  query: query, authorized: true)
        return try decode(NoteEnvelope.self, from: data)
    }

    func fetchTemplate(id: String) async throws -> TemplateDetail {
        let data = try await send(base: \.noteBaseURL, path: "/templates/\(id)", method: "GET",
                                  authorized: true)
        return try decode(TemplateDetail.self, from: data)
    }

    func updateDraft(id: String, content: NoteContent, expectedVersion: Int) async throws -> UpdateDraftResponse {
        let request = UpdateDraftRequest(content: content, expectedVersion: expectedVersion)
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/draft", method: "PUT",
                                  jsonBody: try JSONEncoder().encode(request), authorized: true)
        return try decode(UpdateDraftResponse.self, from: data)
    }

    /// The tenant's notes, newest first; `q` runs the server's full-text search.
    func searchNotes(query: String?, limit: Int = 100) async throws -> SearchResponse {
        var params: [(String, String)] = [("limit", String(limit))]
        if let query, !query.isEmpty { params.append(("q", query)) }
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/search", method: "GET",
                                  query: params, authorized: true)
        return try decode(SearchResponse.self, from: data)
    }

    func notePDF(id: String, purpose: ReadPurpose? = nil) async throws -> Data {
        try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/pdf", method: "GET",
                       query: purpose.map { [("purpose", $0.rawValue)] } ?? [],
                       accept: "application/pdf", authorized: true)
    }

    // MARK: - Delete, visibility, sharing (0016)

    func deleteNote(id: String) async throws {
        _ = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)", method: "DELETE", authorized: true)
    }

    func sharing(id: String) async throws -> SharingView {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/sharing", method: "GET",
                                  authorized: true)
        return try decode(SharingView.self, from: data)
    }

    func setVisibility(id: String, visibility: String) async throws -> SharingView {
        let body = try JSONSerialization.data(withJSONObject: ["visibility": visibility])
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/visibility", method: "PUT",
                                  jsonBody: body, authorized: true)
        return try decode(SharingView.self, from: data)
    }

    /// Idempotent: returns the note's live link, minting one if needed.
    func createPublicLink(id: String) async throws -> SharingView {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/public-link", method: "POST",
                                  authorized: true)
        return try decode(SharingView.self, from: data)
    }

    func revokePublicLink(id: String) async throws -> SharingView {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/public-link", method: "DELETE",
                                  authorized: true)
        return try decode(SharingView.self, from: data)
    }



    // MARK: - Action items + recipient responses (Sprint 20)

    func items(noteId: String) async throws -> [ActionItem] {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/items", method: "GET",
                                  authorized: true)
        return try decode([ActionItem].self, from: data)
    }

    func setItemStatus(noteId: String, itemId: String, status: ActionItemStatus) async throws -> ActionItem {
        let body = try JSONSerialization.data(withJSONObject: ["status": status.rawValue])
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/items/\(itemId)", method: "PATCH",
                                  jsonBody: body, authorized: true)
        return try decode(ActionItem.self, from: data)
    }

    func responses(noteId: String) async throws -> [ItemResponse] {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/responses", method: "GET",
                                  authorized: true)
        return try decode([ItemResponse].self, from: data)
    }

    func clearResponse(noteId: String, responseId: String) async throws {
        _ = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/responses/\(responseId)/clear",
                           method: "POST", authorized: true)
    }

    // MARK: - Per-recipient links (Sprint 19)

    /// 201 with the new link, or 200 with the one already minted for that address.
    func createLink(id: String, label: String, recipientEmail: String?, expiresInDays: Int,
                    mail: Bool = false, personalMessage: String = "",
                    source: String = "native") async throws -> LinkView {
        var payload: [String: Any] = ["label": label, "expires_in_days": expiresInDays, "source": source]
        if let recipientEmail, !recipientEmail.isEmpty { payload["recipient_email"] = recipientEmail }
        if mail {
            // Create and mail in one call, in the app's language.
            payload["send"] = true
            if !personalMessage.isEmpty { payload["personal_message"] = personalMessage }
            payload["lang"] = Locale.preferredLanguageCode ?? "en"
        }
        let body = try JSONSerialization.data(withJSONObject: payload)
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/links", method: "POST",
                                  jsonBody: body, authorized: true)
        return try decode(LinkView.self, from: data)
    }

    /// Mail (or re-mail) a recipient link. 422 `no_recipient_email`, 409 `recipient_opted_out`, 429 on a cap.
    func sendLink(id: String, linkId: String, personalMessage: String) async throws -> LinkView {
        var payload: [String: Any] = ["lang": Locale.preferredLanguageCode ?? "en"]
        if !personalMessage.isEmpty { payload["personal_message"] = personalMessage }
        let body = try JSONSerialization.data(withJSONObject: payload)
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/links/\(linkId)/send", method: "POST",
                                  jsonBody: body, authorized: true)
        return try decode(LinkView.self, from: data)
    }

    /// The workspace's sharing rules, for any member.
    func sharingConstraints() async throws -> SharingConstraints {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/sharing/constraints", method: "GET",
                                  authorized: true)
        return try decode(SharingConstraints.self, from: data)
    }

    func listLinks(id: String) async throws -> [LinkView] {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/links", method: "GET",
                                  authorized: true)
        return try decode([LinkView].self, from: data)
    }

    func revokeLink(id: String, linkId: String) async throws {
        _ = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/links/\(linkId)", method: "DELETE",
                           authorized: true)
    }

    /// 404 `not_a_member` when nobody in the workspace has that address.
    func shareWithMember(id: String, email: String) async throws -> SharingView {
        let body = try JSONSerialization.data(withJSONObject: ["email": email])
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/share", method: "POST",
                                  jsonBody: body, authorized: true)
        return try decode(SharingView.self, from: data)
    }

    /// Mail the note from the server: members get access and an app link,
    /// everyone else the public link (minted if needed).
    func shareByEmail(
        id: String, recipients: [String], message: String, lang: String
    ) async throws -> ShareEmailResponse {
        let body = try JSONSerialization.data(withJSONObject: [
            "recipients": recipients,
            "message": message,
            "lang": lang,
        ])
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/share/email",
                                  method: "POST", jsonBody: body, authorized: true)
        return try decode(ShareEmailResponse.self, from: data)
    }

    // MARK: - Transcription jobs (asr-service)

    /// Accept or reject one unified spelling; a stale `correctionsRev` is refused (409).
    func decideCorrection(jobId: String, correctionId: String, status: String,
                          toText: String?, correctionsRev: Int) async throws -> CorrectionsView {
        let body = try JSONEncoder().encode(CorrectionDecisionRequest(status: status, toText: toText,
                                                                      correctionsRev: correctionsRev))
        let data = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(jobId)/corrections/\(correctionId)",
                                  method: "PUT", jsonBody: body, authorized: true)
        return try decode(CorrectionsView.self, from: data)
    }

    func transcript(jobId: String) async throws -> TranscriptResult {
        let data = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(jobId)/result", method: "GET",
                                  authorized: true)
        return try decode(TranscriptResult.self, from: data)
    }

    /// Ask a question about a note; `history` is the thread so far (the server stores nothing).
    func askNote(id: String, question: String, history: [AskTurn]) async throws -> AskNoteResponse {
        let body = try JSONEncoder().encode(AskNoteRequest(question: question, history: history))
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/ask", method: "POST",
                                  jsonBody: body, authorized: true)
        return try decode(AskNoteResponse.self, from: data)
    }

    /// Name the diarized speakers (complete label → name map; a label left
    /// out reverts to its default). `sources` is a metric only.
    func setSpeakerNames(jobId: String, names: [String: String],
                         sources: [String: SpeakerNameSource]? = nil) async throws -> [String: String] {
        let body = try JSONEncoder().encode(SpeakerNamesRequest(names: names, sources: sources))
        let data = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(jobId)/speakers", method: "PUT",
                                  jsonBody: body, authorized: true)
        return try decode(SpeakerNamesResponse.self, from: data).speakerNames
    }

    /// "✕" on a name suggestion. 204, idempotent; the pair never comes back.
    func dismissNameSuggestion(jobId: String, label: String, name: String) async throws {
        let body = try JSONEncoder().encode(NameSuggestionDismissRequest(label: label, name: name))
        do {
            _ = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(jobId)/speakers/suggestions/dismiss",
                               method: "POST", jsonBody: body, authorized: true)
        } catch {
            throw SpeakerEditError.from(error)
        }
    }

    /// Merge one diarized speaker into another (a reversible overlay on the job).
    func mergeSpeakers(jobId: String, from: String, into: String) async throws -> SpeakerEditResult {
        let body = try JSONEncoder().encode(SpeakerMergeRequest(from: from, into: into))
        do {
            let data = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(jobId)/speakers/merge",
                                      method: "POST", jsonBody: body, authorized: true)
            return try decode(SpeakerEditResult.self, from: data)
        } catch {
            throw SpeakerEditError.from(error)
        }
    }

    /// Move turns to another speaker. `segmentIndices` = the turns' `segment_indices`
    /// concatenated; a newer `resultRev` on the server is `staleResultRev`.
    func reassignTurns(jobId: String, resultRev: Int, segmentIndices: [Int],
                       to target: ReassignTarget) async throws -> SpeakerReassignResult {
        let body = try JSONEncoder().encode(SpeakerReassignRequest(resultRev: resultRev,
                                                                   segmentIndices: segmentIndices,
                                                                   to: target))
        do {
            let data = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(jobId)/speakers/reassign",
                                      method: "POST", jsonBody: body, authorized: true)
            return try decode(SpeakerReassignResult.self, from: data)
        } catch {
            throw SpeakerEditError.from(error)
        }
    }

    /// Undo every live speaker edit (merges and moved turns) of the current
    /// result. Idempotent; 204.
    func resetSpeakerEdits(jobId: String) async throws {
        do {
            _ = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(jobId)/speakers/edits/reset",
                               method: "POST", authorized: true)
        } catch {
            throw SpeakerEditError.from(error)
        }
    }

    /// Undo the job's latest speaker edit.
    func undoSpeakerEdit(jobId: String, editId: String) async throws {
        do {
            _ = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(jobId)/speakers/edits/\(editId)",
                               method: "DELETE", authorized: true)
        } catch {
            throw SpeakerEditError.from(error)
        }
    }

    /// Upload a recording. `tenantId` is the workspace it was made for; when
    /// that is not the open one, a token is borrowed rather than moving the session.
    func submitJob(fileURL: URL, contentType: String, language: String, diarize: Bool,
                   speakersExpected: Int? = nil,
                   context: CaptureContext? = nil,
                   vocabularyHint: String? = nil,
                   captureTiming: CaptureTiming? = nil,
                   tenantId: String? = nil) async throws -> TranscriptionJob {
        // The upload can take minutes: start it with a token that will still be valid when it lands.
        try await ensureFreshToken()
        var borrowed: String?
        if let tenantId, !tenantId.isEmpty, tenantId != self.tenantId {
            borrowed = try await borrowToken(for: tenantId)
        }
        let audioData = try Data(contentsOf: fileURL)
        func post(_ context: CaptureContext?) async throws -> TranscriptionJob {
            let boundary = "NotesAICapture-\(UUID().uuidString)"
            let body = Self.multipartBody(
                boundary: boundary,
                fields: Self.jobFields(language: language, diarize: diarize,
                                       speakersExpected: speakersExpected, context: context,
                                       vocabularyHint: vocabularyHint,
                                       captureTiming: captureTiming),
                fileField: "audio",
                fileName: fileURL.lastPathComponent,
                contentType: contentType,
                fileData: audioData
            )
            let data = try await send(base: \.asrBaseURL, path: "/asr/jobs", method: "POST",
                                      body: body,
                                      contentType: "multipart/form-data; boundary=\(boundary)",
                                      authorized: true, bearer: borrowed)
            return try decode(TranscriptionJob.self, from: data)
        }
        do {
            return try await post(context)
        } catch where Self.refusedNames(error) && !(context?.nameCandidates.isEmpty ?? true) {
            return try await post(context?.withoutNames)
        }
    }

    /// The form fields of `POST /asr/jobs`. `speakers_expected` only for an
    /// exact number; the context adds its own fields (`CaptureContext.formFields`).
    static func jobFields(language: String, diarize: Bool,
                          speakersExpected: Int?,
                          context: CaptureContext? = nil,
                          vocabularyHint: String? = nil,
                          captureTiming: CaptureTiming? = nil) -> [(String, String)] {
        var fields = [("language", language), ("diarize", diarize ? "true" : "false")]
        if let speakersExpected { fields.append(("speakers_expected", String(speakersExpected))) }
        if let context { fields += context.formFields(diarize: diarize) }
        // The workspace's own names and terms.
        if let vocabularyHint, !vocabularyHint.isEmpty {
            fields.append(("vocabulary_hint", String(vocabularyHint.prefix(2000))))
        }
        // When Record was pressed and how late the audio began; both or neither.
        if let captureTiming { fields += captureTiming.formFields }
        return fields
    }

    /// The server refused the invitee names; the upload is worth more.
    static func refusedNames(_ error: Error) -> Bool {
        guard case APIError.http(_, let problem) = error else { return false }
        return problem?.code == "name_candidates_invalid"
    }

    /// Re-label the job's speakers. Returns once queued; poll `jobStatus` for `diarization_status`.
    func rediarize(jobId: String, speakersExpected: Int?) async throws -> RediarizeResponse {
        let body = try JSONEncoder().encode(RediarizeRequest(speakersExpected: speakersExpected))
        do {
            let data = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(jobId)/rediarize",
                                      method: "POST", jsonBody: body, authorized: true)
            return try decode(RediarizeResponse.self, from: data)
        } catch {
            throw RediarizeError.from(error)
        }
    }

    /// Put back the labelling the last re-run replaced (one step only).
    func undoRediarize(jobId: String) async throws -> RediarizeResponse {
        do {
            let data = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(jobId)/rediarize/undo",
                                      method: "POST", authorized: true)
            return try decode(RediarizeResponse.self, from: data)
        } catch {
            throw RediarizeError.from(error)
        }
    }

    func asrLimits() async throws -> AsrLimits {
        let data = try await send(base: \.asrBaseURL, path: "/asr/limits", method: "GET", authorized: true)
        return try decode(AsrLimits.self, from: data)
    }

    /// `DELETE /asr/jobs/{id}` — stop a queued or running job; the recording is kept.
    func cancelJob(id: String) async throws {
        _ = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(id)", method: "DELETE", authorized: true)
    }

    func jobStatus(id: String) async throws -> TranscriptionJob {
        let data = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(id)", method: "GET",
                                  authorized: true)
        return try decode(TranscriptionJob.self, from: data)
    }

    // MARK: - Core request machinery

    private func send(
        base: KeyPath<BackendSettings, String>,
        path: String,
        method: String,
        query: [(String, String)] = [],
        jsonBody: Data? = nil,
        body: Data? = nil,
        contentType: String? = nil,
        accept: String = "application/json",
        authorized: Bool,
        /// A token minted for another workspace, used as-is: never refreshed,
        /// and a 401 on it means the membership is gone, not the session.
        bearer: String? = nil,
        allowRefresh: Bool = true,
        allowReauth: Bool = true,
        /// False for the sign-out request itself: a 401 there is not news.
        signalsSessionLoss: Bool = true
    ) async throws -> Data {
        guard let root = URL(string: settings[keyPath: base].trimmingCharacters(in: .whitespaces)) else {
            throw APIError.badURL
        }
        if authorized, bearer == nil, allowRefresh, needsFreshToken {
            // Expired, about to expire, or never minted in this launch (offline boot).
            do {
                try await refresh()
            } catch APIError.sessionRevoked {
                // Report here, where the reason (revoked) is known; a 401 would only say "expired".
                sessionLost(.securityRevoked)
                throw APIError.sessionRevoked
            } catch APIError.notAuthenticated {
                sessionLost(.expired)
                throw APIError.notAuthenticated
            } catch APIError.sessionLocked {
                // The gate is shut: nothing carrying a token leaves until it opens.
                throw APIError.sessionLocked
            } catch {
                // Transient: send anyway; it will 401 into the retry path, or succeed.
            }
        }

        var url = root.appending(path: path)
        if !query.isEmpty {
            url.append(queryItems: query.map { URLQueryItem(name: $0.0, value: $0.1) })
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue(accept, forHTTPHeaderField: "Accept")
        // `X-Client-Type` makes this a native client (refresh token in the body,
        // no `Origin` needed); `X-Request-Id` is the fleet's correlation id.
        request.setValue("ios", forHTTPHeaderField: "X-Client-Type")
        let requestId = UUID().uuidString
        request.setValue(requestId, forHTTPHeaderField: "X-Request-Id")
        if let jsonBody {
            request.httpBody = jsonBody
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        } else if let body {
            request.httpBody = body
            if let contentType {
                request.setValue(contentType, forHTTPHeaderField: "Content-Type")
            }
        }
        let tokenUsed = authorized ? (bearer ?? accessToken) : nil
        if let tokenUsed {
            request.setValue("Bearer \(tokenUsed)", forHTTPHeaderField: "Authorization")
        }

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.http(status: 0, problem: nil)
        }

        func failure() -> APIError {
            var problem = try? JSONDecoder().decode(Problem.self, from: data)
            problem?.requestId = http.value(forHTTPHeaderField: "X-Request-Id") ?? requestId
            problem?.retryAfter = http.value(forHTTPHeaderField: "Retry-After").flatMap { Int($0) }
            return APIError.http(status: http.statusCode, problem: problem)
        }

        if http.statusCode == 401, authorized {
            // An MFA-gated 401 asks for a code; refreshing would only sign the user out.
            let error = failure()
            if error.isMFARequired { throw error }
        }

        if http.statusCode == 401, authorized, bearer != nil {
            // A borrowed token was refused: the membership is gone; report as is.
            throw failure()
        }

        if http.statusCode == 401, authorized, allowRefresh {
            // Only refresh if nobody rotated the token while this request was
            // out; otherwise the retry below already carries the new one.
            if accessToken == tokenUsed {
                do {
                    try await refresh()
                } catch APIError.sessionRevoked {
                    if signalsSessionLoss { sessionLost(.securityRevoked) }
                    throw APIError.sessionRevoked
                } catch APIError.notAuthenticated {
                    if signalsSessionLoss { sessionLost(.expired) }
                    throw APIError.notAuthenticated
                } catch APIError.sessionLocked {
                    throw APIError.sessionLocked
                }
            }
            return try await send(base: base, path: path, method: method, query: query,
                                  jsonBody: jsonBody, body: body, contentType: contentType,
                                  accept: accept, authorized: authorized, bearer: bearer,
                                  allowRefresh: false, allowReauth: allowReauth,
                                  signalsSessionLoss: signalsSessionLoss)
        }
        if http.statusCode == 401, authorized {
            // Still 401 with a fresh token: the user is denylisted, session gone.
            if signalsSessionLoss { sessionLost(.expired) }
            throw APIError.notAuthenticated
        }

        if http.statusCode == 403, authorized, allowReauth, failure().code == "reauth_required" {
            // Step-up wanted: ask, then try once more.
            guard let reauthHandler, await reauthHandler() else {
                throw APIError.reauthRequired
            }
            return try await send(base: base, path: path, method: method, query: query,
                                  jsonBody: jsonBody, body: body, contentType: contentType,
                                  accept: accept, authorized: authorized, bearer: bearer,
                                  allowRefresh: allowRefresh, allowReauth: false,
                                  signalsSessionLoss: signalsSessionLoss)
        }

        if http.statusCode == 403, authorized, allowRefresh, bearer == nil,
           failure().isRoleDenial {
            // Role denial: `roles` is re-read from the membership on every mint, so
            // rotate once and retry (a genuine denial costs one request). A
            // borrowed `bearer` is excluded: rotating the session would not change it.
            try? await refresh()
            return try await send(base: base, path: path, method: method, query: query,
                                  jsonBody: jsonBody, body: body, contentType: contentType,
                                  accept: accept, authorized: authorized, bearer: bearer,
                                  allowRefresh: false, allowReauth: allowReauth,
                                  signalsSessionLoss: signalsSessionLoss)
        }

        guard (200..<300).contains(http.statusCode) else {
            throw failure()
        }
        return data
    }

    /// Whether an authorised request should refresh first: expiry within 30 s,
    /// or a nil expiry with a session on disk (offline boot).
    private var needsFreshToken: Bool {
        guard let expiry = tokenExpiry else { return accessToken == nil }
        return expiry.timeIntervalSinceNow < 30
    }

    /// Server timestamps are ISO 8601, with or without fractional seconds.
    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let raw = try decoder.singleValueContainer().decode(String.self)
            let fractional = ISO8601DateFormatter()
            fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let plain = ISO8601DateFormatter()
            plain.formatOptions = [.withInternetDateTime]
            if let date = fractional.date(from: raw) ?? plain.date(from: raw) { return date }
            throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath,
                                                    debugDescription: "Unrecognised date: \(raw)"))
        }
        return decoder
    }()

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try Self.decoder.decode(type, from: data)
        } catch {
            throw APIError.http(status: 0, problem: Problem(
                title: "Unexpected response",
                detail: "Could not read the server's response.",
                status: nil, code: nil))
        }
    }

    // MARK: - Multipart

    static func multipartBody(
        boundary: String,
        fields: [(String, String)],
        fileField: String,
        fileName: String,
        contentType: String,
        fileData: Data
    ) -> Data {
        var body = Data()
        func append(_ string: String) { body.append(Data(string.utf8)) }

        for (name, value) in fields {
            append("--\(boundary)\r\n")
            append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n")
            append("\(value)\r\n")
        }
        append("--\(boundary)\r\n")
        append("Content-Disposition: form-data; name=\"\(fileField)\"; filename=\"\(fileName)\"\r\n")
        append("Content-Type: \(contentType)\r\n\r\n")
        body.append(fileData)
        append("\r\n--\(boundary)--\r\n")
        return body
    }
}
