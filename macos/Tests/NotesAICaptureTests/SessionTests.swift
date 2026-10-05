import XCTest
@testable import NotesAICapture

/// The session this Mac keeps, and how it is spent.
final class SessionTests: XCTestCase {

    // MARK: - The store

    func testSavingThenLoadingRoundTrips() async throws {
        let storage = InMemorySessionStorage()
        let store = SessionStore(storage: storage)
        let session = Fixtures.storedSession(refreshToken: "rt-a")

        try await store.save(session)
        let loaded = await store.load()

        XCTAssertEqual(loaded?.refreshToken, "rt-a")
        XCTAssertEqual(loaded?.email, "olena@acme.example")
    }

    func testRotateKeepsWhoTheSessionBelongsTo() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.storedSession(refreshToken: "rt-a"))
        let store = SessionStore(storage: storage)

        try await store.rotate(refreshToken: "rt-b",
                               expiresAt: Date().addingTimeInterval(60),
                               tenantId: nil)

        XCTAssertEqual(storage.session?.refreshToken, "rt-b")
        XCTAssertEqual(storage.session?.identityId, "22222222-2222-2222-2222-222222222222")
    }

    func testAKeychainThatRefusesTheWriteIsAnError() async {
        let storage = InMemorySessionStorage()
        storage.writeStatus = errSecInteractionNotAllowed
        let store = SessionStore(storage: storage)

        do {
            try await store.save(Fixtures.storedSession())
            XCTFail("a refused write must not look like a stored session")
        } catch {
            // The message names the Keychain: that is what the person has to unlock.
            XCTAssertTrue(error.localizedDescription.contains("Keychain"))
        }
    }

    func testUnreadableBytesAreTreatedAsNoSession() async {
        let storage = InMemorySessionStorage()
        _ = storage.write(Data("not json".utf8))
        let store = SessionStore(storage: storage)

        let loaded = await store.load()

        XCTAssertNil(loaded)
        XCTAssertEqual(storage.deletes, 1, "an unusable item is cleared, not left behind")
    }

    // MARK: - Signing in

    func testCodeSignInPutsTheRefreshTokenInTheKeychain() async throws {
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in (200, Fixtures.authenticated(refreshToken: "rt-new"), [:]) }

        let result = try await client.verifyEmailCode(challengeId: "c-1", code: "123456")

        guard case .authenticated(let session) = result else {
            return XCTFail("expected a session")
        }
        XCTAssertEqual(session.identity?.email, "olena@acme.example")
        XCTAssertEqual(storage.session?.refreshToken, "rt-new")
    }

    func testASessionWithNoRefreshTokenIsRefused() async {
        // A server that took this app for a browser: the token is in a `Set-Cookie` the app has nowhere to put.
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in
            (200, Fixtures.json([
                "status": "authenticated", "access_token": "at-1", "expires_in": 900,
                "tenant_id": "t", "roles": ["member"],
            ]), [:])
        }

        do {
            _ = try await client.verifyEmailCode(challengeId: "c-1", code: "123456")
            XCTFail("a cookie-only session is not a session this app can keep")
        } catch APIError.noNativeSession {
            XCTAssertNil(storage.session)
            // It says which of the two problems it is: the fix is on the server.
            XCTAssertTrue(AuthCopy.message(for: APIError.noNativeSession)
                .contains("cannot keep this Mac signed in"))
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testAKeychainFailureDuringSignInDoesNotLeaveTheAppSignedIn() async {
        let storage = InMemorySessionStorage()
        storage.writeStatus = errSecInteractionNotAllowed
        let client = makeClient(storage: storage)
        StubServer.install { _ in (200, Fixtures.authenticated(), [:]) }

        do {
            _ = try await client.verifyEmailCode(challengeId: "c-1", code: "123456")
            XCTFail("the sign-in must fail with the write")
        } catch {
            let stored = await client.storedSession()
            XCTAssertNil(stored)
        }
    }

    func testMFAIsAnswerAndNotASession() async throws {
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { request in
            request.path.hasSuffix("/mfa/verify")
                ? (200, Fixtures.authenticated(refreshToken: "rt-after-mfa"), [:])
                : (200, Fixtures.mfaRequired(), [:])
        }

        let first = try await client.verifyEmailCode(challengeId: "c-1", code: "123456")
        guard case .mfaRequired(let challengeId, let methods, _) = first else {
            return XCTFail("expected the second factor to be owed")
        }
        XCTAssertEqual(challengeId, "c-1")
        XCTAssertEqual(methods, ["totp", "recovery_code"])
        XCTAssertNil(storage.session, "nothing is stored on the near side of the second factor")

        let second = try await client.verifyMFA(challengeId: challengeId, method: "totp", code: "000000")
        guard case .authenticated = second else { return XCTFail("expected a session") }
        XCTAssertEqual(storage.session?.refreshToken, "rt-after-mfa")
    }

    // MARK: - Refresh

    func testRefreshRotatesTheStoredToken() async {
        let storage = InMemorySessionStorage(seed: Fixtures.storedSession(refreshToken: "rt-0"))
        let client = makeClient(storage: storage)
        StubServer.install { _ in (200, Fixtures.authenticated(refreshToken: "rt-1"), [:]) }

        let restored = await client.restoreSession()

        guard case .signedIn = restored else { return XCTFail("expected a live session") }
        XCTAssertEqual(storage.session?.refreshToken, "rt-1")
        let sent = StubServer.requests(to: "/auth/refresh").first?.json()
        XCTAssertEqual(sent?["refresh_token"] as? String, "rt-0",
                       "the refresh token travels in the body, never in a cookie")
    }

    func testTwoConcurrentUnauthorisedRequestsShareOneRefresh() async {
        let storage = InMemorySessionStorage(seed: Fixtures.storedSession())
        let client = makeClient(storage: storage)
        let unauthorised = Counter()
        StubServer.install { request in
            if request.path == "/auth/refresh" {
                return (200, Fixtures.authenticated(refreshToken: "rt-\(UUID().uuidString)"), [:])
            }
            // The first two API calls answer 401; both callers want a refresh at the same moment.
            return unauthorised.next() <= 2
                ? (401, Fixtures.problem("session_expired"), [:])
                : (200, Fixtures.json(["spaces": []]), [:])
        }

        async let first: [Space] = client.fetchSpaces()
        async let second: [Space] = client.fetchSpaces()
        let results = try? await [first, second]

        XCTAssertEqual(results?.count, 2)
        // Two refreshes: one for no access token, one shared by the two 401s. Three would be a replayed refresh token.
        XCTAssertEqual(StubServer.requests(to: "/auth/refresh").count, 2)
    }

    func testAReplayedRefreshTokenWipesTheSessionAndSaysWhy() async {
        let storage = InMemorySessionStorage(seed: Fixtures.storedSession())
        let client = makeClient(storage: storage)
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (401, Fixtures.problem("auth_refresh_replay"), [:])
                : (401, Fixtures.problem("session_expired"), [:])
        }
        let reasons = ReasonBox()
        await client.onSessionLost { reasons.record($0) }

        _ = try? await client.fetchSpaces()

        XCTAssertNil(storage.session, "the Keychain item goes with the session")
        XCTAssertEqual(reasons.value, .securityRevoked)
        XCTAssertEqual(reasons.value?.message,
                       "You were signed out for security. Sign in again.")
    }

    func testANetworkErrorAtBootKeepsTheSession() async {
        let storage = InMemorySessionStorage(seed: Fixtures.storedSession(refreshToken: "rt-keep"))
        let client = makeClient(storage: storage)
        StubServer.install { _ in (0, Data(), [:]) }  // no reply at all

        let restored = await client.restoreSession()

        guard case .offline(let stored) = restored else {
            return XCTFail("an unreachable server is not a sign-out")
        }
        XCTAssertEqual(stored.refreshToken, "rt-keep")
        XCTAssertEqual(storage.session?.refreshToken, "rt-keep")
        XCTAssertEqual(storage.deletes, 0)
    }

    func testAnExpiredStoredSessionIsDroppedWithoutAskingTheServer() async {
        let stored = Fixtures.storedSession(refreshToken: "rt-old", expiresIn: -60)
        let storage = InMemorySessionStorage(seed: stored)
        let client = makeClient(storage: storage)
        StubServer.install { _ in (200, Fixtures.authenticated(), [:]) }

        let restored = await client.restoreSession()

        // The token is gone, but who it belonged to is not: kept recordings must still be found.
        guard case .expired(let carried) = restored else {
            return XCTFail("an expired session is not the same as never having had one")
        }
        XCTAssertEqual(carried.identityId, stored.identityId)
        XCTAssertEqual(carried.email, stored.email)
        XCTAssertEqual(carried.lastTenantId, stored.lastTenantId)
        XCTAssertNil(storage.session, "a dead token is not worth keeping")
        XCTAssertTrue(StubServer.requests.isEmpty, "nothing to ask about")
    }

    func testAnExpiredSessionSignsOutWithTheOrdinaryMessage() async {
        let storage = InMemorySessionStorage(seed: Fixtures.storedSession())
        let client = makeClient(storage: storage)
        StubServer.install { _ in (401, Fixtures.problem("session_expired"), [:]) }
        let reasons = ReasonBox()
        await client.onSessionLost { reasons.record($0) }

        _ = try? await client.fetchSpaces()

        XCTAssertEqual(reasons.value, .expired)
        XCTAssertNil(storage.session)
    }

    // MARK: - Signing out

    func testLogoutSendsTheTokenAndClearsTheItem() async {
        let storage = InMemorySessionStorage(seed: Fixtures.storedSession(refreshToken: "rt-bye"))
        let client = makeClient(storage: storage)
        StubServer.install { _ in (204, Data(), [:]) }

        await client.logout()

        XCTAssertEqual(StubServer.requests(to: "/auth/logout").first?.json()["refresh_token"] as? String,
                       "rt-bye")
        XCTAssertNil(storage.session)
    }

    func testLogoutClearsTheItemEvenWhenTheServerIsUnreachable() async {
        let storage = InMemorySessionStorage(seed: Fixtures.storedSession())
        let client = makeClient(storage: storage)
        StubServer.install { _ in (0, Data(), [:]) }

        await client.logout()

        XCTAssertNil(storage.session, "signing out is something the person did, not a request")
    }
}

