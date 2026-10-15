import XCTest
@testable import NotesAICapture

/// Local state belongs to one identity in one workspace.
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
        // The legacy shape: one list, no owner.
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

/// The workspace a request is scoped to.
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

/// Meeting notes typed offline land in the workspace they were typed in (W1 I-1).
final class PendingMeetingSyncTests: XCTestCase {
    /// The fixture session's workspace.
    private let active = "11111111-1111-1111-1111-111111111111"

    private func note(_ capture: String, tenant: String) -> PendingMeetingNote {
        PendingMeetingNote(
            clientCaptureId: capture, noteId: nil, title: "Weekly", language: "auto",
            meetingType: "auto", startedAt: Date(timeIntervalSince1970: 1_700_000_000),
            text: "budget 40k", lineTimes: [:], calendar: nil,
            identityId: "22222222-2222-2222-2222-222222222222", tenantId: tenant,
            updatedAt: Date())
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
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(accessToken: "at-b"), [:])
            case "/auth/token":
                return (200, Fixtures.json([
                    "access_token": "at-a", "expires_in": 900,
                    "tenant_id": "t-a", "roles": ["member"],
                ]), [:])
            default:
                return Self.notes(request)
            }
        }
        _ = await client.restoreSession()
        // Typed in A, then the person switched to B (the session's workspace).
        PendingMeetingNotes.save(note("cap-a", tenant: "t-a"), in: dir)
        PendingMeetingNotes.save(note("cap-b", tenant: active), in: dir)

        let refused = await CaptureViewModel.syncPendingMeetingNotes(
            api: client, identityId: "22222222-2222-2222-2222-222222222222",
            skipping: nil, in: dir)

        let opened = StubServer.requests(to: "/v1/notes/meeting")
        let tokenFor = { (capture: String) in
            opened.first { $0.json()["client_capture_id"] as? String == capture }?
                .headers["Authorization"]
        }
        XCTAssertEqual(tokenFor("cap-b"), "Bearer at-b", "the open workspace uses the session's token")
        XCTAssertEqual(tokenFor("cap-a"), "Bearer at-a", "A's note is created in A, after the switch")
        let mint = StubServer.requests(to: "/auth/token").first?.json()
        XCTAssertEqual(mint?["tenant_id"] as? String, "t-a")
        XCTAssertEqual(mint?["activate"] as? Bool, false, "syncing must not move the session")
        XCTAssertEqual(StubServer.requests(to: "/v1/notes/n-cap-a").first?.headers["Authorization"],
                       "Bearer at-a", "read back in A too")
        XCTAssertTrue(refused.isEmpty)
        XCTAssertTrue(PendingMeetingNotes.all(in: dir).isEmpty, "both synced, both files gone")
    }

    @MainActor
    func testARefusedWorkspaceKeepsTheNoteAndReportsIt() async throws {
        let dir = FileManager.default.temporaryDirectory
            .appending(path: "meeting-sync-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/auth/token":
                return (403, Fixtures.problem("not_a_member"), [:])
            default:
                return Self.notes(request)
            }
        }
        _ = await client.restoreSession()
        PendingMeetingNotes.save(note("cap-a", tenant: "t-gone"), in: dir)

        let refused = await CaptureViewModel.syncPendingMeetingNotes(
            api: client, identityId: "22222222-2222-2222-2222-222222222222",
            skipping: nil, in: dir)

        XCTAssertEqual(refused.map(\.clientCaptureId), ["cap-a"])
        XCTAssertTrue(StubServer.requests(to: "/v1/notes/meeting").isEmpty,
                      "never created in the open workspace instead")
        XCTAssertNotNil(PendingMeetingNotes.load("cap-a", in: dir), "the typing stays on the phone")

        PendingMeetingNotes.retarget(refused[0], to: "t-personal", in: dir)
        XCTAssertEqual(PendingMeetingNotes.load("cap-a", in: dir)?.tenantId, "t-personal")
    }

    /// A dissolved workspace blocks the note in its own file; moving it clears the mark.
    @MainActor
    func testADissolvedWorkspaceBlocksTheNoteInItsFile() async throws {
        let dir = FileManager.default.temporaryDirectory
            .appending(path: "meeting-sync-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/auth/token":
                return (403, Fixtures.problem("tenant_dissolved"), [:])
            default:
                return Self.notes(request)
            }
        }
        _ = await client.restoreSession()
        PendingMeetingNotes.save(note("cap-a", tenant: "t-dissolved"), in: dir)

        let refused = await CaptureViewModel.syncPendingMeetingNotes(
            api: client, identityId: "22222222-2222-2222-2222-222222222222",
            skipping: nil, in: dir)

        XCTAssertEqual(refused.map(\.clientCaptureId), ["cap-a"])
        XCTAssertEqual(refused.first?.blockedReason, "tenant_dissolved")
        XCTAssertEqual(PendingMeetingNotes.load("cap-a", in: dir)?.blockedReason, "tenant_dissolved",
                       "the reason is written to the sidecar, not only held in memory")
        XCTAssertEqual(PendingMeetingNotes.load("cap-a", in: dir)?.text, "budget 40k", "the typing is untouched")

        PendingMeetingNotes.retarget(refused[0], to: "t-personal", in: dir)
        XCTAssertNil(PendingMeetingNotes.load("cap-a", in: dir)?.blockedReason, "moved = free to sync again")
    }

    /// A transient failure is not a refusal: the note is retried later, never marked blocked.
    @MainActor
    func testAnOutageDoesNotBlockTheNote() async throws {
        let dir = FileManager.default.temporaryDirectory
            .appending(path: "meeting-sync-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/auth/token":
                return (503, Fixtures.problem("try_again"), [:])
            default:
                return Self.notes(request)
            }
        }
        _ = await client.restoreSession()
        PendingMeetingNotes.save(note("cap-a", tenant: "t-a"), in: dir)

        let refused = await CaptureViewModel.syncPendingMeetingNotes(
            api: client, identityId: "22222222-2222-2222-2222-222222222222",
            skipping: nil, in: dir)

        XCTAssertTrue(refused.isEmpty)
        XCTAssertNil(PendingMeetingNotes.load("cap-a", in: dir)?.blockedReason)
    }
}

