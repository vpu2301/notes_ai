import XCTest
@testable import NotesAICapture

/// IDX-M2 — local state belongs to an identity and a workspace, and a
/// workspace is something the server decides you may be in.
final class LocalStoreTests: XCTestCase {
    private var defaults: UserDefaults!
    private var suite: String!

    override func setUpWithError() throws {
        suite = "local-store-tests-\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite)
    }

    override func tearDownWithError() throws {
        defaults.removePersistentDomain(forName: suite)
    }

    private var store: LocalStore { LocalStore(defaults: defaults) }

    private func scope(_ identity: String, _ tenant: String) -> AppState.LocalScope {
        AppState.LocalScope(identityId: identity, tenantId: tenant)
    }

    private func recent(_ jobId: String) -> RecentCapture {
        RecentCapture(jobId: jobId, title: "Meeting \(jobId)", createdAt: Date(),
                      status: .complete, noteId: nil, errorMessage: nil)
    }

    func testAWorkspacesMeetingsAreNotVisibleInAnother() {
        let alpha = scope("ada", "tenant-a")
        let beta = scope("ada", "tenant-b")

        store.setRecents([recent("a-1"), recent("a-2")], for: alpha)
        store.setRecents([recent("b-1")], for: beta)

        XCTAssertEqual(store.recents(for: alpha).map(\.jobId), ["a-1", "a-2"])
        XCTAssertEqual(store.recents(for: beta).map(\.jobId), ["b-1"])
    }

    func testASecondAccountOnThisMacSeesItsOwnMeetings() {
        let ada = scope("ada", "tenant-a")
        let grace = scope("grace", "tenant-a")

        store.setRecents([recent("ada-1")], for: ada)

        XCTAssertTrue(store.recents(for: grace).isEmpty,
                      "the same workspace, a different person: not the same list")
    }

    func testTheLegacyListMovesUnderTheFirstIdentityOnce() throws {
        // What a pre-IDX-M2 Mac has on disk: one unscoped key.
        let legacy = try JSONEncoder().encode([recent("old-1"), recent("old-2")])
        defaults.set(legacy, forKey: AppState.Keys.recents)
        let ada = scope("ada", "tenant-a")

        XCTAssertTrue(store.migrateLegacyRecents(into: ada))
        XCTAssertEqual(store.recents(for: ada).map(\.jobId), ["old-1", "old-2"])
        XCTAssertNotNil(defaults.data(forKey: AppState.Keys.recents),
                        "the legacy key is copied, not moved — one release of overlap")

        // A second run changes nothing, including for a different identity.
        let grace = scope("grace", "tenant-a")
        XCTAssertFalse(store.migrateLegacyRecents(into: grace))
        XCTAssertTrue(store.recents(for: grace).isEmpty)
    }

    func testAMeetingCanBeFiledInAWorkspaceThatIsNotOnScreen() {
        let other = scope("ada", "tenant-b")

        store.addRecent(recent("late-arrival"), to: other)

        XCTAssertEqual(store.recents(for: other).map(\.jobId), ["late-arrival"])
    }

    func testTheRecentsListStaysBounded() {
        let ada = scope("ada", "tenant-a")
        for index in 0..<15 {
            store.addRecent(recent("job-\(index)"), to: ada)
        }
        XCTAssertEqual(store.recents(for: ada).count, 10)
        XCTAssertEqual(store.recents(for: ada).first?.jobId, "job-14")
    }

