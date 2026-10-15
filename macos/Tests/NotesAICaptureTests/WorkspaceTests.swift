import XCTest
@testable import NotesAICapture

/// Local state belongs to an identity and a workspace, and a workspace is something the server decides you may be in.
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
        // What an older Mac has on disk: one unscoped key.
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

    func testANoteLinkCarriesItsWorkspace() {
        XCTAssertEqual(AppURL.parse(URL(string: "notesai://notes/n-1?ws=tenant-a")!),
                       .note(id: "n-1", workspace: "tenant-a"))
        XCTAssertEqual(AppURL.parse(URL(string: "notesai://notes/n-1")!),
                       .note(id: "n-1", workspace: nil))
        XCTAssertNil(AppURL.parse(URL(string: "notesai://notes")!), "a link with no note")
    }

    func testAnythingElseIsIgnoredRatherThanGuessedAt() {
        XCTAssertNil(AppURL.parse(URL(string: "https://example.com/invite/abc")!))
        XCTAssertNil(AppURL.parse(URL(string: "notesai://unknown/thing")!))
        XCTAssertNil(AppURL.parse(URL(string: "notesai://invite")!), "a link with no token")
        XCTAssertNil(AppURL.parse(URL(string: "notesai://invite/")!))
    }
}

// MARK: - Workspace-scoped tokens

/// `POST /auth/token`, from the client's side.
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

// MARK: - Offline meeting notes land in their workspace (W1 M-1)

final class PendingMeetingSyncTests: XCTestCase {
    /// The fixture session's workspace.
    private let active = "11111111-1111-1111-1111-111111111111"
    private let identity = "22222222-2222-2222-2222-222222222222"

    private func note(_ capture: String, tenant: String) -> PendingMeetingNote {
        PendingMeetingNote(
            clientCaptureId: capture, noteId: nil, title: "Weekly", language: "auto",
            meetingType: "auto", startedAt: Date(timeIntervalSince1970: 1_700_000_000),
            text: "budget 40k", lineTimes: [:], calendar: nil,
            identityId: identity, tenantId: tenant, updatedAt: Date())
    }

    /// A note server: the meeting is opened, read back, written, timed.
    private static func notes(_ request: StubServer.Recorded) -> (Int, Data, [String: String]) {
        if request.path == "/v1/notes/meeting" {
            let capture = request.json()["client_capture_id"] as? String ?? "x"
            return (201, Fixtures.json([
                "id": "n-\(capture)", "code": "NOTE-1", "version_number": 1,
                "template_id": "tpl-1", "state": "recording",
            ]), [:])
        }
        if request.path.hasSuffix("/draft") {
            return (200, Fixtures.json(["version_number": 2]), [:])
        }
        if request.path.hasSuffix("/timing") {
            return (200, Fixtures.json([:]), [:])
        }
        let id = request.path.split(separator: "/").last.map(String.init) ?? ""
        return (200, Fixtures.json([
            "id": id, "code": "NOTE-1", "status": "draft", "current_version_number": 1,
            "title": "Weekly", "created_at": "2026-10-01T10:00:00Z",
            "updated_at": "2026-10-01T10:00:00Z",
            "content": ["template_id": "tpl-1", "template_schema_version": 1, "sections": []],
        ]), [:])
    }

    @MainActor
    func testEachNoteIsCreatedWithItsOwnWorkspacesToken() async throws {
        let dir = FileManager.default.temporaryDirectory
            .appending(path: "meeting-sync-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(accessToken: "at-b"), [:])
            case "/auth/token":
                return (200, Fixtures.json([
                    "access_token": "at-a", "expires_in": 900,
                    "tenant_id": "tenant-a", "roles": ["member"],
                ]), [:])
            default:
                return Self.notes(request)
            }
        }
        _ = await client.restoreSession()
        // Typed in A, then the person switched to B (the session's workspace).
        PendingMeetingNotes.save(note("cap-a", tenant: "tenant-a"), in: dir)
        PendingMeetingNotes.save(note("cap-b", tenant: active), in: dir)