// MARK: - Small test helpers

/// A counter the stub's `@Sendable` handler can close over.
final class Counter: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0

    func next() -> Int {
        lock.lock(); defer { lock.unlock() }
        count += 1
        return count
    }
}

final class ReasonBox: @unchecked Sendable {
    private let lock = NSLock()
    private var reason: SessionLostReason?

    func record(_ reason: SessionLostReason) {
        lock.lock(); defer { lock.unlock() }
        self.reason = reason
    }

    var value: SessionLostReason? {
        lock.lock(); defer { lock.unlock() }
        return reason
    }
}

/// The whole life of a session, in the order it happens.
final class SessionLifecycleTests: XCTestCase {

    func testSignInThenRefreshThenSignOut() async throws {
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        let refreshes = Counter()
        StubServer.install { request in
            switch request.path {
            case "/auth/email/verify":
                return (200, Fixtures.authenticated(refreshToken: "rt-1", expiresIn: 900), [:])
            case "/auth/refresh":
                return (200, Fixtures.authenticated(refreshToken: "rt-\(refreshes.next() + 1)"), [:])
            case "/auth/logout":
                return (204, Data(), [:])
            default:
                return (200, Fixtures.json(["spaces": []]), [:])
            }
        }

        // 1. Sign in: the item is created.
        _ = try await client.verifyEmailCode(challengeId: "c-1", code: "123456")
        XCTAssertEqual(storage.session?.refreshToken, "rt-1")

        // 2. A later launch, or an expired access token: the item is rotated.
        let restored = await client.restoreSession()
        guard case .signedIn = restored else { return XCTFail("expected a live session") }
        XCTAssertEqual(storage.session?.refreshToken, "rt-2")
        XCTAssertEqual(storage.session?.email, "olena@acme.example",
                       "rotation replaces the token, not who it belongs to")

        // 3. Sign out: the item is gone.
        await client.logout()
        XCTAssertNil(storage.session)
        let after = await client.restoreSession()
        XCTAssertEqual(after, .signedOut)
    }