    func testRemovingOneAccountLeavesTheOtherAlone() throws {
        let pendingDirectory = FileManager.default.temporaryDirectory
            .appending(path: "pending-remove-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: pendingDirectory) }

        store.setRecents([recent("ada-1")], for: scope("ada", "tenant-a"))
        store.setRecents([recent("grace-1")], for: scope("grace", "tenant-a"))
        store.remember(identityId: "ada", email: "ada@example.com", tenantId: "tenant-a")
        store.remember(identityId: "grace", email: "grace@example.com", tenantId: "tenant-a")
        try keep(identity: "ada", in: pendingDirectory)
        try keep(identity: "grace", in: pendingDirectory)

        store.removeLocalData(identityId: "ada", pendingDirectory: pendingDirectory)

        XCTAssertTrue(store.recents(for: scope("ada", "tenant-a")).isEmpty)
        XCTAssertEqual(store.recents(for: scope("grace", "tenant-a")).map(\.jobId), ["grace-1"])
        XCTAssertEqual(store.knownIdentities.keys.sorted(), ["grace"])
        let kept = PendingCaptures.all(in: pendingDirectory)
        XCTAssertEqual(kept.map(\.info.identityId), ["grace"],
                       "only the account that was removed loses its recordings")
    }

    func testTheLastIdentityIsRememberedForAnExpiredSession() {
        store.remember(identityId: "ada", email: "ada@example.com", tenantId: "tenant-a")

        XCTAssertEqual(store.lastIdentity?.identityId, "ada")
        XCTAssertEqual(store.lastIdentity?.tenantId, "tenant-a")
        XCTAssertEqual(store.otherIdentities(besides: "ada").count, 0)
        XCTAssertEqual(store.otherIdentities(besides: "grace").map(\.email), ["ada@example.com"])
    }

    private func keep(identity: String, in directory: URL) throws {
        let source = FileManager.default.temporaryDirectory
            .appending(path: "\(UUID().uuidString).flac")
        try Data("audio".utf8).write(to: source)
        PendingCaptures.keep(source, info: PendingCapture.Info(
            title: "Meeting", language: "auto", diarize: true, recordedAt: Date(),
            identityId: identity, tenantId: "tenant-a"), in: directory)
    }
}

// MARK: - Deep links

final class AppURLTests: XCTestCase {
    func testAnInvitationLinkIsRecognisedInBothShapes() {
        XCTAssertEqual(AppURL.parse(URL(string: "notesai://invite/abc123")!),
                       .invite(token: "abc123"))
        XCTAssertEqual(AppURL.parse(URL(string: "notesai://invite?token=abc123")!),
                       .invite(token: "abc123"))
    }

    func testTheCallbacksTheAppAlreadyUsesStillParse() {
        XCTAssertEqual(AppURL.parse(URL(string: "notesai://calendar/connected")!),
                       .calendarConnected)
        let oauth = URL(string: "notesai://oauth/callback?code=1&state=2")!
        XCTAssertEqual(AppURL.parse(oauth), .oauthCallback(oauth))
    }

    func testAnythingElseIsIgnoredRatherThanGuessedAt() {
        XCTAssertNil(AppURL.parse(URL(string: "https://example.com/invite/abc")!))
        XCTAssertNil(AppURL.parse(URL(string: "notesai://unknown/thing")!))
        XCTAssertNil(AppURL.parse(URL(string: "notesai://invite")!), "a link with no token")
        XCTAssertNil(AppURL.parse(URL(string: "notesai://invite/")!))
    }
}

// MARK: - Workspace-scoped tokens

/// IDX-M2 — `POST /auth/token`, from the client's side.
final class WorkspaceTokenTests: XCTestCase {

    private func makeClient() -> APIClient {
        makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
    }

