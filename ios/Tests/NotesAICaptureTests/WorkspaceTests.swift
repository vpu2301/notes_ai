import XCTest
@testable import NotesAICapture

/// IDX-I2 I2-01 — local state belongs to one identity in one workspace.
final class ScopedStateTests: XCTestCase {
    private var defaults: UserDefaults!
    private var suite: String!

    override func setUpWithError() throws {
        suite = "scoped-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite)
    }

    override func tearDownWithError() throws {
        defaults.removePersistentDomain(forName: suite)
    }

    private func capture(_ title: String) -> RecentCapture {
        RecentCapture(jobId: UUID().uuidString, title: title, createdAt: Date(),
                      status: .complete, noteId: nil, errorMessage: nil)
    }

    func testTwoWorkspacesDoNotSeeEachOthersMeetings() {
        let agency = StateScope(identityId: "id-1", tenantId: "t-agency")
        let client = StateScope(identityId: "id-1", tenantId: "t-client")

        RecentsStore(scope: agency, defaults: defaults).save([capture("Agency standup")])
        RecentsStore(scope: client, defaults: defaults).save([capture("Client review")])

        XCTAssertEqual(RecentsStore(scope: agency, defaults: defaults).load().map(\.title),
                       ["Agency standup"])
        XCTAssertEqual(RecentsStore(scope: client, defaults: defaults).load().map(\.title),
                       ["Client review"])
    }

    func testTwoIdentitiesDoNotSeeEachOthersMeetings() {
        let mine = StateScope(identityId: "id-1", tenantId: "t-1")
        let theirs = StateScope(identityId: "id-2", tenantId: "t-1")

        RecentsStore(scope: mine, defaults: defaults).save([capture("My one-to-one")])

        XCTAssertTrue(RecentsStore(scope: theirs, defaults: defaults).load().isEmpty,
                      "same workspace, different person: not their meeting")
    }

    func testAScopeIsNotAPrefixOfAnother() {
        // "id-1"/"t-1" and "id-1.t"/"1" would collide under naive
        // concatenation; the key is split on the separator, not matched.
        let a = StateScope(identityId: "id-1", tenantId: "t-1")
        RecentsStore(scope: a, defaults: defaults).save([capture("Mine")])

        let found = ScopedDefaults.allScopes(in: defaults)

        XCTAssertEqual(found, [a])
    }

    func testEveryScopeOnThePhoneCanBeListedAndRemoved() {
        let mine = StateScope(identityId: "id-1", tenantId: "t-1")
        let other = StateScope(identityId: "id-2", tenantId: "t-9")
        RecentsStore(scope: mine, defaults: defaults).save([capture("Mine")])
        RecentsStore(scope: other, defaults: defaults).save([capture("Theirs")])

        XCTAssertEqual(ScopedDefaults.allScopes(in: defaults), [mine, other])

        ScopedDefaults.removeAll(for: other, from: defaults)

        XCTAssertEqual(ScopedDefaults.allScopes(in: defaults), [mine])
        XCTAssertEqual(RecentsStore(scope: mine, defaults: defaults).load().count, 1,
                       "removing one account's data leaves the other's alone")
    }

    func testTheOldUnscopedMeetingsMoveToTheFirstIdentityThatSignsIn() throws {
        // What the app wrote before IDX-I2: one list, no owner.
        let legacy = try JSONEncoder().encode([capture("Before the update")])
        defaults.set(legacy, forKey: "recentCaptures")
        let scope = StateScope(identityId: "id-1", tenantId: "t-1")

        let moved = ScopedDefaults.migrateLegacy(into: scope, defaults: defaults)

        XCTAssertTrue(moved)
        XCTAssertEqual(RecentsStore(scope: scope, defaults: defaults).load().map(\.title),
                       ["Before the update"])
        XCTAssertNil(defaults.data(forKey: "recentCaptures"),
                     "the unscoped key is not left behind for the next identity to inherit")
    }

    func testTheMigrationRunsOnce() {
        let first = StateScope(identityId: "id-1", tenantId: "t-1")
        let second = StateScope(identityId: "id-2", tenantId: "t-2")
        defaults.set(try! JSONEncoder().encode([capture("Before")]), forKey: "recentCaptures")

        XCTAssertTrue(ScopedDefaults.migrateLegacy(into: first, defaults: defaults))
        XCTAssertFalse(ScopedDefaults.migrateLegacy(into: second, defaults: defaults),
                       "the second identity to sign in does not inherit the first one's meetings")
        XCTAssertTrue(RecentsStore(scope: second, defaults: defaults).load().isEmpty)
    }

