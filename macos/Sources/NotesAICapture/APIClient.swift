import Foundation

/// Async URLSession client for the Notes AI backends.
///
/// Native session: the refresh token lives in the Keychain (`SessionStore`),
/// travels in the body of `POST /auth/refresh` and comes back rotated. No
/// cookie store at all, so no request carries an ambient credential.
///
/// - Every request sends `X-Client-Type: macos` (refresh token in the body,
///   origin check skipped) and a fresh `X-Request-Id`.
/// - The access token is memory-only; refreshed once on a 401 or just before expiry.
/// - Refreshes are SINGLE-FLIGHT: the server rotates on every call and treats a
///   re-used token as a replay (revokes the session, denylists access tokens).
/// - The rotated token is written to the Keychain BEFORE it is published in
///   memory, so a crash in between never leaves a retired token on disk.
/// - The keepalive is armed for SHORT-LIVED (Keycloak) sessions only; a native
///   session idles for thirty days. See `armKeepAlive`.
actor APIClient {
    private var settings: BackendSettings
    private var accessToken: String?
    private var tokenExpiry: Date?
    /// The workspace and roles the current access token is scoped to.
    private(set) var tenantId: String?
    private(set) var roles: [String] = []
    private let session: URLSession
    private let store: SessionStore
    /// The refresh currently in flight, if any; joiners await it.
    private var refreshInFlight: Task<Void, Error>?
    /// Rotates a short-lived refresh token before the server idles it out. Nil for native sessions.
    private var keepAlive: Task<Void, Never>?
    /// Called once when the session is gone for good.
    private var sessionLostHandler: (@Sendable (SessionLostReason) -> Void)?
    /// Presents the step-up sheet and answers whether it succeeded, so a `403 reauth_required` can be retried once.
    private var reauthHandler: (@Sendable () async -> Bool)?
    /// Access tokens for other workspaces: a recording started in A must finish uploading to A after a switch to B.
    private var borrowedTokens: [String: (token: String, expiry: Date)] = [:]

    init(settings: BackendSettings,
         store: SessionStore = SessionStore(),
         configuration: URLSessionConfiguration? = nil) {
        self.settings = settings
        self.store = store
        let config = configuration ?? URLSessionConfiguration.ephemeral
        // No cookie jar either way: the refresh token is the app's to hold and rotate.
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        config.httpCookieAcceptPolicy = .never
        config.timeoutIntervalForRequest = 120
        self.session = URLSession(configuration: config)
        // One-time cleanup of the Keycloak cookie the app used to sign in with.
        LegacyCookies.purge()
    }

    func update(settings: BackendSettings) {
        self.settings = settings
    }

    func onSessionLost(_ handler: @escaping @Sendable (SessionLostReason) -> Void) {
        sessionLostHandler = handler
    }

    func onReauthRequired(_ handler: @escaping @Sendable () async -> Bool) {
        reauthHandler = handler
    }

    // MARK: - Signing in

    /// `POST /auth/email/start` — mail a one-time code.
    /// Answers 202 for unknown and known addresses alike (enumeration dead end); treat both the same.
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

    /// `POST /auth/login` — email and password.
    /// A 404 means the server has no native password grant; the caller offers the emailed code instead.
    func login(email: String, password: String, otp: String? = nil) async throws -> AuthResult {
        var body: [String: String] = ["email": email, "password": password]
        if let otp, !otp.isEmpty { body["otp"] = otp }
        return try await authenticate(
            path: "/auth/login",
            body: try JSONSerialization.data(withJSONObject: body))
    }

    /// `POST /auth/signup/resend` — mail the confirmation code again.
    /// Signup itself is a browser flow; this fixes `403 email_not_verified` on `/auth/login`.
    /// Unauthenticated, and answers the same for unknown, confirmed and waiting addresses (enumeration rule).
    func resendSignupVerification(email: String) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["email": email])
        _ = try await send(
            base: \.authBaseURL, path: "/auth/signup/resend", method: "POST",
            jsonBody: body, authorized: false)
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
            // Refresh token came in a cookie: the server took this app for a browser. Nothing to keep.
            throw APIError.noNativeSession
        }
        let ttl = session.refreshExpiresIn ?? 30 * 24 * 60 * 60
        try await store.save(StoredSession(
            refreshToken: refreshToken,
            refreshExpiresAt: Date().addingTimeInterval(TimeInterval(ttl)),
            identityId: session.identity?.id ?? "",
            email: session.identity?.email ?? "",
            lastTenantId: session.tenantId.isEmpty ? nil : session.tenantId))
        publish(accessToken: session.accessToken,
                expiresIn: session.expiresIn,
                tenantId: session.tenantId,
                roles: session.roles)
        armKeepAlive(refreshToken: refreshToken, refreshTTL: ttl,
                     accessExpiresIn: session.expiresIn)
    }

    private func publish(accessToken: String, expiresIn: Int, tenantId: String, roles: [String]) {
        self.accessToken = accessToken
        // Expiry from the server's `expires_in` at receipt, so a wrong Mac clock does not matter.
        self.tokenExpiry = Date().addingTimeInterval(TimeInterval(expiresIn))
        if !tenantId.isEmpty { self.tenantId = tenantId }
        if !roles.isEmpty { self.roles = roles }
    }

    // MARK: - The session across launches

    /// What the app knows about its session at boot.
    enum Restore: Equatable {
        case signedOut
        case signedIn(StoredSession)
        /// A session exists but the server could not be reached. Stay signed in; never wipe a session over a network error.
        case offline(StoredSession)
        /// The refresh token reached its absolute expiry. Recordings kept for that person are still theirs.
        case expired(StoredSession)
    }

    func restoreSession() async -> Restore {
        guard let stored = await store.load() else { return .signedOut }
        if stored.isExpired {
            await store.clear()
            return .expired(stored)
        }
        do {
            try await refresh()
            return .signedIn(stored)
        } catch let error as APIError {
            switch error {
            case .notAuthenticated, .sessionRevoked:
                // `refresh()` has already cleared the Keychain item.
                return .signedOut
            default:
                return .offline(stored)
            }
        } catch {
            return .offline(stored)
        }
    }

    /// The session as stored, without touching the network.
    func storedSession() async -> StoredSession? {
        await store.load()
    }

    func logout() async {
        let token = await store.load()?.refreshToken
        var body: [String: String] = [:]
        if let token { body["refresh_token"] = token }
        _ = try? await send(
            base: \.authBaseURL, path: "/auth/logout", method: "POST",
            jsonBody: try? JSONSerialization.data(withJSONObject: body),
            authorized: true, allowRefresh: false, signalsSessionLoss: false)
        await store.clear()
        forgetToken()
    }

    /// Rotate the refresh token and mint a new access token. Concurrent callers join the refresh in flight (two requests with one token = replay).
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
        guard let stored = await store.load() else {
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
                // 401 from a server that answered: the session is over. Timeouts/503/DNS leave it alone.
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
        publish(accessToken: response.accessToken,
                expiresIn: response.expiresIn,
                tenantId: response.tenantId,
                roles: response.roles)
        armKeepAlive(refreshToken: rotated, refreshTTL: ttl,
                     accessExpiresIn: response.expiresIn)
    }

    private func forgetToken() {
        accessToken = nil
        tokenExpiry = nil
        tenantId = nil
        roles = []
        keepAlive?.cancel()
        keepAlive = nil
    }

    // MARK: - Keeping a short-lived session alive

    /// A refresh token with more life than this needs no keepalive. Keycloak idles
    /// out after thirty minutes (`ssoSessionIdleTimeout`); native lasts thirty days.
    private static let idlesOutWithin: TimeInterval = 4 * 60 * 60

    /// What `session_native` is specified to mint (ADR-0047). Not on the wire yet; see `needsKeepAlive`.
    private static let nativeRefreshPrefix = "nrt_" 

    /// Keep a short-lived session alive — and only a short-lived one. A native
    /// token idles for thirty days; a Keycloak token idles out after thirty
    /// minutes and must be kept warm. The kind is read off the lifetime the
    /// server states, not the token's shape (the `nrt_` prefix never reached the wire).
    /// Whether a keepalive is armed right now (asserted by the native-session tests).
    var keepAliveIsArmed: Bool { keepAlive != nil }

    private func armKeepAlive(refreshToken: String, refreshTTL: Int, accessExpiresIn: Int) {
        keepAlive?.cancel()
        keepAlive = nil
        guard needsKeepAlive(refreshToken: refreshToken, ttl: refreshTTL) else { return }
        scheduleKeepAlive(expiresIn: accessExpiresIn)
    }

    /// Two signals; the token only has to fail one. The `nrt_` prefix (ADR-0047) is
    /// not on the wire today, so the lifetime is what actually distinguishes the issuers.
    private func needsKeepAlive(refreshToken: String, ttl: Int) -> Bool {
        if refreshToken.hasPrefix(Self.nativeRefreshPrefix) { return false }
        return TimeInterval(ttl) <= Self.idlesOutWithin
    }

    /// Refresh a minute before the access token expires; each refresh rotates the refresh token and restarts the server's idle clock.
    private func scheduleKeepAlive(expiresIn: Int) {
        keepAlive?.cancel()
        let delay = max(10, expiresIn - 60)
        keepAlive = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled, let self else { return }
            await self.keepAliveTick()
        }
    }

    private func keepAliveTick() async {
        do {
            // A success re-arms on its way through `performRefresh`.
            try await refresh()
        } catch APIError.sessionRevoked {
            sessionLost(.securityRevoked)
        } catch APIError.notAuthenticated {
            // It idled out anyway (lid shut, or a revoke): say so now.
            sessionLost(.expired)
        } catch {
            // Transient (offline, 503): try again shortly; the next real request's 401 path refreshes too.
            scheduleKeepAlive(expiresIn: 90)
        }
    }

    private func wipe() async {
        await store.clear()
        forgetToken()
    }

    /// A 401 that refreshing did not fix: sign the app out instead of surfacing the server's wording.
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

    /// Name a brand-new identity (the welcome step); the server already defaulted the display name.
    @discardableResult
    func setDisplayName(_ name: String) async throws -> IdentitySummary {
        let body = try JSONSerialization.data(withJSONObject: ["display_name": name])
        let data = try await send(base: \.authBaseURL, path: "/auth/me", method: "PATCH",
                                  jsonBody: body, authorized: true)
        return try decode(IdentitySummary.self, from: data)
    }

    /// `GET /auth/sessions` — every live session of this account.
    func sessions() async throws -> [AuthSessionSummary] {
        let data = try await send(base: \.authBaseURL, path: "/auth/sessions", method: "GET",
                                  authorized: true)
        return try decode([AuthSessionSummary].self, from: data)
    }

    func revokeSession(sid: String) async throws {
        _ = try await send(base: \.authBaseURL, path: "/auth/sessions/\(sid)", method: "DELETE",
                           authorized: true)
    }

    /// End every session but this one. Gated on recent proof of identity, so the step-up sheet appears first.
    @discardableResult
    func revokeOtherSessions() async throws -> Int {
        let data = try await send(base: \.authBaseURL, path: "/auth/sessions/revoke-others",
                                  method: "POST", authorized: true)
        return try decode(RevokedOthersResponse.self, from: data).revoked
    }

    /// `POST /auth/reauth/start` — the server decides which methods it accepts and mails a code if that is the answer.
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

    // MARK: - Workspaces (IDX-M2)

    /// Every workspace this identity can reach, with the caller's role.
    func workspaces() async throws -> [Tenant] {
        let data = try await send(base: \.authBaseURL, path: "/tenants", method: "GET",
                                  authorized: true)
        return try decode(TenantListResponse.self, from: data).items
    }

    /// Move the session to `tenantId` and make its token the default. The server
    /// re-reads the membership; `tid` changes only on this path.
    @discardableResult
    func activateWorkspace(_ tenantId: String) async throws -> WorkspaceToken {
        let minted = try await mintToken(for: tenantId, activate: true)
        // Persist before publishing, like a rotated refresh token: a crash should leave the Mac where the person put it.
        try? await store.setTenant(tenantId)
        borrowedTokens[tenantId] = nil
        publish(accessToken: minted.accessToken,
                expiresIn: minted.expiresIn,
                tenantId: minted.tenantId,
                roles: minted.roles)
        return minted
    }

    /// A token for `tenantId`, minted or reused, without moving the session.
    func token(for tenantId: String) async throws -> String {
        if tenantId == self.tenantId {
            // The active workspace's token is the session's own; renewing it is a refresh, not a mint.
            if needsFreshToken { try await refresh() }
            if let accessToken { return accessToken }
        }
        if let cached = borrowedTokens[tenantId], cached.expiry.timeIntervalSinceNow > 30 {
            return cached.token
        }
        let minted = try await mintToken(for: tenantId, activate: false)
        borrowedTokens[tenantId] = (minted.accessToken,
                                    Date().addingTimeInterval(TimeInterval(minted.expiresIn)))
        return minted.accessToken
    }

    private func mintToken(for tenantId: String, activate: Bool) async throws -> WorkspaceToken {
        let body = try JSONSerialization.data(withJSONObject: [
            "tenant_id": tenantId, "activate": activate,
        ])
        let data = try await send(base: \.authBaseURL, path: "/auth/token", method: "POST",
                                  jsonBody: body, authorized: true)
        return try decode(WorkspaceToken.self, from: data)
    }

    /// Forget a borrowed token (the workspace is gone, or its token 401'd).
    func forgetToken(for tenantId: String) {
        borrowedTokens[tenantId] = nil
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

    /// Add someone to the workspace. 404 when nobody signed up with that address; 403 when the caller is not owner/admin.
    @discardableResult
    func addTenantMember(tenantId: String, email: String, role: String) async throws -> TenantMember {
        let body = try JSONSerialization.data(withJSONObject: ["email": email, "role": role])
        let data = try await send(base: \.authBaseURL, path: "/tenants/\(tenantId)/members", method: "POST",
                                  jsonBody: body, authorized: true)
        return try decode(TenantMember.self, from: data)
    }

    // MARK: - Calendar connections (note-service, 0019)

    func calendarConnections() async throws -> CalendarConnectionsResponse {
        let data = try await send(base: \.noteBaseURL, path: "/v1/calendar/connections", method: "GET",
                                  authorized: true)
        return try decode(CalendarConnectionsResponse.self, from: data)
    }

    /// Google's consent page for a new connection; afterwards Google sends the browser to `returnTo`.
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

    func createNoteFromTranscript(asrJobId: String, templateId: String?, title: String,
                                  tenant: String? = nil) async throws -> FromTranscriptResponse {
        // The app's own "Meeting <date>" placeholder is not a chosen title: sent empty, the server names the note.
        let request = FromTranscriptRequest(asrJobId: asrJobId, templateId: templateId,
                                            title: CaptureViewModel.isPlaceholderTitle(title) ? "" : title)
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/from-transcript", method: "POST",
                                  jsonBody: try JSONEncoder().encode(request), authorized: true,
                                  tenant: tenant)
        return try decode(FromTranscriptResponse.self, from: data)
    }


    // MARK: - The live meeting note (Sprint 34, ADR-0055)

    /// Open the note as Record is pressed. Idempotent on `clientCaptureId`.
    /// Must never block or stop a recording: a lost note is recoverable, a lost meeting is not.
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

    /// The recording was discarded or never happened. The note stays (it holds what was typed).
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

    /// Remember one term; an existing term merges the new mishearing. `noteId` is
    /// the note the correction was made in. 422 `term_not_vocabulary`: a role label, refused.
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

    /// The workspace's terms as a `vocabulary_hint` for the transcriber.
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

    // MARK: - Billing (0068)

    /// The workspace's plan, the catalogue and this month's usage. Admins only (403 otherwise).
    func billing() async throws -> Billing {
        let data = try await send(base: \.noteBaseURL, path: "/v1/billing", method: "GET",
                                  authorized: true)
        return try decode(Billing.self, from: data)
    }

    /// `applied`: the plan already changed. `redirect`: pay at `redirectURL` first; the plan changes when the payment lands.
    func changePlan(_ plan: String, yearly: Bool = false) async throws -> ChangePlanResult {
        let body = ["plan": plan, "interval": yearly ? "yearly" : "monthly"]
        let data = try await send(base: \.noteBaseURL, path: "/v1/billing/plan", method: "POST",
                                  jsonBody: try JSONSerialization.data(withJSONObject: body),
                                  authorized: true)
        return try decode(ChangePlanResult.self, from: data)
    }

    /// Spend a redeem code on this workspace (0069). Works without payments.
    func redeemCode(_ code: String) async throws -> ChangePlanResult {
        let data = try await send(base: \.noteBaseURL, path: "/v1/billing/redeem", method: "POST",
                                  jsonBody: try JSONSerialization.data(withJSONObject: ["code": code]),
                                  authorized: true)
        return try decode(ChangePlanResult.self, from: data)
    }

    // MARK: - Notes (note-service): open, edit, export

    // MARK: - Generation (Sprint 33)

    /// 404 when the note was never written up by the engine.
    func generation(noteId: String) async throws -> GenerationView {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/generation",
                                  method: "GET", authorized: true)
        return try decode(GenerationView.self, from: data)
    }

    /// Write the note from its recording. 409 with a code when off, over budget or already running; 429 after ten runs a day.
    @discardableResult
    func regenerate(noteId: String) async throws -> GenerationStarted {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/generation",
                                  method: "POST", authorized: true)
        return try decode(GenerationStarted.self, from: data)
    }

    // MARK: - The evidence behind a note (Q5), carry-over and the client version (Sprint 36)

    /// Every line the engine wrote, with the words that prove it. `current` = only the run being read.
    func generatedItems(noteId: String, generation: String = "current") async throws -> [GeneratedItem] {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/generated-items",
                                  method: "GET", query: [("generation", generation)], authorized: true)
        return try decode([GeneratedItem].self, from: data)
    }

    /// Accept or reject a name the engine respelled.
    @discardableResult
    func correctName(noteId: String, itemKey: String, expectedVersion: Int, accept: Bool,
                     surface: String, canonical: String, source: String?) async throws -> CorrectNameResponse {
        let request = CorrectNameRequest(
            expectedVersion: expectedVersion,
            action: accept ? "correction_accepted" : "correction_rejected",
            surface: surface, canonical: canonical, source: source,
            reason: accept ? nil : "wrong_name")
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/items/by-key/\(itemKey)",
                                  method: "PATCH", jsonBody: try JSONEncoder().encode(request), authorized: true)
        return try decode(CorrectNameResponse.self, from: data)
    }

    /// What is still open from the previous meeting in this series.
    func carried(noteId: String) async throws -> CarriedView {
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/carried",
                                  method: "GET", authorized: true)
        return try decode(CarriedView.self, from: data)
    }

    /// Tick a carried item off, re-open it, or drop it: open | done_marked | dropped.
    @discardableResult
    func setCarriedState(noteId: String, itemKey: String, state: String) async throws -> CarriedItem {
        struct Body: Encodable { let state: String }
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/carried/\(itemKey)",
                                  method: "POST", jsonBody: try JSONEncoder().encode(Body(state: state)),
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

    // MARK: - History

    func versions(noteId: String, purpose: ReadPurpose? = nil) async throws -> [NoteVersionSummary] {
        var query: [(String, String)] = []
        if let purpose { query.append(("purpose", purpose.rawValue)) }
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/versions",
                                  method: "GET", query: query, authorized: true)
        return try decode([NoteVersionSummary].self, from: data)
    }

    func version(noteId: String, number: Int, purpose: ReadPurpose? = nil) async throws -> NoteVersionDetail {
        var query: [(String, String)] = []
        if let purpose { query.append(("purpose", purpose.rawValue)) }
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(noteId)/versions/\(number)",
                                  method: "GET", query: query, authorized: true)
        return try decode(NoteVersionDetail.self, from: data)
    }

    // MARK: - A note from a template, by hand

    func createNote(content: NoteContent) async throws -> NoteCreatedResponse {
        struct Body: Encodable { let content: NoteContent }
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes", method: "POST",
                                  jsonBody: try JSONEncoder().encode(Body(content: content)), authorized: true)
        return try decode(NoteCreatedResponse.self, from: data)
    }

    // MARK: - Notifications (notification-service)

    func unreadNotifications() async throws -> Int {
        let data = try await send(base: \.notificationBaseURL, path: "/v1/notifications/unread-count",
                                  method: "GET", authorized: true)
        return try decode(UnreadCount.self, from: data).unreadCount
    }

    func notificationFeed(limit: Int = 15) async throws -> NotificationFeed {
        let data = try await send(base: \.notificationBaseURL, path: "/v1/notifications",
                                  method: "GET", query: [("limit", String(limit))], authorized: true)
        return try decode(NotificationFeed.self, from: data)
    }

    @discardableResult
    func markNotificationRead(id: String) async throws -> NotificationReadResult {
        let data = try await send(base: \.notificationBaseURL, path: "/v1/notifications/\(id)/read",
                                  method: "POST", authorized: true)
        return try decode(NotificationReadResult.self, from: data)
    }

    @discardableResult
    func markAllNotificationsRead() async throws -> NotificationReadResult {
        let data = try await send(base: \.notificationBaseURL, path: "/v1/notifications/read-all",
                                  method: "POST", authorized: true)
        return try decode(NotificationReadResult.self, from: data)
    }

    /// `purpose` is required for a note that is not ours and not shared with us (`APIError.needsReadPurpose`).
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

    /// Mail the note to people, from the server. Members are granted access and
    /// pointed at the note; everyone else gets the public link, minted if needed.
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

    /// Accept or reject one unified spelling; a stale `correctionsRev` is refused (409) and the caller reloads.
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

    /// Ask a question about a note, grounded in the note and its transcript; `history` is the thread so far (the server stores nothing).
    func askNote(id: String, question: String, history: [AskTurn]) async throws -> AskNoteResponse {
        let body = try JSONEncoder().encode(AskNoteRequest(question: question, history: history))
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/ask", method: "POST",
                                  jsonBody: body, authorized: true)
        return try decode(AskNoteResponse.self, from: data)
    }

    /// Name the diarized speakers (the complete label → name map; a label left out
    /// reverts to its default). Stored on the job. `sources` is a metric only.
    func setSpeakerNames(jobId: String, names: [String: String],
                         sources: [String: SpeakerNameSource]? = nil) async throws -> [String: String] {
        let body = try JSONEncoder().encode(SpeakerNamesRequest(names: names, sources: sources))
        let data = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(jobId)/speakers", method: "PUT",
                                  jsonBody: body, authorized: true)
        return try decode(SpeakerNamesResponse.self, from: data).speakerNames
    }

    /// "✕" on a name suggestion. 204, idempotent; the pair never comes back for this job.
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

    /// Move turns to another speaker. `segmentIndices` are the turns' `segment_indices`
    /// concatenated; a newer `resultRev` on the server is `SpeakerEditError.staleResultRev`.
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

    /// Undo every live speaker edit of the current result. Idempotent; 204.
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

    func submitJob(fileURL: URL, contentType: String, language: String, diarize: Bool,
                   speakersExpected: Int? = nil,
                   context: CaptureContext? = nil,
                   vocabularyHint: String? = nil,
                   channelLayout: String? = nil,
                   localSpeakerName: String? = nil,
                   captureTiming: CaptureTiming? = nil,
                   tenant: String? = nil) async throws -> TranscriptionJob {
        let audioData = try Data(contentsOf: fileURL)
        func post(_ context: CaptureContext?, channelLayout: String? = channelLayout) async throws -> TranscriptionJob {
            let boundary = "NotesAICapture-\(UUID().uuidString)"
            let body = Self.multipartBody(
                boundary: boundary,
                fields: Self.jobFields(language: language, diarize: diarize,
                                       speakersExpected: speakersExpected, context: context,
                                       vocabularyHint: vocabularyHint,
                                       channelLayout: channelLayout,
                                       localSpeakerName: localSpeakerName,
                                       captureTiming: captureTiming),
                fileField: "audio",
                fileName: fileURL.lastPathComponent,
                contentType: contentType,
                fileData: audioData
            )
            let data = try await send(base: \.asrBaseURL, path: "/asr/jobs", method: "POST",
                                      body: body,
                                      contentType: "multipart/form-data; boundary=\(boundary)",
                                      authorized: true, tenant: tenant)
            return try decode(TranscriptionJob.self, from: data)
        }
        do {
            return try await post(context)
        } catch where Self.refusedNames(error) && !(context?.nameCandidates.isEmpty ?? true) {
            return try await post(context?.withoutNames)
        } catch where Self.refusedLayout(error) && channelLayout != nil {
            // The file is not what the layout said: send it as mono rather than lose the recording.
            return try await post(context, channelLayout: nil)
        }
    }

    /// The server says the file does not have the declared channel layout.
    static func refusedLayout(_ error: Error) -> Bool {
        guard case APIError.http(_, let problem) = error else { return false }
        return problem?.code == "channel_layout_mismatch"
    }

    /// The form fields of `POST /asr/jobs`. `speakers_expected` goes only for an exact
    /// count. `channel_layout` only `mic_system` for a 2-channel file; `local_speaker_name` omitted when empty, never logged.
    static func jobFields(language: String, diarize: Bool,
                          speakersExpected: Int?,
                          context: CaptureContext? = nil,
                          vocabularyHint: String? = nil,
                          channelLayout: String? = nil,
                          localSpeakerName: String? = nil,
                          captureTiming: CaptureTiming? = nil) -> [(String, String)] {
        var fields = [("language", language), ("diarize", diarize ? "true" : "false")]
        if let speakersExpected { fields.append(("speakers_expected", String(speakersExpected))) }
        if let context { fields += context.formFields(diarize: diarize) }
        // The workspace's own names and terms, so the transcriber has the spellings first.
        if let vocabularyHint, !vocabularyHint.isEmpty {
            fields.append(("vocabulary_hint", String(vocabularyHint.prefix(2000))))
        }
        if let channelLayout { fields.append(("channel_layout", channelLayout)) }
        if let name = LocalSpeakerName.normalized(localSpeakerName) { fields.append(("local_speaker_name", name)) }
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

    /// Stop a transcription that has not finished; the job answers `cancelled` from then on.
    func cancelJob(id: String) async throws {
        _ = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(id)", method: "DELETE",
                           authorized: true)
    }

    func jobStatus(id: String, tenant: String? = nil) async throws -> TranscriptionJob {
        let data = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(id)", method: "GET",
                                  authorized: true, tenant: tenant)
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
        /// Send as a workspace other than the active one (a pending upload finishing where it was recorded).
        tenant: String? = nil,
        allowRefresh: Bool = true,
        allowReauth: Bool = true,
        /// False for the sign-out request itself: a 401 there is not news worth a notice.
        signalsSessionLoss: Bool = true
    ) async throws -> Data {
        guard let root = URL(string: settings[keyPath: base].trimmingCharacters(in: .whitespaces)) else {
            throw APIError.badURL
        }
        if authorized, allowRefresh, needsFreshToken {
            // Expired, about to expire, or never minted in this launch (offline boot).
            do {
                try await refresh()
            } catch APIError.sessionRevoked {
                // Report here, where the reason is known: a 401 later would only read as "expired".
                sessionLost(.securityRevoked)
                throw APIError.sessionRevoked
            } catch APIError.notAuthenticated {
                sessionLost(.expired)
                throw APIError.notAuthenticated
            } catch {
                // Transient (offline, 503): send anyway; it will 401 and retry below, or succeed.
            }
        }

        var url = root.appending(path: path)
        if !query.isEmpty {
            url.append(queryItems: query.map { URLQueryItem(name: $0.0, value: $0.1) })
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue(accept, forHTTPHeaderField: "Accept")
        // `X-Client-Type` makes this a native client (refresh token in the body, no
        // `Origin` needed); `X-Request-Id` is the fleet's correlation id.
        request.setValue("macos", forHTTPHeaderField: "X-Client-Type")
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
        var tokenUsed: String?
        if authorized {
            if let tenant, tenant != tenantId {
                // Minting can refuse (membership gone): let the caller decide.
                tokenUsed = try await token(for: tenant)
            } else {
                tokenUsed = accessToken
            }
        }
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
            // An MFA-gated endpoint answers 401 to ask for a code, not because the session is gone.
            let error = failure()
            if error.isMFARequired { throw error }
        }

        if http.statusCode == 401, authorized, allowRefresh {
            if let tenant, tenant != tenantId {
                // A borrowed token went stale: drop it; the retry mints a fresh one.
                forgetToken(for: tenant)
            } else if accessToken == tokenUsed {
                // Only refresh if nobody rotated the token while this request was out.
                do {
                    try await refresh()
                } catch APIError.sessionRevoked {
                    if signalsSessionLoss { sessionLost(.securityRevoked) }
                    throw APIError.sessionRevoked
                } catch APIError.notAuthenticated {
                    if signalsSessionLoss { sessionLost(.expired) }
                    throw APIError.notAuthenticated
                }
            }
            return try await send(base: base, path: path, method: method, query: query,
                                  jsonBody: jsonBody, body: body, contentType: contentType,
                                  accept: accept, authorized: authorized, tenant: tenant,
                                  allowRefresh: false, allowReauth: allowReauth,
                                  signalsSessionLoss: signalsSessionLoss)
        }
        if http.statusCode == 401, authorized {
            // Still unauthorised with a fresh token: the user is revoked — unless this
            // was a borrowed token, where one workspace refusing us is not a lost session.
            if signalsSessionLoss, tenant == nil || tenant == tenantId {
                sessionLost(.expired)
            }
            throw APIError.notAuthenticated
        }

        if http.statusCode == 403, authorized, allowReauth, failure().code == "reauth_required" {
            // Not a lost session, just no recent proof: ask, then try once more.
            guard let reauthHandler, await reauthHandler() else {
                throw APIError.reauthRequired
            }
            return try await send(base: base, path: path, method: method, query: query,
                                  jsonBody: jsonBody, body: body, contentType: contentType,
                                  accept: accept, authorized: authorized, tenant: tenant,
                                  allowRefresh: allowRefresh, allowReauth: false,
                                  signalsSessionLoss: signalsSessionLoss)
        }

        if http.statusCode == 403, authorized, allowRefresh, failure().isRoleDenial {
            // A role denial, not a session problem. `roles` are re-read on every mint,
            // so a token minted before a grant keeps being refused until it rotates:
            // rotate once and retry; a genuine denial earns the same 403 and reaches the caller.
            if let tenant, tenant != tenantId {
                forgetToken(for: tenant)
            } else {
                try? await refresh()
            }
            return try await send(base: base, path: path, method: method, query: query,
                                  jsonBody: jsonBody, body: body, contentType: contentType,
                                  accept: accept, authorized: authorized, tenant: tenant,
                                  allowRefresh: false, allowReauth: allowReauth,
                                  signalsSessionLoss: signalsSessionLoss)
        }

        guard (200..<300).contains(http.statusCode) else {
            throw failure()
        }
        return data
    }

    /// Whether an authorised request should refresh first. "About to expire" is 30 s;
    /// a nil expiry with a session on disk is the offline-boot case.
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
