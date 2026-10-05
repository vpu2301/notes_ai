import XCTest
@testable import NotesAICapture

/// The dual-issuer period (ADR-0047): the app must notice which kind of
/// refresh token it holds (30-day gated native vs 30-minute Keycloak).
final class DualSessionTests: XCTestCase {

    // MARK: - Telling the two apart

    func testTheTokenPrefixIsWhatDecides() {
        // The same rule the server routes `/auth/refresh` on.
        XCTAssertEqual(SessionKind(refreshToken: "nrt_abc"), .native)
        XCTAssertEqual(SessionKind(refreshToken: Fixtures.keycloakToken), .keycloak)
        XCTAssertEqual(SessionKind(refreshToken: ""), .keycloak,
                       "anything that is not ours is the other issuer's")
    }

    func testEachKindKnowsWhatItCanDo() {
        XCTAssertFalse(SessionKind.native.needsKeepAlive)
        XCTAssertTrue(SessionKind.keycloak.needsKeepAlive)
        XCTAssertFalse(SessionKind.native.canSavePassword)
        XCTAssertTrue(SessionKind.keycloak.canSavePassword)
        XCTAssertTrue(SessionKind.native.canGate)
        XCTAssertFalse(SessionKind.keycloak.canGate)
    }

    // MARK: - What the sign-in stores

    func testAnEmailCodeSignInStoresANativeSession() async throws {
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in (200, Fixtures.authenticated(refreshToken: "nrt_new"), [:]) }

        _ = try await client.verifyEmailCode(challengeId: "c-1", code: "123456")