    func testAFreshInstallHasNothingToMigrate() {
        let scope = StateScope(identityId: "id-1", tenantId: "t-1")
        XCTAssertFalse(ScopedDefaults.migrateLegacy(into: scope, defaults: defaults))
    }

    func testThereIsNoScopeWithoutBothHalves() {
        XCTAssertNil(StateScope.of(identityId: "", tenantId: "t-1"))
        XCTAssertNil(StateScope.of(identityId: "id-1", tenantId: nil))
        XCTAssertNil(StateScope.of(identityId: "id-1", tenantId: ""))
        XCTAssertNotNil(StateScope.of(identityId: "id-1", tenantId: "t-1"))
    }
}

/// IDX-I2 I2-02 — the workspace a request is scoped to.
final class WorkspaceTransportTests: XCTestCase {

    func testSwitchingPublishesTheNewTokenAndRemembersTheWorkspace() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.record())
        let client = makeClient(storage: storage)
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/auth/token":
                return (200, Fixtures.json([
                    "access_token": "at-other", "expires_in": 900,
                    "tenant_id": "t-other", "roles": ["member"],
                ]), [:])
            default:
                return (200, Fixtures.json(["spaces": []]), [:])
            }
        }
        _ = await client.restoreSession()

        let switched = try await client.switchWorkspace(to: "t-other")
        _ = try? await client.fetchSpaces()

        XCTAssertEqual(switched.tenantId, "t-other")
        XCTAssertEqual(StubServer.requests(to: "/auth/token").first?.json()["activate"] as? Bool, true)
        XCTAssertEqual(StubServer.requests(to: "/v1/spaces").last?.headers["Authorization"],
                       "Bearer at-other", "every request after the switch is scoped to the new tenant")
        XCTAssertEqual(storage.record?.lastTenantId, "t-other",
                       "the next launch comes back to the workspace the person chose")
        XCTAssertEqual(storage.record?.token, "nrt_rt-1", "switching rotates nothing")
    }

    func testAnUploadForAnotherWorkspaceBorrowsATokenWithoutMovingTheSession() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.record())
        let client = makeClient(storage: storage)
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(accessToken: "at-active"), [:])
            case "/auth/token":
                return (200, Fixtures.json([
                    "access_token": "at-borrowed", "expires_in": 900,
                    "tenant_id": "t-agency", "roles": ["member"],
                ]), [:])
            default:
                return (200, Fixtures.json(["id": "job-1", "status": "queued"]), [:])
            }
        }
        let recording = FileManager.default.temporaryDirectory
            .appending(path: "\(UUID().uuidString).flac")
        try Data("audio".utf8).write(to: recording)
        defer { try? FileManager.default.removeItem(at: recording) }

        _ = try await client.submitJob(fileURL: recording, contentType: "audio/flac",
                                       language: "auto", diarize: true, tenantId: "t-agency")

        XCTAssertEqual(StubServer.requests(to: "/auth/token").first?.json()["activate"] as? Bool, false,
                       "an upload must not move the session under the person's feet")
        XCTAssertEqual(StubServer.requests(to: "/asr/jobs").first?.headers["Authorization"],
                       "Bearer at-borrowed")
        // And the session is still where it was.
        _ = try? await client.fetchSpaces()
        XCTAssertEqual(StubServer.requests(to: "/v1/spaces").last?.headers["Authorization"],
                       "Bearer at-active")
    }

    func testAnUploadForTheActiveWorkspaceBorrowsNothing() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.record())
        let client = makeClient(storage: storage)
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (200, Fixtures.json(["id": "job-1", "status": "queued"]), [:])
        }
        let recording = FileManager.default.temporaryDirectory
            .appending(path: "\(UUID().uuidString).flac")
        try Data("audio".utf8).write(to: recording)
        defer { try? FileManager.default.removeItem(at: recording) }

        // The fixture's tenant is the one the session is already in.
        _ = try await client.submitJob(fileURL: recording, contentType: "audio/flac",
                                       language: "auto", diarize: true,
                                       tenantId: "11111111-1111-1111-1111-111111111111")

        XCTAssertTrue(StubServer.requests(to: "/auth/token").isEmpty)
    }

    func testABorrowedTokenThatIsRefusedDoesNotCostTheSession() async {
        let storage = InMemorySessionStorage(seed: Fixtures.record())
        let client = makeClient(storage: storage)
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/auth/token":
                return (200, Fixtures.json([
                    "access_token": "at-borrowed", "expires_in": 900,
                    "tenant_id": "t-gone", "roles": [],
                ]), [:])
            default:
                return (401, Fixtures.problem("not_a_member"), [:])
            }
        }
        let reasons = ReasonBox()
        await client.onSessionLost { reasons.record($0) }
        let recording = FileManager.default.temporaryDirectory
            .appending(path: "\(UUID().uuidString).flac")
        try? Data("audio".utf8).write(to: recording)
        defer { try? FileManager.default.removeItem(at: recording) }

        _ = try? await client.submitJob(fileURL: recording, contentType: "audio/flac",
                                        language: "auto", diarize: true, tenantId: "t-gone")

        XCTAssertNil(reasons.value, "a membership that is gone is not a session that is gone")
        XCTAssertNotNil(storage.record, "and the Keychain item stays")
        XCTAssertEqual(StubServer.requests(to: "/asr/jobs").count, 1,
                       "a borrowed token is not refreshed and retried")
    }

    func testTheWorkspaceListComesFromTheTenantsEndpoint() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (200, Fixtures.json(["items": [
                    ["id": "t-1", "name": "acme", "display_name": "Acme",
                     "slug": "acme", "status": "active", "is_active": true,
                     "logo_url": "", "my_role": "owner"],
                  ]]), [:])
        }

        let list = try await client.workspaces()

        XCTAssertEqual(list.map(\.id), ["t-1"])
        XCTAssertEqual(list.first?.title, "Acme")
        XCTAssertEqual(list.first?.roleLabel, "Owner")
    }

    func testSigningOutEverywhereElseStepsUpAndRetriesOnce() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
        let attempts = Counter()
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/auth/sessions/revoke-others":
                return attempts.next() == 1
                    ? (403, Fixtures.json(["code": "reauth_required", "detail": "prove it"]), [:])
                    : (200, Fixtures.json(["revoked": 2]), [:])
            default:
                return (404, Data(), [:])
            }
        }
        let prompts = Counter()
        await client.onReauthRequired {
            _ = prompts.next()
            return true
        }

        let revoked = try await client.revokeOtherSessions()

        XCTAssertEqual(revoked, 2)
        XCTAssertEqual(prompts.next() - 1, 1, "asked to confirm exactly once")
    }

    func testTheSessionListNamesThisPhone() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (200, Fixtures.json([[
                    "sid": "s-1", "client_type": "ios", "device_name": "", "user_agent": "",
                    "ip_last": "192.0.2.4", "created_at": "2026-09-01T10:00:00Z",
                    "last_used_at": "2026-09-06T09:00:00Z",
                    "last_authenticated_at": "2026-09-01T10:00:00Z", "current": true,
                  ]]), [:])
        }

        let sessions = try await client.sessions()

        XCTAssertEqual(sessions.first?.title, "iPhone")
        XCTAssertEqual(sessions.first?.symbol, "iphone")
        XCTAssertTrue(sessions.first?.current == true)
    }
}

/// IDX-I2 I2-04 (cut) — the seam that is left where invitations will go.
final class AppLinkTests: XCTestCase {

    func testAnInvitationLinkIsRecognised() {
        let link = AppState.AppLink(URL(string: "notesai://invite/abc123")!)
        XCTAssertEqual(link, .invite(token: "abc123"))
    }

    func testANoteLinkIsRecognised() {
        let link = AppState.AppLink(URL(string: "notesai://notes/n-1")!)
        XCTAssertEqual(link, .note(id: "n-1"))
    }

    func testTheOAuthCallbacksAreNotAppLinks() {
        // They are answered by the ASWebAuthenticationSession that started
        // them; anything that could route them here could replay them.
        XCTAssertNil(AppState.AppLink(URL(string: "notesai://oauth/callback?code=x")!))
        XCTAssertNil(AppState.AppLink(URL(string: "notesai://calendar/connected")!))
    }

    func testAnotherAppsSchemeIsIgnored() {
        XCTAssertNil(AppState.AppLink(URL(string: "https://notes.example/invite/abc")!))
        XCTAssertNil(AppState.AppLink(URL(string: "othernotes://invite/abc")!))
    }
}
