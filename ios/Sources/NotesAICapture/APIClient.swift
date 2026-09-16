import Foundation

/// Async URLSession client for the Notes AI backends.
///
/// Since IDX-I1 this phone holds a **native session**: the refresh token
/// lives in the Keychain (`SessionStore`), optionally behind Face ID,
/// travels in the body of `POST /auth/refresh`, and comes back rotated.
/// The app keeps no cookie store at all — `URLSession` is built without
/// one — so nothing this client sends can carry an ambient credential it
/// did not choose to.
///
/// - Every request declares itself: `X-Client-Type: ios` (which is how the
///   server knows to put the refresh token in the body rather than a
///   cookie, and how the origin check knows this is not a browser) and a
///   fresh `X-Request-Id`, which comes back on failures worth quoting.
/// - The access token is kept in memory only, and refreshed once (via
///   `POST /auth/refresh`) whenever a request answers 401 or the token is
///   about to expire.
/// - Refreshes are SINGLE-FLIGHT. The server rotates the token on every
///   call and treats a re-used one as a replay after a 30-second grace
///   — it revokes the session and denylists the account's access tokens
///   — so two concurrent 401s (the capture pipeline polling a job while
///   the home page polls notes) must share one refresh rather than each
///   sending the same token.
/// - The rotated token is written to the Keychain BEFORE it is published
///   in memory. A crash in between then costs nothing: the newest token
///   is on disk. The other order would leave the retired token there, and
///   the next launch would present it — which is the definition of a
///   replay.
/// - The KEEPALIVE is armed for Keycloak sessions and only those. During
///   the dual-issuer period (ADR-0047) this phone may hold either kind of
///   refresh token, told apart by the `nrt_` prefix. A Keycloak token
///   dies after the realm's thirty idle minutes, so without a background
///   refresh a long meeting ends with a recording and no session to
///   upload it with — which is exactly the failure this app had before
///   IDX-I1, and it did not stop being real because a second issuer
///   arrived. A native token idles for thirty days
///   (`AUTH_REFRESH_TTL_SECONDS`); arming a timer for it would wake the
///   phone every quarter of an hour to prove something that was never in
///   doubt. Either way a 45-minute meeting also refreshes once just
///   before the upload (`ensureFreshToken`), which is the belt to the
///   keepalive's braces and the only protection a native session needs.
actor APIClient {
    private var settings: BackendSettings
    private var accessToken: String?
    private var tokenExpiry: Date?
    /// The workspace and roles the current access token is scoped to.
    private(set) var tenantId: String?
    private(set) var roles: [String] = []
    private let session: URLSession
    private let store: SessionStore
    /// Which issuer minted the session this phone is holding, once it is
    /// known. Nil while signed out.
    private(set) var sessionKind: SessionKind?
    /// The refresh currently in flight, if any; joiners await it.
    private var refreshInFlight: Task<Void, Error>?
    /// The background refresh that keeps a Keycloak session from idling
    /// out. Nil for a native session, and for no session at all.
    private var keepAlive: Task<Void, Never>?
    /// Called once when the session is gone for good.
    private var sessionLostHandler: (@Sendable (SessionLostReason) -> Void)?
    /// Called when the gate is shut and something needs the token.
    private var lockedHandler: (@Sendable () -> Void)?
    /// Presents the step-up sheet and answers whether it succeeded, so a
    /// `403 reauth_required` can be retried once (IDX-I2 uses it).
    private var reauthHandler: (@Sendable () async -> Bool)?

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

    /// `POST /auth/signup/resend` — mail the confirmation link again.
    ///
    /// For accounts made through the web signup (BE-0), which land
    /// unconfirmed: `/auth/login` refuses them with `403
    /// email_not_verified` until the link in the mail is followed. The
    /// only thing this app can usefully do about that is send it again.
    ///
    /// Unauthorised by definition — the caller cannot sign in, which is
    /// the whole problem — and, like `/auth/email/start`, its answer must
    /// not depend on whether the address is known.
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
            // The server put the refresh token in a cookie, which means it
            // took this app for a browser — `X-Client-Type` did not reach
            // it, or the deployment still runs the Keycloak login. Either
            // way there is nothing to keep, and claiming to be signed in
            // would end fifteen minutes later with no explanation.
            throw APIError.noNativeSession
        }
        let kind = SessionKind(refreshToken: refreshToken)
        // Keycloak's refresh token is worth ~30 idle minutes, not 30 days,
        // and `refresh_expires_in` says so — so the fallback below is only
        // ever reached for a native token, where 30 days is the right one.
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
        // Expiry is computed from the server's `expires_in` at the moment
        // of receipt, so a phone whose clock is wrong is still right about
        // how long it has.
        self.tokenExpiry = Date().addingTimeInterval(TimeInterval(expiresIn))
        if !tenantId.isEmpty { self.tenantId = tenantId }
        if !roles.isEmpty { self.roles = roles }
        scheduleKeepAlive(expiresIn: expiresIn)
    }

    // MARK: - The keepalive (Keycloak sessions only)

    /// Refresh a minute before the access token expires, for as long as
    /// the app holds a Keycloak session.
    ///
    /// The point is the refresh token, not the access token: Keycloak's
    /// idle timeout is what runs out during a long recording, and each
    /// refresh rotates the token and pushes that timeout out again. A
    /// native session is left alone — see the note at the top of the file.
    private func scheduleKeepAlive(expiresIn: Int) {
        // A minute before the access token expires, and never in the past:
        // a phone that wakes to an already-spent token refreshes at once
        // rather than an hour on.
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
            // The Keycloak session idled out past its timeout while the
            // app was suspended. Say so rather than letting the next thing
            // the person taps fail with no explanation.
            sessionLost(.expired)
        } catch {
            // Transient — offline, a 503, a captive portal. A fixed minute
            // rather than the token's own cadence, which by now is in the
            // past and would spin. The next real request refreshes too, so
            // nothing is lost meanwhile.
            scheduleKeepAlive(in: 60)
        }
    }

    // MARK: - The session across launches

    /// What the app knows about its session at boot.
    enum Restore: Equatable {
        case signedOut
        case signedIn(SessionSummary)
        /// There is a session, and it is behind the biometric gate. No
        /// request carrying a token has been sent, and none will be until
        /// the gate is opened.
        case locked(SessionSummary)
        /// There is a session, but the server could not be reached to
        /// prove it. Stay signed in and say so — wiping a session because
        /// a café's Wi-Fi is down would be the app's own doing.
        case offline(SessionSummary)
    }

    func restoreSession() async -> Restore {
        guard let summary = await store.summary() else { return .signedOut }
        // Before the first request, so `publish` can arm the keepalive for
        // a Keycloak session on the very refresh that restores it.
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

    /// Whether this phone's session can carry the gate at all. False for a
    /// Keycloak session, which has no native refresh token to seal.
    func canGate() async -> Bool {
        (await store.kind ?? .native).canGate
    }

    func isUnlocked() async -> Bool {
        await store.isUnlocked
    }

    /// Show the biometric prompt. `false` means the person cancelled;
    /// `SessionStoreError.gateLost` means the enrolled biometry changed
    /// and the session has been wiped.
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

    /// Turn the gate on or off. Only possible while unlocked, which is
    /// exactly when the Settings screen offering it can be reached.
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
        // After the write, and before `publish` arms the keepalive off it:
        // a rotation should never change the issuer, but the phone follows
        // the token it is actually holding rather than the one it expected.
        sessionKind = SessionKind(refreshToken: rotated)
        publish(accessToken: response.accessToken,
                expiresIn: response.expiresIn,
                tenantId: response.tenantId,
                roles: response.roles)
    }

    /// Refresh now if the access token has less than `minimum` seconds of
    /// life left. Called before a long upload: a token that expires while
    /// a 45-minute recording is on the wire costs the whole upload, and on
    /// a phone the retry may be minutes later on a worse connection.
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

    // MARK: - Workspaces (auth-service /tenants, POST /auth/token)

    /// Every workspace this identity belongs to.
    ///
    /// `GET /tenants`, not `GET /auth/me`: `routers/me.py` still answers
    /// the pre-IDX `{claims, db_user}` shape and carries no memberships
    /// (IDX-B2 debt, recorded in IDX-M1 and unchanged since). The tenant
    /// list is the membership list, re-read from the database on every
    /// call, which is what the switcher needs it to be.
    func workspaces() async throws -> [Workspace] {
        let data = try await send(base: \.authBaseURL, path: "/tenants", method: "GET",
                                  authorized: true)
        return try decode(WorkspaceList.self, from: data).items
    }

    /// Move this session to another workspace.
    ///
    /// The new access token is published here, so every request after it
    /// is scoped to the new `tid`. Nothing rotates: the refresh token is
    /// untouched. The stored session's `lastTenantId` follows, so the next
    /// launch comes back to the same place.
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

    /// A token for one request against another workspace, without moving
    /// the session. This is how a recording made for workspace A is
    /// uploaded while workspace B is open.
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

    /// Where this account is signed in. The row with `current` is this
    /// phone.
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
    /// (`403 reauth_required`), which `send` answers with the step-up
    /// sheet and one retry — this is the first endpoint in the app to use
    /// the plumbing IDX-I1 laid down.
    @discardableResult
    func revokeOtherSessions() async throws -> Int {
        let data = try await send(base: \.authBaseURL, path: "/auth/sessions/revoke-others",
                                  method: "POST", authorized: true)
        return try decode(RevokedOthers.self, from: data).revoked
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

    func createNoteFromTranscript(asrJobId: String, templateId: String?, title: String) async throws -> FromTranscriptResponse {
        let request = FromTranscriptRequest(asrJobId: asrJobId, templateId: templateId, title: title)
        let data = try await send(base: \.noteBaseURL, path: "/v1/notes/from-transcript", method: "POST",
                                  jsonBody: try JSONEncoder().encode(request), authorized: true)
        return try decode(FromTranscriptResponse.self, from: data)
    }

    // MARK: - Notes (note-service): open, edit, finalize, export

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

    func finalizeNote(id: String, expectedVersion: Int) async throws {
        let body = try JSONSerialization.data(withJSONObject: ["expected_version": expectedVersion])
        _ = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/finalize", method: "POST",
                           jsonBody: body, authorized: true)
    }

    func revertToDraft(id: String) async throws {
        _ = try await send(base: \.noteBaseURL, path: "/v1/notes/\(id)/revert-to-draft", method: "POST",
                           authorized: true)
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

    /// Upload a recording.
    ///
    /// `tenantId` is the workspace the recording was **made for**, which
    /// since IDX-I2 need not be the one that is open: a meeting recorded
    /// for the agency and retried a day later, after the person switched
    /// to a client workspace, still belongs to the agency. When it differs
    /// the upload borrows a token for that workspace rather than moving
    /// the session under the person's feet.
    func submitJob(fileURL: URL, contentType: String, language: String, diarize: Bool,
                   tenantId: String? = nil) async throws -> TranscriptionJob {
        // The upload is the one request in this app that can be tens of
        // megabytes over a phone connection. Start it with a token that
        // will still be valid when it lands (IDX-I1 F).
        try await ensureFreshToken()
        var borrowed: String?
        if let tenantId, !tenantId.isEmpty, tenantId != self.tenantId {
            borrowed = try await borrowToken(for: tenantId)
        }
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
                                  authorized: true, bearer: borrowed)
        return try decode(TranscriptionJob.self, from: data)
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
        /// A token minted for another workspace (`POST /auth/token`).
        /// It is used as-is: it is not this session's access token, so
        /// refreshing would replace it with one scoped to the wrong
        /// tenant, and a 401 on it means the membership is gone rather
        /// than that the session is.
        bearer: String? = nil,
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
        if authorized, bearer == nil, allowRefresh, needsFreshToken {
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
            } catch APIError.sessionLocked {
                // The gate is shut. Nothing carrying a token leaves this
                // phone until it is opened — that is what the gate is.
                throw APIError.sessionLocked
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
            // An MFA-gated endpoint answers 401 to ask for a one-time code,
            // not because the session is gone — refreshing would only earn
            // a second 401 and sign the user out.
            let error = failure()
            if error.isMFARequired { throw error }
        }

        if http.statusCode == 401, authorized, bearer != nil {
            // A borrowed token was refused: the membership behind it is
            // gone. Refreshing this session would not help and would hide
            // what happened, so it is reported as it is.
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
            // Still unauthorised with a freshly minted token: the server has
            // revoked the user (denylist), so the session is gone too.
            if signalsSessionLoss { sessionLost(.expired) }
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
                                  accept: accept, authorized: authorized, bearer: bearer,
                                  allowRefresh: allowRefresh, allowReauth: false,
                                  signalsSessionLoss: signalsSessionLoss)
        }

        if http.statusCode == 403, authorized, allowRefresh, bearer == nil,
           failure().isRoleDenial {
            // A role denial, not a session problem. The `roles` claim is
            // re-read from the workspace membership every time a token is
            // minted, so a token taken out before the person was granted
            // what they now hold keeps being refused until it rotates —
            // which, for an account that was just created or just given a
            // role, is the whole of the "you are not allowed to work with
            // notes here" wall. Rotate once and try again; if the denial
            // is genuine the retry earns the same 403 and it reaches the
            // caller with `allowRefresh: false`, so this costs one request.
            // A borrowed `bearer` is excluded: it is not this session's
            // token, and rotating the session would not change it.
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