    func testALongRecordingCostsExactlyOneRefresh() async throws {
        // A native session idles for thirty days: nothing while recording, one refresh when the access token expired, then the upload.
        let storage = InMemorySessionStorage(seed: Fixtures.storedSession())
        let client = makeClient(storage: storage)
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (200, Fixtures.json(["spaces": []]), [:])
        }

        _ = try await client.fetchSpaces()

        XCTAssertEqual(StubServer.requests(to: "/auth/refresh").count, 1)
        XCTAssertEqual(StubServer.requests(to: "/v1/spaces").count, 1)
    }

    // MARK: - Keeping a short-lived session alive

    /// Sign in against a server stating `refreshExpiresIn` seconds of refresh-token life; report whether the app kept it warm.
    private func armedAfterSignIn(refreshExpiresIn: Int) async throws -> APIClient {
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in
            (200, Fixtures.authenticated(refreshExpiresIn: refreshExpiresIn), [:])
        }
        _ = try await client.verifyEmailCode(challengeId: "c-1", code: "123456")
        return client
    }

    func testANativeSessionArmsNoKeepAlive() async throws {
        // Thirty days of idle life: no keepalive.
        let client = try await armedAfterSignIn(refreshExpiresIn: 2_592_000)

        let armed = await client.keepAliveIsArmed
        XCTAssertFalse(armed)
    }

    func testAKeycloakSessionIsKeptWarm() async throws {
        // `ssoSessionIdleTimeout` is 1800 in the realm and belongs to the Keycloak session, so a token in the Keychain idles out just as fast.
        let client = try await armedAfterSignIn(refreshExpiresIn: 1800)

        let armed = await client.keepAliveIsArmed
        XCTAssertTrue(armed)
    }

    func testARealmReconfiguredToTwoHoursIsStillKeptWarm() async throws {
        // The rule reads the lifetime the server states, not a token prefix (`nrt_` never reached the wire).
        let client = try await armedAfterSignIn(refreshExpiresIn: 7200)

        let armed = await client.keepAliveIsArmed
        XCTAssertTrue(armed)
    }

    func testAPrefixedNativeTokenIsNeverKeptWarm() async throws {
        // Belt and braces: an `nrt_` prefix (ADR-0047) keeps a native session unarmed even if the server understates its life.
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in
            (200, Fixtures.authenticated(refreshToken: "nrt_abc", refreshExpiresIn: 1800), [:])
        }
        _ = try await client.verifyEmailCode(challengeId: "c-1", code: "123456")

        let armed = await client.keepAliveIsArmed
        XCTAssertFalse(armed)
    }

    func testSigningOutDisarmsTheKeepAlive() async throws {
        // A timer that outlived the session would refresh a gone token and report the session lost to somebody signed out.
        let client = try await armedAfterSignIn(refreshExpiresIn: 1800)
        let armedBefore = await client.keepAliveIsArmed
        XCTAssertTrue(armedBefore)

        await client.logout()

        let armedAfter = await client.keepAliveIsArmed
        XCTAssertFalse(armedAfter)
    }

    func testAKeycloakSessionSignsInAndIsKept() async throws {
        // The `/auth/login` proxy hands a native client the Keycloak refresh token in the body; kept like a native one.
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in
            (200, Fixtures.authenticated(refreshToken: "kc-rt", refreshExpiresIn: 1800), [:])
        }

        _ = try await client.login(email: "olena@acme.example", password: "hunter2")

        XCTAssertEqual(storage.session?.refreshToken, "kc-rt")
        let armed = await client.keepAliveIsArmed
        XCTAssertTrue(armed)
    }

    func testTheKeycloakLoginShapeStillParses() throws {
        // `/auth/login` answers the three token fields only. It must decode, then be refused for having no refresh token.
        let data = Fixtures.json(["access_token": "at", "expires_in": 900, "token_type": "Bearer"])
        let dto = try JSONDecoder().decode(AuthResultDTO.self, from: data)

        XCTAssertEqual(dto.status, "authenticated")
        XCTAssertNil(dto.refreshToken)
        guard case .authenticated(let session) = try dto.result() else {
            return XCTFail("expected the token fields to be read")
        }
        XCTAssertEqual(session.accessToken, "at")
        XCTAssertNil(session.refreshToken)
    }
}
