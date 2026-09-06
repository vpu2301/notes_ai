import XCTest
@testable import NotesAICapture

/// The dual-issuer period (ADR-0047), from the phone's side.
///
/// During `dual` this app can be holding either kind of refresh token, and
/// the two are not interchangeable: one idles for thirty days and can be
/// sealed behind a face, the other idles for thirty minutes and cannot.
/// Everything here is about the app noticing which one it has — because
/// the failure it prevents is silent. A Keycloak session with no keepalive
/// does not look broken; it looks fine for twenty-nine minutes and then
/// loses a recording.
final class DualSessionTests: XCTestCase {

    // MARK: - Telling the two apart

    func testTheTokenPrefixIsWhatDecides() {
        // The same rule BE-2 routes `/auth/refresh` on, so the phone and
        // the server cannot disagree about what a token is.
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
        // `routers/login.py` honours `X-Client-Type: ios` and puts the
        // Keycloak refresh token in the body, exactly as the native login
        // does — so this phone holds it in the same Keychain item, and
        // nothing here needs a cookie jar. `kind` is the whole difference.
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
        // The keepalive decision is made at boot, before any face prompt
        // can be shown — so the field has to be in the clear even when the
        // token beside it is sealed.
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
        // Keycloak's refresh token dies after the realm's idle timeout.
        // Without this the app is signed out mid-meeting and finds out
        // when it tries to upload — which is the worst possible moment.
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
        // The same 61-second access token, and this time nothing happens:
        // a native refresh token idles for thirty days, and waking the
        // phone every minute to prove it would cost battery for nothing.
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
        // De-escalation is honoured whatever kind of session is loaded:
        // refusing to *remove* protection is the wrong way round.
        let storage = InMemorySessionStorage(seed: Fixtures.record(refreshToken: Fixtures.keycloakToken))
        let gate = FakeGate()
        _ = try gate.create()
        let store = SessionStore(storage: storage, gate: gate)

        try await store.setGate(enabled: false)

        XCTAssertFalse(gate.exists())
    }

    func testSigningInWithAPasswordDoesNotDestroyAGateTheOwnerAskedFor() async throws {
        // A phone that used the gate on a native session, then signed in
        // with a password: the Keycloak session is ungated (it must be),
        // but the gate key is left alone so the next native sign-in finds
        // the preference the owner set.
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
        // IOS-1: built, tested, and deliberately not on screen until every
        // session is native (I1-05). Asserted so that turning it back on
        // is a decision somebody makes, not one that drifts in.
        XCTAssertFalse(AppState.gateOffered)
    }

    // MARK: - `409 use_password`

    func testTheServerCanSendAnAddressToThePasswordForm() async {
        // BE-3's answer for an address that belongs to a Keycloak account.
        // A redirection, not a failure: the sign-in screen shows the
        // password form and keeps the address the person just typed.
        //
        // On `verify`, never on `start`: the start endpoint answers 202
        // for every address by construction, and saying "use a password"
        // there would tell an unauthenticated caller which addresses
        // exist. Here the code has already proved the mailbox.
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
        // Recorded in ADR-0047 up front: auth-service cannot re-mint a
        // Keycloak token for another tenant, so this is the one capability
        // `dual` splits by token origin.
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