/// Roles and kinds the server may send before the app offers them (W1 I-3).
final class WorkspaceDecodingTests: XCTestCase {

    func testAGuestRoleAndAPersonalWorkspaceDecode() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh":
                return (200, Fixtures.authenticated(), [:])
            case "/tenants":
                return (200, Fixtures.json(["items": [
                    ["id": "t-p", "name": "olena", "display_name": "Olena's workspace",
                     "slug": "olena", "status": "active", "is_active": true,
                     "logo_url": "", "my_role": "owner", "kind": "personal"],
                    ["id": "t-g", "name": "globex", "display_name": "Globex",
                     "slug": "globex", "status": "active", "is_active": true,
                     "logo_url": "", "my_role": "guest", "kind": "team"],
                  ]]), [:])
            default:
                return (200, Fixtures.json(["items": [
                    ["user_sub": "s-1", "role": "guest", "status": "active",
                     "email": "g@example.com", "display_name": "G"],
                  ]]), [:])
            }
        }

        let list = try await client.workspaces()
        let members = try await client.tenantMembers(tenantId: "t-g")

        XCTAssertEqual(list.map(\.title), ["Personal", "Globex"], "Personal is a kind, not a name")
        XCTAssertTrue(list[0].isPersonal)
        XCTAssertEqual(list[1].roleLabel, "Guest")
        XCTAssertEqual(members.first?.role, "guest")
    }

    func testAnOlderServerWithoutKindStillDecodes() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
        StubServer.install { request in
            request.path == "/auth/refresh"
                ? (200, Fixtures.authenticated(), [:])
                : (200, Fixtures.json(["items": [
                    ["id": "t-1", "name": "acme", "display_name": "Acme",
                     "slug": "acme", "status": "active", "is_active": true,
                     "logo_url": "", "my_role": "member"],
                  ]]), [:])
        }

        let list = try await client.workspaces()

        XCTAssertNil(list.first?.kind)
        XCTAssertEqual(list.first?.title, "Acme")
    }
}

/// Links into the app: invitations and notes.
final class AppLinkTests: XCTestCase {

    func testAnInvitationLinkIsRecognised() {
        let link = AppState.AppLink(URL(string: "notesai://invite/abc123")!)
        XCTAssertEqual(link, .invite(token: "abc123"))
    }

    func testANoteLinkIsRecognised() {
        let link = AppState.AppLink(URL(string: "notesai://notes/n-1")!)
        XCTAssertEqual(link, .note(id: "n-1"))
    }

    func testANoteLinkCarriesItsWorkspace() {
        let link = AppState.AppLink(URL(string: "notesai://notes/n-1?ws=t-a")!)
        XCTAssertEqual(link, .note(id: "n-1", workspace: "t-a"))
    }

    func testTheOAuthCallbacksAreNotAppLinks() {
        // Answered by the ASWebAuthenticationSession that started them; routing them here could replay them.
        XCTAssertNil(AppState.AppLink(URL(string: "notesai://oauth/callback?code=x")!))
        XCTAssertNil(AppState.AppLink(URL(string: "notesai://calendar/connected")!))
    }