        let refused = await CaptureViewModel.syncPendingMeetingNotes(
            api: client, identityId: identity, skipping: nil, in: dir)

        let opened = StubServer.requests(to: "/v1/notes/meeting")
        let tokenFor = { (capture: String) in
            opened.first { $0.json()["client_capture_id"] as? String == capture }?
                .headers["Authorization"]
        }
        XCTAssertEqual(tokenFor("cap-b"), "Bearer at-b", "the active workspace uses the session's token")
        XCTAssertEqual(tokenFor("cap-a"), "Bearer at-a", "A's note is created in A, after the switch")
        let mint = StubServer.requests(to: "/auth/token")
        XCTAssertEqual(mint.count, 1, "one borrowed token serves every request for A")
        XCTAssertEqual(mint.first?.json()["activate"] as? Bool, false, "syncing must not move the session")
        XCTAssertTrue(refused.isEmpty)
        XCTAssertTrue(PendingMeetingNotes.all(in: dir).isEmpty, "both synced, both files gone")
    }

    @MainActor
    func testARefusedWorkspaceKeepsTheNoteAndReportsIt() async throws {
        let dir = FileManager.default.temporaryDirectory
            .appending(path: "meeting-sync-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/auth/token":
                return (403, Fixtures.json(["code": "not_a_member", "detail": "no"]), [:])
            default:
                return Self.notes(request)
            }
        }
        _ = await client.restoreSession()
        PendingMeetingNotes.save(note("cap-a", tenant: "tenant-gone"), in: dir)

        let refused = await CaptureViewModel.syncPendingMeetingNotes(
            api: client, identityId: identity, skipping: nil, in: dir)

        XCTAssertEqual(refused.map(\.clientCaptureId), ["cap-a"])
        XCTAssertTrue(StubServer.requests(to: "/v1/notes/meeting").isEmpty,
                      "never created in the active workspace instead")
        XCTAssertNotNil(PendingMeetingNotes.load("cap-a", in: dir), "the typing stays on this Mac")
    }
}

// MARK: - Roles and kinds the server may send before the app offers them (W1)

final class WorkspaceDecodingTests: XCTestCase {

    func testAGuestRoleAndAPersonalWorkspaceDecode() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/tenants":
                return (200, Fixtures.json(["items": [
                    ["id": "t-p", "name": "olena", "display_name": "Olena's workspace",
                     "my_role": "owner", "kind": "personal"],
                    ["id": "t-g", "name": "globex", "display_name": "Globex",
                     "my_role": "guest", "kind": "team"],
                  ]]), [:])
            default:
                return (200, Fixtures.json(["items": [
                    ["user_sub": "s-1", "role": "guest", "status": "active",
                     "email": "g@example.com", "display_name": "G"],
                  ]]), [:])
            }
        }
        _ = await client.restoreSession()

        let list = try await client.workspaces()
        let members = try await client.tenantMembers(tenantId: "t-g")

        XCTAssertEqual(list.map(\.title), ["Personal", "Globex"], "Personal is a kind, not a name")
        XCTAssertTrue(list[0].isPersonal)
        XCTAssertEqual(list[1].myRole, "guest")
        XCTAssertFalse(list[1].canManageMembers)
        XCTAssertEqual(members.first?.role, "guest")
    }

    func testAnOlderServerWithoutKindStillDecodes() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (200, Fixtures.json(["items": [
                    ["id": "t-1", "name": "acme", "display_name": "Acme", "my_role": "member"],
                  ]]), [:])
        }
        _ = await client.restoreSession()

        let list = try await client.workspaces()

        XCTAssertNil(list.first?.kind)
        XCTAssertEqual(list.first?.title, "Acme")
    }
}

/// Creating a workspace, inviting, and joining one (W2).
final class InvitationTests: XCTestCase {

