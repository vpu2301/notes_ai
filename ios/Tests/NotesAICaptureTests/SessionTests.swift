import CryptoKit
import XCTest
@testable import NotesAICapture

/// IDX-I1 — the session this phone keeps, and how it is spent.
final class SessionTests: XCTestCase {

    // MARK: - The store

    func testSavingThenLoadingRoundTrips() async throws {
        let storage = InMemorySessionStorage()
        let store = SessionStore(storage: storage, gate: FakeGate())

        try await store.save(Fixtures.storedSession(refreshToken: "nrt_rt-a"))
        let loaded = try await store.load()

        XCTAssertEqual(loaded?.refreshToken, "nrt_rt-a")
        XCTAssertEqual(loaded?.email, "olena@acme.example")
    }

    func testRotateKeepsWhoTheSessionBelongsTo() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.record(refreshToken: "nrt_rt-a"))
        let store = SessionStore(storage: storage, gate: FakeGate())

        try await store.rotate(refreshToken: "nrt_rt-b",
                               expiresAt: Date().addingTimeInterval(60),
                               tenantId: nil)

        XCTAssertEqual(storage.record?.token, "nrt_rt-b")
        XCTAssertEqual(storage.record?.identityId, "22222222-2222-2222-2222-222222222222")
    }

    func testAKeychainThatRefusesTheWriteIsAnError() async {
        let storage = InMemorySessionStorage()
        storage.writeStatus = errSecInteractionNotAllowed
        let store = SessionStore(storage: storage, gate: FakeGate())

        do {
            try await store.save(Fixtures.storedSession())
            XCTFail("a refused write must not look like a stored session")
        } catch {
            // The message names the Keychain, because that is what the
            // person has to go and unlock.
            XCTAssertTrue(error.localizedDescription.contains("Keychain"))
        }
    }

    func testUnreadableBytesAreTreatedAsNoSession() async {
        let storage = InMemorySessionStorage()
        _ = storage.write(Data("not json".utf8))
        let store = SessionStore(storage: storage, gate: FakeGate())

        let summary = await store.summary()

        XCTAssertNil(summary)
        XCTAssertEqual(storage.deletes, 1, "an unusable item is cleared, not left behind")
    }

    // MARK: - The biometric gate

    func testWithTheGateOnTheTokenIsNotInTheItem() async throws {
        let storage = InMemorySessionStorage()
        let gate = FakeGate()
        let store = SessionStore(storage: storage, gate: gate)
        try await store.save(Fixtures.storedSession(refreshToken: "nrt_rt-secret"))

        try await store.setGate(enabled: true)

        XCTAssertTrue(storage.record?.gated == true)
        XCTAssertFalse(storage.storedText.contains("nrt_rt-secret"),
                       "the refresh token is sealed, not merely flagged")
        // Everything the boot path needs is still readable without a face.
        let summary = await store.summary()
        XCTAssertEqual(summary?.email, "olena@acme.example")
        XCTAssertEqual(summary?.gated, true)
        // And it still opens for the app that holds the key.
        let opened = try await store.load()
        XCTAssertEqual(opened?.refreshToken, "nrt_rt-secret")
    }

    func testAGatedItemIsUnreadableInAFreshLaunch() async throws {
        let storage = InMemorySessionStorage()
        let gate = FakeGate()
        let first = SessionStore(storage: storage, gate: gate)
        try await first.save(Fixtures.storedSession(refreshToken: "nrt_rt-secret"))
        try await first.setGate(enabled: true)

        // A new launch: the same Keychain, the same gate item, no key held.
        let second = SessionStore(storage: storage, gate: gate)
        do {
            _ = try await second.load()
            XCTFail("a gated session must not open without the gate key")
        } catch SessionStoreError.locked {
            // As it should be.
        }

        try await second.unlock(reason: "test")
        let opened = try await second.load()
        XCTAssertEqual(opened?.refreshToken, "nrt_rt-secret")
        XCTAssertEqual(gate.prompts, 1)
    }

    func testTheWrongKeyDoesNotOpenTheItem() async throws {
        let storage = InMemorySessionStorage()
        let gate = FakeGate()
        let store = SessionStore(storage: storage, gate: gate)
        try await store.save(Fixtures.storedSession(refreshToken: "nrt_rt-secret"))
        try await store.setGate(enabled: true)
        let sealed = storage.record!

        // Another gate key entirely — what an attacker who copied the item
        // to another phone would be working with.
        let otherGate = FakeGate()
        _ = try otherGate.create()
        let other = SessionStore(storage: InMemorySessionStorage(seed: sealed), gate: otherGate)
        try await other.unlock(reason: "test")

        do {
            _ = try await other.load()
            XCTFail("AES-GCM must refuse a key that did not seal it")
        } catch SessionStoreError.undecipherable {
            // The AEAD tag is the whole point.
        }
    }

    func testChangingTheBiometryWipesTheSession() async throws {
        let storage = InMemorySessionStorage()
        let gate = FakeGate()
        let store = SessionStore(storage: storage, gate: gate)
        try await store.save(Fixtures.storedSession())
        try await store.setGate(enabled: true)

        gate.simulateBiometryChange()
        let next = SessionStore(storage: storage, gate: gate)
        do {
            try await next.unlock(reason: "test")
            XCTFail("the key is gone; the session cannot be opened again")
        } catch SessionStoreError.gateLost {
            XCTAssertNil(storage.record,
                         "an item nothing can ever open is not left on the phone")
        }
    }

    func testTurningTheGateOffPutsTheTokenBackInTheClearAndDestroysTheKey() async throws {
        let storage = InMemorySessionStorage()
        let gate = FakeGate()
        let store = SessionStore(storage: storage, gate: gate)
        try await store.save(Fixtures.storedSession(refreshToken: "nrt_rt-plain"))
        try await store.setGate(enabled: true)

        try await store.setGate(enabled: false)

        XCTAssertEqual(storage.record?.token, "nrt_rt-plain")
        XCTAssertEqual(storage.record?.gated, false)
        XCTAssertFalse(gate.exists(), "a key nothing references does not survive the switch")
    }

    func testACancelledPromptLeavesTheSessionAlone() async throws {
        let storage = InMemorySessionStorage()
        let gate = FakeGate()
        let store = SessionStore(storage: storage, gate: gate)
        try await store.save(Fixtures.storedSession())
        try await store.setGate(enabled: true)

        gate.refuses = true
        let next = SessionStore(storage: storage, gate: gate)
        do {
            try await next.unlock(reason: "test")
            XCTFail("a cancelled prompt is not an unlock")
        } catch SessionStoreError.locked {
            XCTAssertNotNil(storage.record, "cancelling is not signing out")
        }
    }

    func testAGatedSessionStopsTheClientBeforeAnythingIsSent() async throws {
        let storage = InMemorySessionStorage()
        let gate = FakeGate()
        let store = SessionStore(storage: storage, gate: gate)
        try await store.save(Fixtures.storedSession())
        try await store.setGate(enabled: true)

        // A fresh launch over the same Keychain.
        let client = APIClient(settings: .default,
                               store: SessionStore(storage: storage, gate: gate),
                               configuration: StubServer.configuration())
        StubServer.install { _ in (200, Fixtures.authenticated(), [:]) }

        let restored = await client.restoreSession()

        guard case .locked = restored else { return XCTFail("expected a locked session") }
        XCTAssertTrue(StubServer.requests.isEmpty,
                      "nothing carrying a token leaves the phone before the gate opens")
    }

    func testSigningInAgainKeepsTheGateOn() async throws {
        // Signing out drops the key this launch held but leaves the gate
        // item — the person asked for a gate, not for one session. The
        // next sign-in must be sealed too, or the preference has silently
        // turned itself off.
        let storage = InMemorySessionStorage()
        let gate = FakeGate()
        let store = SessionStore(storage: storage, gate: gate)
        try await store.save(Fixtures.storedSession())
        try await store.setGate(enabled: true)
        await store.clear()

        let next = SessionStore(storage: storage, gate: gate)
        try await next.save(Fixtures.storedSession(refreshToken: "nrt_rt-second"))

        XCTAssertEqual(storage.record?.gated, true)
        XCTAssertFalse(storage.storedText.contains("nrt_rt-second"))
    }

    // MARK: - Signing in

    func testCodeSignInPutsTheRefreshTokenInTheKeychain() async throws {
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { _ in (200, Fixtures.authenticated(refreshToken: "nrt_rt-new"), [:]) }

        let result = try await client.verifyEmailCode(challengeId: "c-1", code: "123456")

        guard case .authenticated(let session) = result else {
            return XCTFail("expected a session")
        }
        XCTAssertEqual(session.identity?.email, "olena@acme.example")
        XCTAssertEqual(storage.record?.token, "nrt_rt-new")
    }

    func testASessionWithNoRefreshTokenIsRefused() async {
        // What a server that took this app for a browser answers: the token
        // is in a `Set-Cookie` the app has nowhere to put. Signing in
        // "successfully" here would end fifteen minutes later.
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
            XCTAssertNil(storage.record)
            XCTAssertTrue(AuthCopy.message(for: APIError.noNativeSession)
                .contains("cannot keep this phone signed in"))
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
            let summary = await client.storedSummary()
            XCTAssertNil(summary)
        }
    }

    func testMFAIsAnAnswerAndNotASession() async throws {
        let storage = InMemorySessionStorage()
        let client = makeClient(storage: storage)
        StubServer.install { request in
            request.path.hasSuffix("/mfa/verify")
                ? (200, Fixtures.authenticated(refreshToken: "nrt_rt-after-mfa"), [:])
                : (200, Fixtures.mfaRequired(), [:])
        }

        let first = try await client.verifyEmailCode(challengeId: "c-1", code: "123456")
        guard case .mfaRequired(let challengeId, let methods, _) = first else {
            return XCTFail("expected the second factor to be owed")
        }
        XCTAssertEqual(challengeId, "c-1")
        XCTAssertEqual(methods, ["totp", "recovery_code"])
        XCTAssertNil(storage.record, "nothing is stored on the near side of the second factor")

        let second = try await client.verifyMFA(challengeId: challengeId, method: "totp", code: "000000")
        guard case .authenticated = second else { return XCTFail("expected a session") }
        XCTAssertEqual(storage.record?.token, "nrt_rt-after-mfa")
    }

    // MARK: - Refresh

    func testRefreshRotatesTheStoredToken() async {
        let storage = InMemorySessionStorage(seed: Fixtures.record(refreshToken: "nrt_rt-0"))
        let client = makeClient(storage: storage)
        StubServer.install { _ in (200, Fixtures.authenticated(refreshToken: "nrt_rt-1"), [:]) }

        let restored = await client.restoreSession()

        guard case .signedIn = restored else { return XCTFail("expected a live session") }
        XCTAssertEqual(storage.record?.token, "nrt_rt-1")
        let sent = StubServer.requests(to: "/auth/refresh").first?.json()
        XCTAssertEqual(sent?["refresh_token"] as? String, "nrt_rt-0",
                       "the refresh token travels in the body, never in a cookie")
    }

    func testTwoConcurrentUnauthorisedRequestsShareOneRefresh() async {
        let storage = InMemorySessionStorage(seed: Fixtures.record())
        let client = makeClient(storage: storage)
        let unauthorised = Counter()
        StubServer.install { request in
            if request.path == "/auth/refresh" {
                return (200, Fixtures.authenticated(refreshToken: "nrt_rt-\(UUID().uuidString)"), [:])
            }
            // The first two calls to the API answer 401; both callers then
            // want a refresh at the same moment.
            return unauthorised.next() <= 2
                ? (401, Fixtures.problem("session_expired"), [:])
                : (200, Fixtures.json(["spaces": []]), [:])
        }

        async let first: [Space] = client.fetchSpaces()
        async let second: [Space] = client.fetchSpaces()
        let results = try? await [first, second]

        XCTAssertEqual(results?.count, 2)
        // Two refreshes in total: one because the app had no access token
        // at all, one shared by the two 401s. Not three, which is what a
        // client without single-flight would send — and what the server
        // would read as a replayed refresh token.
        XCTAssertEqual(StubServer.requests(to: "/auth/refresh").count, 2)
    }

    func testAReplayedRefreshTokenWipesTheSessionAndSaysWhy() async {
        let storage = InMemorySessionStorage(seed: Fixtures.record())
        let client = makeClient(storage: storage)
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (401, Fixtures.problem("auth_refresh_replay"), [:])
                : (401, Fixtures.problem("session_expired"), [:])
        }
        let reasons = ReasonBox()
        await client.onSessionLost { reasons.record($0) }

        _ = try? await client.fetchSpaces()

        XCTAssertNil(storage.record, "the Keychain item goes with the session")
        XCTAssertEqual(reasons.value, .securityRevoked)
        XCTAssertEqual(reasons.value?.message,
                       "You were signed out for security. Sign in again.")
    }

    func testANetworkErrorAtBootKeepsTheSession() async {
        let storage = InMemorySessionStorage(seed: Fixtures.record(refreshToken: "nrt_rt-keep"))
        let client = makeClient(storage: storage)
        StubServer.install { _ in (0, Data(), [:]) }  // no reply at all

        let restored = await client.restoreSession()

        guard case .offline(let summary) = restored else {
            return XCTFail("an unreachable server is not a sign-out")
        }
        XCTAssertEqual(summary.email, "olena@acme.example")
        XCTAssertEqual(storage.record?.token, "nrt_rt-keep")
        XCTAssertEqual(storage.deletes, 0)
    }

    func testAnExpiredStoredSessionIsDroppedWithoutAskingTheServer() async {
        let storage = InMemorySessionStorage(
            seed: Fixtures.record(refreshToken: "nrt_rt-old", expiresIn: -60))
        let client = makeClient(storage: storage)
        StubServer.install { _ in (200, Fixtures.authenticated(), [:]) }

        let restored = await client.restoreSession()

        XCTAssertEqual(restored, .signedOut)
        XCTAssertNil(storage.record)
        XCTAssertTrue(StubServer.requests.isEmpty, "nothing to ask about")
    }

    func testAnExpiredSessionSignsOutWithTheOrdinaryMessage() async {
        let storage = InMemorySessionStorage(seed: Fixtures.record())
        let client = makeClient(storage: storage)
        StubServer.install { _ in (401, Fixtures.problem("session_expired"), [:]) }
        let reasons = ReasonBox()
        await client.onSessionLost { reasons.record($0) }

        _ = try? await client.fetchSpaces()

        XCTAssertEqual(reasons.value, .expired)
        XCTAssertNil(storage.record)
    }

    // MARK: - Signing out

    func testLogoutSendsTheTokenAndClearsTheItem() async {
        let storage = InMemorySessionStorage(seed: Fixtures.record(refreshToken: "nrt_rt-bye"))
        let client = makeClient(storage: storage)
        StubServer.install { _ in (204, Data(), [:]) }

        await client.logout()

        XCTAssertEqual(StubServer.requests(to: "/auth/logout").first?.json()["refresh_token"] as? String,
                       "nrt_rt-bye")
        XCTAssertNil(storage.record)
    }

    func testLogoutClearsTheItemEvenWhenTheServerIsUnreachable() async {
        let storage = InMemorySessionStorage(seed: Fixtures.record())
        let client = makeClient(storage: storage)
        StubServer.install { _ in (0, Data(), [:]) }

        await client.logout()

        XCTAssertNil(storage.record, "signing out is something the person did, not a request")
    }

    // MARK: - The password that still lives here, during `dual`

    func testTheMigrationLeavesTheSavedPasswordAlone() {
        // IDX-I1 wrote this migration to delete the password vault. IOS-1
        // holds it back: during the dual-issuer period that password is
        // still how every pre-existing user signs in, so deleting it would
        // sign them out of their own phone in the release that was meant
        // to add email codes. The default `purgeCredentials` is a no-op,
        // and that default is the behaviour under test.
        let defaults = UserDefaults(suiteName: "migration-\(UUID().uuidString)")!
        var cookiePurges = 0

        let notice = SessionMigration.run(defaults: defaults, purgeCookies: {
            cookiePurges += 1
            return 1
        })

        XCTAssertNil(notice, "a purged cookie is not news worth a banner")
        XCTAssertEqual(cookiePurges, 1, "the cookie is still swept: nothing reads it")
    }

    func testTheSavedPasswordSurvivesTheMigrationInTheRealKeychain() throws {
        // The acceptance criterion the other way round from IDX-I1's:
        // against the real Keychain, a seeded password user still has
        // their password after the first launch of this build.
        //
        // `CredentialStore.save` needs enrolled biometry for
        // `.biometryCurrentSet`; where there is none — a plain simulator —
        // there is nothing to seed and nothing to assert.
        try XCTSkipUnless(Biometrics.name != nil, "no enrolled biometry on this device")
        defer { CredentialStore.delete() }
        try CredentialStore.save(email: "olena@acme.example", password: "hunter2")
        XCTAssertTrue(CredentialStore.hasSaved)

        SessionMigration.run(defaults: UserDefaults(suiteName: "migration-\(UUID().uuidString)")!,
                             purgeCookies: { 0 })

        XCTAssertTrue(CredentialStore.hasSaved,
                      "a Keycloak user's way in must survive the update that adds email codes")
    }

    func testTheOldCutOverStillWorksWhenA4A5TurnsItBackOn() {
        // The delete side is kept and kept tested, because IDX-A4/A5 turns
        // it on by changing one default. A migration nobody exercised for
        // two sprints is one nobody trusts on the day it matters.
        let defaults = UserDefaults(suiteName: "migration-\(UUID().uuidString)")!
        var credentialPurges = 0

        let first = SessionMigration.run(defaults: defaults,
                                         purgeCredentials: { credentialPurges += 1; return 1 },
                                         purgeCookies: { 0 })

        XCTAssertEqual(credentialPurges, 1)
        XCTAssertEqual(first, "Sign-in now uses a device session; your password is no longer stored on this phone.")

        let second = SessionMigration.run(defaults: defaults,
                                          purgeCredentials: { credentialPurges += 1; return 1 },
                                          purgeCookies: { 0 })
        XCTAssertNil(second, "the notice is shown once, not on every launch")
        XCTAssertEqual(credentialPurges, 1, "and the Keychain is not swept again")
    }

    func testAFreshInstallIsNotToldAboutAPasswordItNeverHad() {
        let defaults = UserDefaults(suiteName: "migration-\(UUID().uuidString)")!

        let notice = SessionMigration.run(defaults: defaults,
                                          purgeCredentials: { 0 },
                                          purgeCookies: { 0 })

        XCTAssertNil(notice)
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
                return (200, Fixtures.authenticated(refreshToken: "nrt_rt-1", expiresIn: 900), [:])
            case "/auth/refresh":
                return (200, Fixtures.authenticated(refreshToken: "nrt_rt-\(refreshes.next() + 1)"), [:])
            case "/auth/logout":
                return (204, Data(), [:])
            default:
                return (200, Fixtures.json(["spaces": []]), [:])
            }
        }

        // 1. Sign in: the item is created.
        _ = try await client.verifyEmailCode(challengeId: "c-1", code: "123456")
        XCTAssertEqual(storage.record?.token, "nrt_rt-1")

        // 2. A later launch, or an expired access token: the item is rotated.
        let restored = await client.restoreSession()
        guard case .signedIn = restored else { return XCTFail("expected a live session") }
        XCTAssertEqual(storage.record?.token, "nrt_rt-2")
        XCTAssertEqual(storage.record?.email, "olena@acme.example",
                       "rotation replaces the token, not who it belongs to")

        // 3. Sign out: the item is gone.
        await client.logout()
        XCTAssertNil(storage.record)
        let after = await client.restoreSession()
        XCTAssertEqual(after, .signedOut)
    }

    func testALongRecordingCostsExactlyOneRefresh() async throws {
        // A native session idles for thirty days, not thirty minutes, so
        // it arms no keepalive. A 45-minute recording followed by an
        // upload therefore looks like this: nothing at all while
        // recording, then one refresh because the access token expired,
        // then the upload. (The Keycloak half of `dual` does arm one —
        // `DualSessionTests`.)
        let storage = InMemorySessionStorage(seed: Fixtures.record())
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

    func testAnUploadRefreshesBeforeItStartsWhenTheTokenIsNearlySpent() async throws {
        // `expires_in: 60` — under the five-minute floor `submitJob` asks
        // for, so the upload must take a fresh token with it rather than
        // discover the expiry with the audio already on the wire.
        let storage = InMemorySessionStorage(seed: Fixtures.record())
        let client = makeClient(storage: storage)
        let refreshes = Counter()
        StubServer.install { request in
            if request.path == "/auth/refresh" {
                let n = refreshes.next()
                return (200, Fixtures.authenticated(accessToken: "at-\(n)", expiresIn: 60), [:])
            }
            return (200, Fixtures.json(["id": "job-1", "status": "queued"]), [:])
        }
        let recording = FileManager.default.temporaryDirectory
            .appending(path: "\(UUID().uuidString).flac")
        try Data("audio".utf8).write(to: recording)
        defer { try? FileManager.default.removeItem(at: recording) }

        _ = try await client.submitJob(fileURL: recording, contentType: "audio/flac",
                                       language: "auto", diarize: true)

        XCTAssertEqual(StubServer.requests(to: "/auth/refresh").count, 2,
                       "one to open the session, one because 60 s is not enough for an upload")
        XCTAssertEqual(StubServer.requests(to: "/asr/jobs").first?.headers["Authorization"],
                       "Bearer at-2")
    }

    func testTheKeycloakLoginShapeStillParses() throws {
        // `/auth/login` answers the three token fields and nothing else.
        // It must decode — and then be refused for having no refresh token,
        // which is a different failure with a different fix (IDX-A4).
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