    private func installServer() {
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(accessToken: "at-active"), [:])
            case "/auth/token":
                let tenant = request.json()["tenant_id"] as? String ?? "?"
                return (200, Fixtures.json([
                    "access_token": "at-\(tenant)", "expires_in": 900,
                    "tenant_id": tenant, "roles": ["member"],
                ]), [:])
            default:
                return (200, Fixtures.json(["spaces": []]), [:])
            }
        }
    }

    func testActivatingSwitchesTheDefaultTokenAndRemembersTheChoice() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.storedSession())
        let client = makeClient(storage: storage)
        installServer()
        _ = await client.restoreSession()

        _ = try await client.activateWorkspace("tenant-b")
        _ = try await client.fetchSpaces()

        let ask = StubServer.requests(to: "/auth/token").first
        XCTAssertEqual(ask?.json()["activate"] as? Bool, true)
        XCTAssertEqual(StubServer.requests(to: "/v1/spaces").last?.headers["Authorization"],
                       "Bearer at-tenant-b", "the active token is the new workspace's")
        XCTAssertEqual(storage.session?.lastTenantId, "tenant-b",
                       "the next launch opens where the person left off")
    }

    func testBorrowingATokenDoesNotMoveTheSession() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.storedSession())
        let client = makeClient(storage: storage)
        installServer()
        _ = await client.restoreSession()

        let borrowed = try await client.token(for: "tenant-b")

        XCTAssertEqual(borrowed, "at-tenant-b")
        XCTAssertEqual(StubServer.requests(to: "/auth/token").first?.json()["activate"] as? Bool,
                       false)
        XCTAssertEqual(storage.session?.lastTenantId, "11111111-1111-1111-1111-111111111111")
    }

    func testABorrowedTokenIsMintedOnceAndReused() async throws {
        let client = makeClient()
        installServer()
        _ = await client.restoreSession()

        _ = try await client.token(for: "tenant-b")
        _ = try await client.token(for: "tenant-b")

        XCTAssertEqual(StubServer.requests(to: "/auth/token").count, 1)
    }

    func testARefusedWorkspaceReachesTheCallerWithItsCode() async {
        let client = makeClient()
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (403, Fixtures.json(["code": "membership_suspended", "detail": "no"]), [:])
        }
        _ = await client.restoreSession()

        do {
            _ = try await client.token(for: "tenant-b")
            XCTFail("a refused workspace is not a token")
        } catch let error as APIError {
            XCTAssertEqual(WorkspaceLoss(code: error.code), .suspended)
            XCTAssertEqual(AuthCopy.message(for: error), "Your membership is suspended.")
        } catch {
            XCTFail("unexpected \(error)")
        }
    }

    func testAWorkspaceRefusalDoesNotSignTheAppOut() async {
        let client = makeClient()
        let reasons = ReasonBox()
        await client.onSessionLost { reasons.record($0) }
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/auth/token":
                return (200, Fixtures.json([
                    "access_token": "at-stale", "expires_in": 900,
                    "tenant_id": "tenant-b", "roles": ["member"],
                ]), [:])
            default:
                // The borrowed token is refused, twice.
                return (401, Fixtures.problem("session_expired"), [:])
            }
        }
        _ = await client.restoreSession()

        _ = try? await client.jobStatus(id: "job-1", tenant: "tenant-b")

        XCTAssertNil(reasons.value,
                     "one workspace refusing a token is not the session ending")
    }

    func testTheSessionsListAndRevokeOthersUseTheStepUp() async throws {
        let client = makeClient()
        let asked = Counter()
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/auth/sessions":
                return (200, Fixtures.json([[
                    "sid": "s-1", "client_type": "macos", "device_name": "Mac",
                    "user_agent": "", "ip_last": "10.0.0.0/24",
                    "created_at": "2026-09-01T10:00:00Z",
                    "last_used_at": "2026-09-05T10:00:00Z",
                    "last_authenticated_at": "2026-09-05T10:00:00Z",
                    "current": true,
                ]]), [:])
            default:
                return asked.next() == 1
                    ? (403, Fixtures.json(["code": "reauth_required"]), [:])
                    : (200, Fixtures.json(["revoked": 2]), [:])
            }
        }
        let prompts = Counter()
        await client.onReauthRequired {
            _ = prompts.next()
            return true
        }

        let sessions = try await client.sessions()
        let revoked = try await client.revokeOtherSessions()

        XCTAssertEqual(sessions.first?.title, "Mac · this Mac")
        XCTAssertEqual(revoked, 2)
        XCTAssertEqual(prompts.next() - 1, 1, "asked to prove it once")
    }
}