    private static let invitationOut: [String: Any] = [
        "id": "inv-1", "email": "tom@client.example", "role": "member", "status": "pending",
        "expires_at": "2026-10-27T10:00:00Z", "sent_count": 0, "last_sent_at": NSNull(),
        "invited_by_display": "Olena", "created_at": "2026-10-13T10:00:00.123Z",
        "delivery": "queued_failed",
    ]

    func testAnInvitationLinkIsLookedUpThenAcceptedAndTheTokenAdopted() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.storedSession())
        let client = makeClient(storage: storage)
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/auth/invitations/tok-1":
                return (200, Fixtures.json([
                    "workspace_name": "Sunrise Studio", "inviter_display": "Anna",
                    "role": "member", "email_masked": "t•••@client.example",
                    "expires_at": "2026-10-27T10:00:00Z", "note_title": NSNull(),
                ]), [:])
            case "/auth/invitations/tok-1/accept":
                return (200, Fixtures.json([
                    "tenant_id": "t-sunrise", "role": "member",
                    "token": ["access_token": "at-sunrise", "expires_in": 900,
                              "tenant_id": "t-sunrise", "roles": ["member"]],
                ]), [:])
            default:
                return (200, Fixtures.json(["spaces": []]), [:])
            }
        }
        guard case .invite(let token)? = AppURL.parse(URL(string: "notesai://invite/tok-1")!) else {
            return XCTFail("not an invitation link")
        }

        let lookup = try await client.lookupInvitation(token: token)
        _ = await client.restoreSession()
        let accepted = try await client.acceptInvitation(token: token)
        _ = try? await client.fetchSpaces()

        XCTAssertEqual(lookup.workspaceName, "Sunrise Studio")
        XCTAssertEqual(lookup.emailMasked, "t•••@client.example")
        XCTAssertNil(StubServer.requests(to: "/auth/invitations/tok-1").first?.headers["Authorization"],
                     "the lookup is anonymous: it works before sign-in")
        XCTAssertEqual(accepted.tenantId, "t-sunrise")
        XCTAssertEqual(StubServer.requests(to: "/v1/spaces").last?.headers["Authorization"],
                       "Bearer at-sunrise", "the server switched the session; the app follows it")
        XCTAssertEqual(storage.session?.lastTenantId, "t-sunrise")
        XCTAssertTrue(StubServer.requests(to: "/auth/token").isEmpty, "no second switch is minted")
    }

    func testAnInvitationForAnotherAddressGrantsNothing() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.storedSession())
        let client = makeClient(storage: storage)
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(accessToken: "at-mine"), [:])
            case "/auth/invitations/tok-1/accept":
                return (403, Fixtures.json(["status": 403, "code": "invitation_email_mismatch",
                                            "detail": "different address"]), [:])
            default:
                return (200, Fixtures.json(["spaces": []]), [:])
            }
        }
        _ = await client.restoreSession()

        do {
            try await client.acceptInvitation(token: "tok-1")
            XCTFail("a mismatched address must not join")
        } catch let error as APIError {
            XCTAssertEqual(error.code, "invitation_email_mismatch")
        }
        _ = try? await client.fetchSpaces()

        XCTAssertEqual(StubServer.requests(to: "/v1/spaces").last?.headers["Authorization"], "Bearer at-mine")
        XCTAssertEqual(storage.session?.lastTenantId, Fixtures.storedSession().lastTenantId)
    }

    func testCreatingAWorkspaceThenSwitchingIntoIt() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/tenants":
                return (201, Fixtures.json([
                    "id": "t-new", "name": "sunrise-studio-x7", "display_name": "Sunrise Studio",
                    "slug": "sunrise-studio-x7", "status": "active", "is_active": true,
                    "my_role": "owner", "kind": "team",
                ]), [:])
            case "/auth/token":
                return (200, Fixtures.json([
                    "access_token": "at-new", "expires_in": 900,
                    "tenant_id": "t-new", "roles": ["owner"],
                ]), [:])
            default:
                return (200, Fixtures.json(["spaces": []]), [:])
            }
        }
        _ = await client.restoreSession()

        let created = try await client.createWorkspace(name: "Sunrise Studio")
        let switched = try await client.activateWorkspace(created.id)

        let create = StubServer.requests(to: "/tenants").first
        XCTAssertEqual(create?.method, "POST")
        XCTAssertEqual(create?.json().keys.sorted(), ["name"], "the short form: a name and nothing else")
        XCTAssertEqual(created.title, "Sunrise Studio")
        XCTAssertEqual(created.myRole, "owner")
        XCTAssertEqual(switched.tenantId, "t-new")
        XCTAssertEqual(StubServer.requests(to: "/auth/token").first?.json()["activate"] as? Bool, true)
    }

    func testAnInvitationDecodesAndSaysWhenItWasNotSent() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (201, Fixtures.json(Self.invitationOut), [:])
        }

        let invite = try await client.invite(tenantId: "t-1", email: "tom@client.example",
                                             role: "member", message: "")

        XCTAssertEqual(invite.id, "inv-1")
        XCTAssertEqual(invite.role, "member")
        XCTAssertEqual(invite.invitedByDisplay, "Olena")
        XCTAssertNil(invite.lastSentAt)
        XCTAssertEqual(invite.expiresAt, ISO8601DateFormatter().date(from: "2026-10-27T10:00:00Z"))
        XCTAssertTrue(invite.notSent, "the mail relay was down: the list offers Resend")
        let body = StubServer.requests(to: "/tenants/t-1/invitations").first?.json()
        XCTAssertEqual(body?["email"] as? String, "tom@client.example")
        XCTAssertNil(body?["message"], "an empty note is not sent")
    }

    func testTheRosterCarriesTheSeatMeterAndWhoLeft() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.storedSession()))
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (200, Fixtures.json([
                    "items": [
                        ["user_sub": "s-1", "role": "owner", "status": "active",
                         "email": "o@x.example", "display_name": "O", "left_at": NSNull()],
                        ["user_sub": "s-2", "role": "member", "status": "suspended",
                         "email": "m@x.example", "display_name": "M", "left_at": "2026-10-10T09:00:00Z"],
                    ],
                    "seat_meter": ["active": 1, "limit": 3],
                  ]), [:])
        }

        let roster = try await client.roster(tenantId: "t-1")

        XCTAssertEqual(roster.seatMeter, SeatMeter(active: 1, limit: 3))
        XCTAssertNil(roster.items[0].leftAt)
        XCTAssertNotNil(roster.items[1].leftAt)
    }

    func testLeavingAdoptsThePersonalWorkspacesToken() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.storedSession())
        let client = makeClient(storage: storage)
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/tenants/t-team/members/me":
                return (200, Fixtures.json([
                    "token": ["access_token": "at-personal", "expires_in": 900,
                              "tenant_id": "t-personal", "roles": ["owner"]],
                ]), [:])
            default:
                return (200, Fixtures.json(["spaces": []]), [:])
            }
        }
        _ = await client.restoreSession()

        try await client.leaveWorkspace(tenantId: "t-team")
        _ = try? await client.fetchSpaces()

        XCTAssertEqual(StubServer.requests(to: "/tenants/t-team/members/me").first?.method, "DELETE")
        XCTAssertEqual(StubServer.requests(to: "/v1/spaces").last?.headers["Authorization"], "Bearer at-personal")
        XCTAssertEqual(storage.session?.lastTenantId, "t-personal")
    }

    func testSignUpFromAnInvitationNamesTheWorkspacesJoined() async throws {
        let client = makeClient(storage: InMemorySessionStorage())
        StubServer.install { _ in
            var body = try! JSONSerialization.jsonObject(with: Fixtures.authenticated(isNew: true)) as! [String: Any]
            body["joined_tenant_ids"] = ["t-sunrise"]
            return (200, try! JSONSerialization.data(withJSONObject: body), [:])
        }

        let result = try await client.verifyEmailCode(challengeId: "c-1", code: "123456")

        guard case .authenticated(let session) = result else { return XCTFail("not signed in") }
        XCTAssertEqual(session.joinedTenantIds, ["t-sunrise"])
    }
}