    func testAnotherAppsSchemeIsIgnored() {
        XCTAssertNil(AppState.AppLink(URL(string: "https://notes.example/invite/abc")!))
        XCTAssertNil(AppState.AppLink(URL(string: "othernotes://invite/abc")!))
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
        let storage = InMemorySessionStorage(seed: Fixtures.record())
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
        guard case .invite(let token)? = AppState.AppLink(URL(string: "notesai://invite/tok-1")!) else {
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
        XCTAssertEqual(storage.record?.lastTenantId, "t-sunrise")
        XCTAssertTrue(StubServer.requests(to: "/auth/token").isEmpty, "no second switch is minted")
    }

    func testAnInvitationForAnotherAddressGrantsNothing() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.record())
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
        XCTAssertEqual(storage.record?.lastTenantId, Fixtures.record().lastTenantId)
    }

    func testCreatingAWorkspaceThenSwitchingIntoIt() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
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
        let switched = try await client.switchWorkspace(to: created.id)

        let create = StubServer.requests(to: "/tenants").first
        XCTAssertEqual(create?.method, "POST")
        XCTAssertEqual(create?.json().keys.sorted(), ["name"], "the short form: a name and nothing else")
        XCTAssertEqual(created.title, "Sunrise Studio")
        XCTAssertEqual(created.myRole, "owner")
        XCTAssertEqual(switched.tenantId, "t-new")
        XCTAssertEqual(StubServer.requests(to: "/auth/token").first?.json()["tenant_id"] as? String, "t-new")
    }

    func testAnInvitationDecodesAndSaysWhenItWasNotSent() async throws {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
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
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
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
        let storage = InMemorySessionStorage(seed: Fixtures.record())
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
        XCTAssertEqual(storage.record?.lastTenantId, "t-personal")
    }

    func testSignUpFromAnInvitationNamesTheWorkspacesJoined() throws {
        var body = try JSONSerialization.jsonObject(with: Fixtures.authenticated(isNew: true)) as! [String: Any]
        body["joined_tenant_ids"] = ["t-sunrise"]

        let result = try JSONDecoder().decode(AuthResultDTO.self,
                                              from: JSONSerialization.data(withJSONObject: body)).result()

        guard case .authenticated(let session) = result else { return XCTFail("not signed in") }
        XCTAssertEqual(session.joinedTenantIds, ["t-sunrise"])
    }
}

/// Links into another workspace, sessions moved by the server, leave/dissolve/accept answers (IOS-2, IOS-6, IOS-7).
final class WorkspaceMoveTests: XCTestCase {
    private func workspace(_ id: String, kind: String = "team", role: String = "member") -> Workspace {
        Workspace(id: id, name: id, myRole: role, kind: kind)
    }

    func testANoteLinkSwitchesForAMemberAndSaysSoOtherwise() {
        let mine = [workspace("t-personal", kind: "personal", role: "owner"), workspace("t-acme")]
        XCTAssertEqual(AppState.route(linkWorkspace: "t-acme", active: "t-personal", workspaces: mine),
                       .switchTo(mine[1]))
        XCTAssertEqual(AppState.route(linkWorkspace: "t-other", active: "t-personal", workspaces: mine),
                       .notAMember)
        XCTAssertEqual(AppState.route(linkWorkspace: "t-personal", active: "t-personal", workspaces: mine), .open)
        XCTAssertEqual(AppState.route(linkWorkspace: nil, active: "t-personal", workspaces: mine), .open,
                       "no ?ws=: open here; a 404 then offers the switcher")
        XCTAssertFalse(AuthCopy.notAMember.isEmpty)
    }

    func testOnlyAChangedWorkspaceCountsAsAMove() {
        XCTAssertEqual(APIClient.movedTenant(stored: "t-a", refreshed: "t-personal"), "t-personal")
        XCTAssertNil(APIClient.movedTenant(stored: "t-a", refreshed: "t-a"))
        XCTAssertNil(APIClient.movedTenant(stored: nil, refreshed: "t-a"), "nothing stored: nothing to compare")
        XCTAssertNil(APIClient.movedTenant(stored: "t-a", refreshed: ""))
        XCTAssertEqual(AuthCopy.workspaceMoved("Personal"), "Switched to Personal.")
    }