        let kind = await client.sessionKind
        XCTAssertEqual(storage.record?.kind, .native)
        XCTAssertEqual(kind, .native)
    }

    func testAPasswordSignInStoresAKeycloakSession() async throws {
        // The Keycloak login also puts the refresh token in the body; `kind` is the whole difference.
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in
            (200, Fixtures.authenticated(refreshToken: Fixtures.keycloakToken,
                                         refreshExpiresIn: 1_800), [:])
        }

        _ = try await client.login(email: "olena@acme.example", password: "hunter2")

        let kind = await client.sessionKind
        XCTAssertEqual(storage.record?.kind, .keycloak)
        XCTAssertEqual(kind, .keycloak)
        XCTAssertNil(StubServer.requests(to: "/auth/login").first?.headers["Cookie"],
                     "no cookie in either direction, whoever minted the token")
    }

    func testTheStoredKindIsReadableWithoutOpeningTheToken() async throws {
        // The keepalive decision is made at boot, before any prompt: the field must be in the clear.
        let storage = InMemorySessionStorage()
        let gate = FakeGate()
        let store = SessionStore(storage: storage, gate: gate)
        try await store.setGate(enabled: true)
        try await store.save(Fixtures.storedSession(refreshToken: "nrt_secret"))

        let summary = await store.summary()
        XCTAssertEqual(summary?.kind, .native)
        XCTAssertFalse(storage.storedText.contains("nrt_secret"), "sealed, as before")
        XCTAssertTrue(storage.storedText.contains("native"), "but the issuer is legible")
    }

    // MARK: - The keepalive, for one kind of session only

    func testAKeycloakSessionRefreshesBeforeItsTokenIdlesOut() async throws {
        // Keycloak's refresh token dies after the idle timeout; without this the upload fails.
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        let refreshes = Counter()
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(
                    refreshToken: "\(Fixtures.keycloakToken)-\(refreshes.next())",
                    expiresIn: 900, refreshExpiresIn: 1_800), [:])
            default:
                // 61 seconds of access token: the keepalive is due in one.
                return (200, Fixtures.authenticated(refreshToken: Fixtures.keycloakToken,
                                                    expiresIn: 61,
                                                    refreshExpiresIn: 1_800), [:])
            }
        }

        _ = try await client.login(email: "olena@acme.example", password: "hunter2")
        try await Task.sleep(for: .seconds(2))

        XCTAssertEqual(StubServer.requests(to: "/auth/refresh").count, 1,
                       "the session renewed itself with nobody touching the phone")
        XCTAssertEqual(storage.record?.kind, .keycloak)
    }

    func testANativeSessionArmsNoKeepAlive() async throws {
        // The same 61-second access token; a native session arms nothing.
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in
            (200, Fixtures.authenticated(refreshToken: "nrt_new", expiresIn: 61), [:])
        }

        _ = try await client.verifyEmailCode(challengeId: "c-1", code: "123456")
        try await Task.sleep(for: .seconds(2))

        XCTAssertTrue(StubServer.requests(to: "/auth/refresh").isEmpty,
                      "an idle native session makes no requests at all")
    }

    func testSigningOutStopsTheKeepAlive() async throws {
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { request in
            request.path == "/auth/logout"
                ? (204, Data(), [:])
                : (200, Fixtures.authenticated(refreshToken: Fixtures.keycloakToken,
                                               expiresIn: 61, refreshExpiresIn: 1_800), [:])
        }

        _ = try await client.login(email: "olena@acme.example", password: "hunter2")
        await client.logout()
        try await Task.sleep(for: .seconds(2))

        XCTAssertTrue(StubServer.requests(to: "/auth/refresh").isEmpty,
                      "a signed-out app does not keep a session alive behind the person's back")
    }

    // MARK: - The gate is native-only, and off in this batch

    func testAKeycloakSessionCannotBeGated() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.record(refreshToken: Fixtures.keycloakToken))
        let store = SessionStore(storage: storage, gate: FakeGate())

        do {
            try await store.setGate(enabled: true)
            XCTFail("a Keycloak refresh token has nothing this app can seal")
        } catch let error as SessionStoreError {
            XCTAssertEqual(error, .gateUnavailable)
        }
        XCTAssertEqual(storage.record?.gated, false)
    }

    func testTurningTheGateOffIsNeverRefused() async throws {
        // De-escalation is honoured for every kind of session.
        let storage = InMemorySessionStorage(seed: Fixtures.record(refreshToken: Fixtures.keycloakToken))
        let gate = FakeGate()
        _ = try gate.create()
        let store = SessionStore(storage: storage, gate: gate)

        try await store.setGate(enabled: false)

        XCTAssertFalse(gate.exists())
    }

    func testSigningInWithAPasswordDoesNotDestroyAGateTheOwnerAskedFor() async throws {
        // Keycloak session ungated, but the gate key is left for the next native sign-in.
        let storage = InMemorySessionStorage()
        let gate = FakeGate()
        let store = SessionStore(storage: storage, gate: gate)
        try await store.setGate(enabled: true)

        try await store.save(Fixtures.storedSession(refreshToken: Fixtures.keycloakToken))

        XCTAssertEqual(storage.record?.gated, false)
        XCTAssertTrue(gate.exists(), "the key outlives the session it protected")
    }

    @MainActor
    func testTheGateIsNotOfferedInThisBatch() {
        // Deliberately off until every session is native; asserted so turning it on is a decision.
        XCTAssertFalse(AppState.gateOffered)
    }

    // MARK: - `409 use_password`

    func testTheServerCanSendAnAddressToThePasswordForm() async {
        // A Keycloak account: a redirection to the password form, keeping the
        // address. On `verify`, never on `start` (start answers 202 for every address).
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in
            (409, Fixtures.json([
                "title": "Conflict", "status": 409,
                "detail": "this account signs in with a password",
                "code": "use_password",
            ]), [:])
        }

        do {
            _ = try await client.verifyEmailCode(challengeId: "c-1", code: "123456")
            XCTFail("the server refused")
        } catch let error as APIError {
            XCTAssertTrue(error.isUsePassword)
            XCTAssertEqual(AuthCopy.message(for: error),
                           "This account signs in with a password. Enter it below.")
        } catch {
            XCTFail("unexpected \(error)")
        }
        XCTAssertNil(storage.record, "nothing is stored on a redirection")
    }

    func testAPlainConflictIsNotAPasswordRedirect() async {
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in
            (409, Fixtures.json(["status": 409, "code": "challenge_consumed"]), [:])
        }

        do {
            _ = try await client.verifyEmailCode(challengeId: "c-1", code: "123456")
            XCTFail("the server refused")
        } catch let error as APIError {
            XCTAssertFalse(error.isUsePassword)
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    // MARK: - `409 legacy_session`

    func testSwitchingWorkspaceIsNativeOnly() async {
        // ADR-0047: a Keycloak token cannot be re-minted for another tenant.
        let storage = InMemorySessionStorage(seed: Fixtures.record(refreshToken: Fixtures.keycloakToken))
        let client = makeClient(storage: storage)
        StubServer.install { request in
            request.path == "/auth/token"
                ? (409, Fixtures.json(["status": 409, "code": "legacy_session"]), [:])
                : (200, Fixtures.authenticated(refreshToken: Fixtures.keycloakToken,
                                               refreshExpiresIn: 1_800), [:])
        }

        do {
            _ = try await client.switchWorkspace(to: "33333333-3333-3333-3333-333333333333")
            XCTFail("a Keycloak session cannot switch workspace")
        } catch let error as APIError {
            XCTAssertTrue(error.isLegacySession)
            XCTAssertEqual(
                AuthCopy.message(for: error),
                "Switching workspace needs the new sign-in. Sign out and sign in with an emailed code, or switch in the web app.")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }
}
