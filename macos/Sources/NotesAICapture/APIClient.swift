import Foundation

/// Async URLSession client for the Notes AI backends.
///
/// Since IDX-M1 this Mac holds a **native session**: the refresh token
/// lives in the Keychain (`SessionStore`), travels in the body of
/// `POST /auth/refresh`, and comes back rotated. The app keeps no cookie
/// store at all — `URLSession` is built without one — so nothing this
/// client sends can carry an ambient credential it did not choose to.
///
/// - Every request declares itself: `X-Client-Type: macos` (which is how
///   the server knows to put the refresh token in the body rather than a
///   cookie, and how the origin check knows this is not a browser) and a
///   fresh `X-Request-Id`, which comes back on failures worth quoting.
/// - The access token is kept in memory only, and refreshed once (via
///   `POST /auth/refresh`) whenever a request answers 401 or the token is
///   about to expire.
/// - Refreshes are SINGLE-FLIGHT. The server rotates the token on every
///   call and treats a re-used one as a replay after a 30-second grace
///   — it revokes the session and denylists the account's access tokens
///   — so two concurrent 401s (the capture pipeline polling a job while
///   the popover polls recents) must share one refresh rather than each
///   sending the same token.
/// - The rotated token is written to the Keychain BEFORE it is published
///   in memory. A crash in between then costs nothing: the newest token
///   is on disk. The other order would leave the retired token there, and
///   the next launch would present it — which is the definition of a
///   replay.
/// - The keepalive is armed for SHORT-LIVED sessions only, which during
///   the dual-issuer period (ADR-0047) means Keycloak's. A native session
///   idles for thirty days (`AUTH_REFRESH_TTL_SECONDS`), so a 45-minute
///   meeting uploads on one refresh taken at the moment of the upload and
///   the app makes no requests at all while it is otherwise idle. A
///   Keycloak session idles out after thirty minutes and has to be kept
///   warm — see `armKeepAlive` for why that is read off the lifetime the
///   server states rather than the token's shape.
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
    /// Rotates a short-lived refresh token before the server idles it
    /// out. Nil for native sessions, which do not need it (`armKeepAlive`).
    private var keepAlive: Task<Void, Never>?
    /// Called once when the session is gone for good.
    private var sessionLostHandler: (@Sendable (SessionLostReason) -> Void)?
    /// Presents the step-up sheet and answers whether it succeeded, so a
    /// `403 reauth_required` can be retried once.
    private var reauthHandler: (@Sendable () async -> Bool)?
    /// Access tokens for workspaces other than the active one, with their
    /// expiries. A recording that started in workspace A must finish
    /// uploading to A even after the person has moved to B, and the token
    /// that does it cannot be the active one.
    private var borrowedTokens: [String: (token: String, expiry: Date)] = [:]

    init(settings: BackendSettings,
         store: SessionStore = SessionStore(),
         configuration: URLSessionConfiguration? = nil) {
        self.settings = settings
        self.store = store
        let config = configuration ?? URLSessionConfiguration.ephemeral
        // No cookie jar, in either direction: the refresh token is the
        // app's to hold, and an HttpOnly cookie in a native app is a
        // credential on disk that nothing in the app can see or rotate.
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        config.httpCookieAcceptPolicy = .never
        config.timeoutIntervalForRequest = 120
        self.session = URLSession(configuration: config)
        // One-time cleanup of the cookie the app used to sign in with.
        // Keycloak's cookies are invalid after the cut-over anyway; what
        // matters is that a credential this app no longer uses does not
        // stay on disk.
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
    ///
    /// Answers 202 for an address nobody has registered exactly as it does
    /// for one that exists: the endpoint is an enumeration dead end by
    /// construction, and this app must not undo that by treating the two
    /// differently.
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
    ///
    /// Native mode does not serve this yet (IDX-A4 owns the native
    /// password grant), so a 404 here is a fact about the server, not a
    /// failure of the sign-in: the caller offers the emailed code instead.
    func login(email: String, password: String, otp: String? = nil) async throws -> AuthResult {
        var body: [String: String] = ["email": email, "password": password]
        if let otp, !otp.isEmpty { body["otp"] = otp }
        return try await authenticate(
            path: "/auth/login",
            body: try JSONSerialization.data(withJSONObject: body))
    }

    /// `POST /auth/signup/resend` — mail the confirmation code again.
    ///
    /// The only piece of signup this app owns. Creating the account is a
    /// browser flow (BE-0 serves `<webAppURL>/signup`), but the dead end
    /// it can leave behind — an account that exists and cannot sign in
    /// until the address is confirmed — surfaces *here*, as
    /// `403 email_not_verified` on `/auth/login`. Sending the person back
    /// to the browser to ask for a new code would be a worse answer than
    /// the one button that fixes it.
    ///
    /// Unauthenticated by construction, and answers the same for an
    /// address that is unknown, already confirmed, or waiting: the same
    /// enumeration rule `/auth/email/start` follows.
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
            // The server put the refresh token in a cookie, which means it
            // took this app for a browser — `X-Client-Type` did not reach
            // it, or the deployment still runs the Keycloak login. Either
            // way there is nothing to keep, and claiming to be signed in
            // would end fifteen minutes later with no explanation.
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
        // Expiry is computed from the server's `expires_in` at the moment
        // of receipt, so a Mac whose clock is wrong is still right about
        // how long it has.
        self.tokenExpiry = Date().addingTimeInterval(TimeInterval(expiresIn))
        if !tenantId.isEmpty { self.tenantId = tenantId }
        if !roles.isEmpty { self.roles = roles }
    }

    // MARK: - The session across launches

    /// What the app knows about its session at boot.
    enum Restore: Equatable {
        case signedOut
        case signedIn(StoredSession)
        /// There is a session, but the server could not be reached to
        /// prove it. Stay signed in and say so — wiping a session because
        /// a café's Wi-Fi is down would be the app's own doing.
        case offline(StoredSession)
        /// The refresh token reached its absolute expiry, probably during a
        /// long stretch away from the network. The token is gone, but who
        /// it belonged to is not: recordings kept for that person are still
        /// on this Mac and still theirs (IDX-M2).
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

    /// Rotate the refresh token and mint a new access token. Concurrent
    /// callers join the refresh already in flight instead of racing it —
    /// two requests carrying the same token is exactly what the server's
    /// replay detection is looking for.
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
                // A 401 with no code we know, from a server that answered:
                // the session is over. Anything else — a timeout, a 503, a
                // DNS failure — leaves the session alone and is retried by
                // whatever the person does next.
                if error.status == 401 {
                    await wipe()
                    throw APIError.notAuthenticated
                }
                throw error
            }
        }

        let response = try decode(AuthResultDTO.self, from: data)
        guard let rotated = response.refreshToken, !response.accessToken.isEmpty else {
            // A body with no refresh token means the server answered as if
            // to a browser. Nothing to store; do not pretend otherwise.
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

    /// A refresh token with more life than this in it is one nobody has
    /// to keep warm. Keycloak's realm idles a session out after thirty
    /// minutes (`infra/keycloak/realm-export.json`, `ssoSessionIdleTimeout`);
    /// a native session lasts thirty days. Four hours sits between them
    /// with room for a realm that is reconfigured rather than replaced.
    private static let idlesOutWithin: TimeInterval = 4 * 60 * 60

    /// What `session_native` is specified to mint (ADR-0047, BE-2). Not
    /// on the wire yet; see `needsKeepAlive`.
    private static let nativeRefreshPrefix = "nrt_" 

    /// Keep a short-lived session alive — and only a short-lived one.
    ///
    /// During the dual-issuer period this app holds one of two kinds of
    /// refresh token. Both live in the Keychain, both travel in the body
    /// of `POST /auth/refresh`, and they behave nothing alike when left
    /// alone:
    ///
    /// - a **native** token, minted by auth-service, good for thirty days
    ///   of idleness. Refreshing it on a timer would be the app waking up
    ///   to tell a server something it already knows.
    /// - a **Keycloak** token, handed to native clients by the
    ///   `/auth/login` proxy. The realm idles it out after thirty
    ///   minutes, and that clock belongs to the Keycloak session rather
    ///   than to the cookie the token used to arrive in — moving it into
    ///   the Keychain did not slow it down. Left alone, someone who signs
    ///   in and then does not touch the app for half an hour is signed
    ///   out with a meeting's worth of audio still to upload.
    ///
    /// Which kind this is gets read off the lifetime the server states,
    /// not the token's shape: ADR-0047's `nrt_` routing prefix never
    /// reached the wire (`session_service` mints a bare
    /// `secrets.token_urlsafe`), and the lifetime is the thing actually
    /// being reacted to in any case. A realm reconfigured to idle out in
    /// two hours keeps working; a native session never arms this.
    /// Whether a keepalive is armed right now. "No keepalive task armed"
    /// is an acceptance criterion for a native session, and asserting it
    /// directly beats waiting out a timer to watch nothing happen.
    var keepAliveIsArmed: Bool { keepAlive != nil }

    private func armKeepAlive(refreshToken: String, refreshTTL: Int, accessExpiresIn: Int) {
        keepAlive?.cancel()
        keepAlive = nil
        guard needsKeepAlive(refreshToken: refreshToken, ttl: refreshTTL) else { return }
        scheduleKeepAlive(expiresIn: accessExpiresIn)
    }

    /// Two signals, and the token only has to fail one of them.
    ///
    /// The prefix is ADR-0047's stated discriminator and iOS keys on it
    /// alone — but `session_service` mints a bare `secrets.token_urlsafe`,
    /// so today nothing on the wire carries it and the prefix test passes
    /// everything through. The lifetime is what actually distinguishes the
    /// two issuers right now. Keeping both means this stays right whether
    /// or not BE-2 ever adds the prefix, and costs one comparison.
    private func needsKeepAlive(refreshToken: String, ttl: Int) -> Bool {
        if refreshToken.hasPrefix(Self.nativeRefreshPrefix) { return false }
        return TimeInterval(ttl) <= Self.idlesOutWithin
    }

    /// Refresh a minute before the access token expires (the web app does
    /// the same). Each refresh rotates the refresh token, which is what
    /// restarts the server's idle clock.
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
            // It idled out anyway — a lid shut for an hour, or a revoke.
            // Say so now rather than on the person's next click.
            sessionLost(.expired)
        } catch {
            // Transient (offline, 503). Try again shortly; the 401 path of
            // the next real request refreshes too, so nothing is lost by
            // waiting, and nothing is spent hammering a server that is down.
            scheduleKeepAlive(expiresIn: 90)
        }
    }

    private func wipe() async {
        await store.clear()
        forgetToken()
    }

    /// A request answered 401 and refreshing did not help: sign the app out
    /// instead of surfacing the server's wording in a capture banner.
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

    /// Name a brand-new identity (the welcome step). The server has
    /// already defaulted the display name to the address's local part, so
    /// this is an edit, not a requirement.
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

    /// End every session but this one. Gated on recent proof of identity,
    /// so the step-up sheet appears first (IDX-M1's plumbing, IDX-M2's
    /// first real user).
    @discardableResult
    func revokeOtherSessions() async throws -> Int {
        let data = try await send(base: \.authBaseURL, path: "/auth/sessions/revoke-others",
                                  method: "POST", authorized: true)
        return try decode(RevokedOthersResponse.self, from: data).revoked
    }

    /// `POST /auth/reauth/start` — the server decides which methods it
    /// will accept (an authenticator if the account has one, a mailed
    /// code otherwise) and sends the code if that is the answer.
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

    /// Move the session to `tenantId` and make its token the default.
    ///
    /// The server is the authority on every switch: the membership is
    /// re-read, and `tid` — which every service in the fleet filters rows
    /// by — changes only on this path.
    @discardableResult
    func activateWorkspace(_ tenantId: String) async throws -> WorkspaceToken {
        let minted = try await mintToken(for: tenantId, activate: true)
        // Persist the choice before publishing it, for the same reason a
        // rotated refresh token is persisted first: a crash in between
        // should leave the Mac where the person put it.
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
            // The active workspace's token is the one the session already
            // has; renewing it is a refresh, not a second mint.
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

    /// Add someone to the workspace. The server resolves the address to an
    /// existing account: 404 when nobody signed up with it yet (invite them
    /// by e-mail instead), 403 when the caller is not an owner/admin.
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

    /// Google's consent page for a new connection. After the sign-in Google
    /// sends the browser to `returnTo` (the app's own URL scheme here).
    func startGoogleCalendarConnect(returnTo: String, loginHint: String?) async throws -> URL {
        var body: [String: Any] = ["return_to": returnTo]
        if let loginHint, !loginHint.isEmpty { body["login_hint"] = loginHint }
        let data = try await send(base: \.noteBaseURL, path: "/v1/calendar/google/connect", method: "POST",
                                  jsonBody: try JSONSerialization.data(withJSONObject: body), authorized: true)
        let response = try decode(CalendarConnectResponse.self, from: data)
        guard let url = URL(string: response.authorizeUrl) else { throw APIError.badURL }
        return url
    }

    /// 0020: add a calendar by its private iCal address. No Google client
    /// involved; the server fetches the feed once before answering.
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
        let request = FromTranscriptRequest(asrJobId: asrJobId, templateId: templateId, title: title)
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/from-transcript", method: "POST",
                                  jsonBody: try JSONEncoder().encode(request), authorized: true,
                                  tenant: tenant)
        return try decode(FromTranscriptResponse.self, from: data)
    }

    // MARK: - Notes (note-service): open, edit, export

    /// `purpose` is required when the note is not ours and was not shared
    /// with us; the server says so with `APIError.needsReadPurpose`.
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

    /// The tenant's notes, newest first; `q` runs the server's full-text
    /// search (with synonym expansion).
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

    /// 201 with the new link, or 200 with the one already minted for that
    /// address.
    func createLink(id: String, label: String, recipientEmail: String?, expiresInDays: Int,
                    mail: Bool = false, personalMessage: String = "",
                    source: String = "native") async throws -> LinkView {
        var payload: [String: Any] = ["label": label, "expires_in_days": expiresInDays, "source": source]
        if let recipientEmail, !recipientEmail.isEmpty { payload["recipient_email"] = recipientEmail }
        if mail {
            // Sprint 22: create and mail in one call, in the app's language.
            payload["send"] = true
            if !personalMessage.isEmpty { payload["personal_message"] = personalMessage }
            payload["lang"] = Locale.preferredLanguageCode ?? "en"
        }
        let body = try JSONSerialization.data(withJSONObject: payload)
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/links", method: "POST",
                                  jsonBody: body, authorized: true)
        return try decode(LinkView.self, from: data)
    }

    /// Sprint 22: mail (or re-mail) a recipient link from the product.
    /// 422 `no_recipient_email`, 409 `recipient_opted_out`, 429 on a cap.
    func sendLink(id: String, linkId: String, personalMessage: String) async throws -> LinkView {
        var payload: [String: Any] = ["lang": Locale.preferredLanguageCode ?? "en"]
        if !personalMessage.isEmpty { payload["personal_message"] = personalMessage }
        let body = try JSONSerialization.data(withJSONObject: payload)
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/links/\(linkId)/send", method: "POST",
                                  jsonBody: body, authorized: true)
        return try decode(LinkView.self, from: data)
    }

    /// Sprint 23: the workspace's sharing rules, for any member.
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

    /// Mail the note to people, from the server.
    ///
    /// Replaces the old `mailto:` hand-off, which opened Mail.app with an
    /// unstyled draft the sender still had to send — and, often enough,
    /// with whatever message Mail already had open in front of it.
    /// Members are granted access and pointed at the note; everyone else
    /// gets the public link, minted server-side if the note has none.
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

    /// Plaintext transcript of a COMPLETE job (409 while it is still running).
    func transcript(jobId: String) async throws -> TranscriptResult {
        let data = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(jobId)/result", method: "GET",
                                  authorized: true)
        return try decode(TranscriptResult.self, from: data)
    }

    /// Ask a question about a note. The answer comes from the model the
    /// server routes this environment to, grounded in the note and its
    /// transcript; `history` is the thread so far (the server stores nothing).
    func askNote(id: String, question: String, history: [AskTurn]) async throws -> AskNoteResponse {
        let body = try JSONEncoder().encode(AskNoteRequest(question: question, history: history))
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/ask", method: "POST",
                                  jsonBody: body, authorized: true)
        return try decode(AskNoteResponse.self, from: data)
    }

    /// Name the diarized speakers of a job (the complete label → name map;
    /// a label left out goes back to its "Speaker N" default). Stored on the
    /// job, so the web app and the note built from it show the same names.
    func setSpeakerNames(jobId: String, names: [String: String]) async throws -> [String: String] {
        let body = try JSONEncoder().encode(SpeakerNamesRequest(names: names))
        let data = try await send(base: \.asrBaseURL, path: "/asr/jobs/\(jobId)/speakers", method: "PUT",
                                  jsonBody: body, authorized: true)
        return try decode(SpeakerNamesResponse.self, from: data).speakerNames
    }

    func submitJob(fileURL: URL, contentType: String, language: String, diarize: Bool,
                   tenant: String? = nil) async throws -> TranscriptionJob {
        let audioData = try Data(contentsOf: fileURL)
        let boundary = "NotesAICapture-\(UUID().uuidString)"
        let body = Self.multipartBody(
            boundary: boundary,
            fields: [("language", language), ("diarize", diarize ? "true" : "false")],
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

    func asrLimits() async throws -> AsrLimits {
        let data = try await send(base: \.asrBaseURL, path: "/asr/limits", method: "GET", authorized: true)
        return try decode(AsrLimits.self, from: data)
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
        /// Send this as a workspace other than the active one. Used by a
        /// pending upload finishing in the workspace it was recorded in.
        tenant: String? = nil,
        allowRefresh: Bool = true,
        allowReauth: Bool = true,
        /// False for the one request that is *already* the person signing
        /// out: a 401 there means the session was over, which is not news
        /// worth putting on the sign-in screen as "your session ended".
        signalsSessionLoss: Bool = true
    ) async throws -> Data {
        guard let root = URL(string: settings[keyPath: base].trimmingCharacters(in: .whitespaces)) else {
            throw APIError.badURL
        }
        if authorized, allowRefresh, needsFreshToken {
            // Expired, about to expire, or never minted in this launch (the
            // app came up offline and is now being used).
            do {
                try await refresh()
            } catch APIError.sessionRevoked {
                // Report it here, where the reason is known. Sending the
                // request anyway would earn a 401 whose only honest
                // reading is "expired", and the person would never be told
                // that their session was revoked for security.
                sessionLost(.securityRevoked)
                throw APIError.sessionRevoked
            } catch APIError.notAuthenticated {
                sessionLost(.expired)
                throw APIError.notAuthenticated
            } catch {
                // Transient (offline, 503): send the request anyway. It
                // will 401 and take the retry path below, or succeed if
                // the token still had life in it.
            }
        }

        var url = root.appending(path: path)
        if !query.isEmpty {
            url.append(queryItems: query.map { URLQueryItem(name: $0.0, value: $0.1) })
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue(accept, forHTTPHeaderField: "Accept")
        // Two headers on every request, to every service. `X-Client-Type`
        // is what makes this a native client rather than a browser — the
        // refresh token comes back in the body because of it, and the
        // origin check lets a request through without an `Origin` because
        // of it. `X-Request-Id` is the correlation id the fleet already
        // propagates; it comes back on failures the app cannot explain.
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
                // Minting can refuse (the membership is gone): let that
                // reach the caller, which is the only place that knows
                // what to do about a workspace it can no longer reach.
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
            // An MFA-gated endpoint (adding a workspace member) answers 401
            // to ask for a one-time code, not because the session is gone —
            // refreshing would only earn a second 401 and sign the user out.
            let error = failure()
            if error.isMFARequired { throw error }
        }

        if http.statusCode == 401, authorized, allowRefresh {
            if let tenant, tenant != tenantId {
                // A borrowed token went stale. Drop it; the retry mints a
                // fresh one, and if the membership is gone by then the
                // mint refuses and says why.
                forgetToken(for: tenant)
            } else if accessToken == tokenUsed {
                // Only refresh if nobody rotated the token while this
                // request was out; otherwise the retry below already
                // carries the new one.
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
            // Still unauthorised with a freshly minted token: the server has
            // revoked the user (denylist), so the session is gone too —
            // unless this was a *borrowed* token, in which case one
            // workspace is refusing us and the session is fine. Signing the
            // app out for that would be the tail wagging the dog.
            if signalsSessionLoss, tenant == nil || tenant == tenantId {
                sessionLost(.expired)
            }
            throw APIError.notAuthenticated
        }

        if http.statusCode == 403, authorized, allowReauth, failure().code == "reauth_required" {
            // The session is fine; it just has not proved itself recently
            // enough for whatever this endpoint does. Ask, then try once
            // more — a step-up the person completes should not cost them
            // the action they were taking.
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
            // A role denial, not a session problem. The `roles` claim is
            // re-read from the workspace membership every time a token is
            // minted, so a token taken out before the person was granted
            // what they now hold keeps being refused until it rotates —
            // which, for an account that was just created or just given a
            // role, is the whole of the "you are not allowed to work with
            // notes here" wall. Rotate once and try again; if the denial
            // is genuine the retry earns the same 403 and it reaches the
            // caller with `allowRefresh: false`, so this costs one request.
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

    /// Whether an authorised request should refresh before it is sent.
    ///
    /// "About to expire" is 30 seconds: long enough to cover the request's
    /// own flight, short enough that a token is not thrown away while it
    /// still works. A nil expiry with a session on disk is the offline-boot
    /// case — there is a session, it has simply never been proved here.
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