    /// Left or removed elsewhere: the refresh lands in Personal. The app is told once, the Keychain follows,
    /// and a restore reports where the session is now rather than where it was.
    func testARefreshThatLandsElsewhereIsAdoptedAndReported() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.record())
        let client = makeClient(storage: storage)
        var moved = try JSONSerialization.jsonObject(with: Fixtures.authenticated()) as! [String: Any]
        moved["tenant_id"] = "t-personal"
        let body = try JSONSerialization.data(withJSONObject: moved)
        StubServer.install { request in
            request.path == "/auth/refresh" ? (200, body, [:]) : (200, Fixtures.json(["spaces": []]), [:])
        }
        let seen = MovedBox()
        await client.onTenantMoved { seen.record($0) }

        let restored = await client.restoreSession()
        _ = try? await client.fetchSpaces()

        guard case .signedIn(let summary) = restored else { return XCTFail("not signed in") }
        XCTAssertEqual(summary.lastTenantId, "t-personal")
        XCTAssertEqual(storage.record?.lastTenantId, "t-personal")
        XCTAssertEqual(seen.values, ["t-personal"])

        // The next refresh stays there: no second report.
        try await client.ensureFreshToken(minimum: 100_000)
        XCTAssertEqual(seen.values, ["t-personal"])
    }

    func testLeavingAnotherWorkspaceMovesNothing() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.record())
        let client = makeClient(storage: storage)
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh": return (200, Fixtures.authenticated(), [:])
            case "/tenants/t-other/members/me": return (200, Fixtures.json(["token": NSNull()]), [:])
            default: return (200, Fixtures.json(["spaces": []]), [:])
            }
        }
        _ = await client.restoreSession()

        let movedTo = try await client.leaveWorkspace(tenantId: "t-other")

        XCTAssertNil(movedTo)
        XCTAssertEqual(storage.record?.lastTenantId, "11111111-1111-1111-1111-111111111111")
        let tenant = await client.tenantId
        XCTAssertEqual(tenant, "11111111-1111-1111-1111-111111111111")
    }

    func testDissolvingTheOpenWorkspaceAdoptsPersonal() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.record())
        let client = makeClient(storage: storage)
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh": return (200, Fixtures.authenticated(), [:])
            case "/tenants/t-team/dissolve":
                return (202, Fixtures.json([
                    "status": "dissolved", "restore_until": "2026-11-12T10:00:00Z",
                    "token": ["access_token": "at-personal", "expires_in": 900,
                              "tenant_id": "t-personal", "roles": ["owner"]],
                ]), [:])
            default: return (200, Fixtures.json(["spaces": []]), [:])
            }
        }
        _ = await client.restoreSession()

        let result = try await client.dissolveWorkspace(tenantId: "t-team", confirmName: "Team")
        _ = try? await client.fetchSpaces()

        XCTAssertEqual(result.status, "dissolved")
        XCTAssertEqual(StubServer.requests(to: "/tenants/t-team/dissolve").first?.json()["confirm_name"] as? String,
                       "Team")
        XCTAssertEqual(storage.record?.lastTenantId, "t-personal")
        XCTAssertEqual(StubServer.requests(to: "/v1/spaces").last?.headers["Authorization"], "Bearer at-personal")
    }

    /// A Keycloak-era session cannot be switched: the server accepts but sends no token; nothing moves.
    func testAnAcceptWithoutATokenMovesNothing() async throws {
        let storage = InMemorySessionStorage(seed: Fixtures.record())
        let client = makeClient(storage: storage)
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh": return (200, Fixtures.authenticated(), [:])
            case "/auth/invitations/inv-1/accept":
                return (200, Fixtures.json(["tenant_id": "t-sunrise", "role": "member", "token": NSNull()]), [:])
            default: return (200, Fixtures.json([:]), [:])
            }
        }
        _ = await client.restoreSession()

        let accepted = try await client.acceptInvitation(id: "inv-1")

        XCTAssertEqual(accepted.tenantId, "t-sunrise")
        XCTAssertNil(accepted.token)
        XCTAssertEqual(storage.record?.lastTenantId, "11111111-1111-1111-1111-111111111111")
    }

    func testPastedAddressesAreInvitedOnceEach() {
        let pasted = "anna@client.com, Tom <tom@client.com>;\nanna@client.com\tnot-an-address  lee@x.io"
        XCTAssertEqual(InviteAddresses.split(pasted), ["anna@client.com", "tom@client.com", "lee@x.io"])
        XCTAssertTrue(InviteAddresses.split("  ").isEmpty)
    }

    func testTheNoteInvitationNamesItsNote() throws {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let lookup = try decoder.decode(InvitationLookup.self, from: Data("""
        {"workspace_name":"Acme","inviter_display":"Anna","role":"guest","email_masked":"t•••@client.com",
         "expires_at":"2026-10-20T10:00:00Z","note_title":"Q4 plan"}
        """.utf8))
        XCTAssertEqual(lookup.noteTitle, "Q4 plan")
        XCTAssertEqual(WorkspaceRoles.label(lookup.role), "Guest")
    }
}

/// What the stub's `@Sendable` handler saw.
final class MovedBox: @unchecked Sendable {
    private let lock = NSLock()
    private var seen: [String] = []

    func record(_ value: String) {
        lock.lock(); defer { lock.unlock() }
        seen.append(value)
    }

    var values: [String] {
        lock.lock(); defer { lock.unlock() }
        return seen
    }
}
