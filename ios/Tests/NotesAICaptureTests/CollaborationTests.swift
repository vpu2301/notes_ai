import SwiftUI
import XCTest
@testable import NotesAICapture

/// The `/tenants` row type (`Workspace` here, `Tenant` on macOS).
private typealias WorkspaceRow = Workspace

/// W3: what a level allows, how the v2 wire shapes read, and what a guest is not offered.
final class NoteLevelTests: XCTestCase {
    func testOnlyEditAndManageMayChangeTheBody() {
        XCTAssertFalse(NoteLevel.view.canEdit)
        XCTAssertFalse(NoteLevel.comment.canEdit)
        XCTAssertTrue(NoteLevel.edit.canEdit)
        XCTAssertTrue(NoteLevel.manage.canEdit)
    }

    func testCommentingStartsAtComment() {
        XCTAssertFalse(NoteLevel.view.canComment)
        XCTAssertTrue(NoteLevel.comment.canComment)
        XCTAssertTrue(NoteLevel.edit.canComment)
        XCTAssertFalse(NoteLevel.edit.canManage)
        XCTAssertTrue(NoteLevel.manage.canManage)
    }

    func testAnOlderServerKeepsTheDraftEditableButOffersNoComments() {
        XCTAssertTrue(NoteLevel.allowsEdit(nil))
        XCTAssertFalse(NoteLevel.allowsComment(nil))
        XCTAssertFalse(NoteLevel.allowsEdit(.comment))
        XCTAssertTrue(NoteLevel.allowsComment(.comment))
    }

    func testReadOnlyLevelsSaySo() {
        XCTAssertEqual(NoteLevel.view.readOnlyLine, "You can view this note")
        XCTAssertEqual(NoteLevel.comment.readOnlyLine, "You can comment on this note")
        XCTAssertNil(NoteLevel.edit.readOnlyLine)
        XCTAssertEqual(NoteLevel.grantable, [.view, .comment, .edit], "manage is never handed out")
    }

    func testUnknownLevelReadsAsNothing() {
        XCTAssertNil(NoteLevel.decode("owner"))
        XCTAssertEqual(NoteLevel.decode("comment"), .comment)
    }
}

final class GuestCapabilityTests: XCTestCase {
    func testAGuestIsOfferedNoRecordingNotesSpacesOrInvites() {
        let guest = WorkspaceCapabilities(role: "guest")
        XCTAssertTrue(guest.isGuest)
        XCTAssertFalse(guest.canRecord)
        XCTAssertFalse(guest.canCreateNotes)
        XCTAssertFalse(guest.showsSpaces)
        XCTAssertFalse(guest.canInvite)
        XCTAssertTrue(guest.scopes.isEmpty, "a guest's list is Shared with me; nothing to pick")
    }

    func testMembersAndViewersKeepEverything() {
        for role in ["owner", "admin", "member", "viewer", nil] {
            let caps = WorkspaceCapabilities(role: role)
            XCTAssertFalse(caps.isGuest)
            XCTAssertTrue(caps.canRecord)
            XCTAssertTrue(caps.showsSpaces)
            XCTAssertEqual(caps.scopes, [.all, .mine, .sharedWithMe])
        }
    }

    func testWorkspaceSwitcherNamesAGuestWorkspace() throws {
        let json = #"{"id":"t1","name":"acme","display_name":"Acme Inc","my_role":"guest","kind":"team"}"#
        let workspace = try JSONDecoder().decode(WorkspaceRow.self, from: Data(json.utf8))
        XCTAssertTrue(workspace.isGuest)
        XCTAssertEqual(workspace.switcherTitle, "Guest in Acme Inc")
    }

    func testScopesGoOnTheWireAsTheServerNamesThem() {
        XCTAssertEqual(NoteScope.sharedWithMe.rawValue, "shared_with_me")
        XCTAssertEqual(NoteScope.mine.rawValue, "mine")
    }
}

final class CollaborationDecodingTests: XCTestCase {
    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try decoder.decode(type, from: Data(json.utf8))
    }

    func testEnvelopeCarriesLevelAndTranscriptGate() throws {
        let note = try decode(NoteEnvelope.self, """
        {"id":"n1","code":"NOTE-1","status":"draft","current_version_number":3,"title":"Call",
         "created_at":"2026-10-01T10:00:00Z","updated_at":"2026-10-01T10:05:00Z",
         "my_level":"comment","can_read_transcript":false,"source_job_id":null}
        """)
        XCTAssertEqual(note.myLevel, .comment)
        XCTAssertFalse(note.canReadTranscript)
        XCTAssertNil(note.sourceJobId)
    }

    func testAnOlderEnvelopeReadsAsBefore() throws {
        let note = try decode(NoteEnvelope.self, """
        {"id":"n1","code":"NOTE-1","status":"draft","current_version_number":1,"title":"Call",
         "created_at":"2026-10-01T10:00:00Z","updated_at":"2026-10-01T10:05:00Z","source_job_id":"j1"}
        """)
        XCTAssertNil(note.myLevel)
        XCTAssertTrue(note.canReadTranscript)
    }

    func testSharingViewV2() throws {
        let view = try decode(SharingView.self, """
        {"note_id":"n1","visibility":"workspace","can_manage":true,"can_delete":true,
         "shared_with":[{"sub":"s2","email":"anna@acme.test","display_name":"Anna"}],
         "public_link":null,"links":[],"my_level":"manage","transcript_shared":true,
         "workspace_kind":"team",
         "people":[
           {"sub":"s1","email":"me@acme.test","display_name":"Me","level":"manage","source":"author",
            "membership_role":"owner","can_change":false},
           {"sub":"s2","email":"anna@acme.test","display_name":"Anna","level":"comment","source":"collaborator",
            "membership_role":"member","can_change":true},
           {"sub":"s3","email":"tom@client.test","display_name":"","level":"view","source":"collaborator",
            "membership_role":"guest","can_change":true},
           {"sub":"s4","email":"bo@acme.test","display_name":"Bo","level":"edit","source":"workspace_role",
            "membership_role":"member","can_change":false}],
         "pending":[{"invitation_id":"i1","email_masked":"j***@client.test","note_role":"view",
                     "expires_at":"2026-10-20T00:00:00Z"}]}
        """)
        XCTAssertEqual(view.myLevel, .manage)
        XCTAssertTrue(view.transcriptShared)
        XCTAssertFalse(view.isPersonalWorkspace)
        XCTAssertEqual(view.people.count, 4)
        XCTAssertEqual(view.namedPeople.map(\.sub), ["s1", "s2", "s3"], "workspace roles fold into one row")
        XCTAssertTrue(view.people[0].isAuthor)
        XCTAssertTrue(view.people[2].isGuest)
        XCTAssertEqual(view.people[2].title, "tom@client.test")
        XCTAssertEqual(view.pending.first?.noteRole, .view)
        XCTAssertEqual(NoteAccess(view).sharedWithCount, 2, "collaborators only")
    }

    func testAnOlderSharingViewStillDecodes() throws {
        let view = try decode(SharingView.self, """
        {"note_id":"n1","visibility":"private","can_manage":true,"can_delete":true,
         "shared_with":[],"public_link":null}
        """)
        XCTAssertNil(view.myLevel)
        XCTAssertTrue(view.people.isEmpty)
        XCTAssertTrue(view.pending.isEmpty)
        XCTAssertFalse(view.transcriptShared)
    }

    func testSearchHitCarriesLevelAndCollaboratorCount() throws {
        let response = try decode(SearchResponse.self, """
        {"hits":[{"note_id":"n1","code":"NOTE-1","title":"Call","status":"draft","snippet":"",
                  "updated_at":"2026-10-01T10:05:00Z","visibility":"private","my_level":"view",
                  "collaborator_count":3,"has_public_link":false}],"next_cursor":null}
        """)
        XCTAssertEqual(response.hits.first?.myLevel, .view)
        XCTAssertEqual(response.hits.first?.access?.sharedWithCount, 3)
    }

    func testCommentsAndGroups() throws {
        let list = try decode(CommentList.self, """
        {"items":[
          {"id":"c2","author":{"sub":"s2","display_name":"Anna"},"anchor_kind":"section","anchor_key":"decisions",
           "anchor_present":true,"body":"Is this final?","created_at":"2026-10-01T10:02:00Z","edited_at":null,
           "resolved_at":null,"resolved_by_display":null,"can_edit":true,"can_resolve":false,"can_delete":true},
          {"id":"c1","author":{"sub":"s1","display_name":"Me"},"anchor_kind":"note","anchor_key":null,
           "anchor_present":true,"body":"Thanks all","created_at":"2026-10-01T10:03:00Z","edited_at":null,
           "resolved_at":"2026-10-01T11:00:00Z","resolved_by_display":"Me","can_edit":false,"can_resolve":true,
           "can_delete":true},
          {"id":"c3","author":{"sub":"s2","display_name":"Anna"},"anchor_kind":"item","anchor_key":"k9",
           "anchor_present":false,"body":"<b>gone</b>","created_at":"2026-10-01T10:04:00Z","edited_at":null,
           "resolved_at":null,"resolved_by_display":null,"can_edit":true,"can_resolve":false,"can_delete":true}]}
        """)
        XCTAssertEqual(list.items.count, 3)
        XCTAssertTrue(list.items[1].isResolved)
        XCTAssertEqual(list.items[2].body, "<b>gone</b>", "a body is text, kept as sent")

        let groups = CommentGroup.make(list.items)
        XCTAssertEqual(groups.map(\.anchor), [.note, .section("decisions"), .item("k9")], "the note itself first")
        XCTAssertFalse(groups[1].removed)
        XCTAssertTrue(groups[2].removed, "its line is gone: on a removed line")
    }

    func testPresence() throws {
        let list = try decode(PresenceList.self, """
        {"viewers":[{"sub":"s2","display_name":"Anna"},{"sub":"s3","display_name":"Tom"}]}
        """)
        XCTAssertEqual(PresenceViewer.line(list.viewers), "Anna and Tom are viewing")
        XCTAssertEqual(PresenceViewer.line(Array(list.viewers.prefix(1))), "Anna is viewing")
    }
}

final class CommentRetryTests: XCTestCase {
    private actor Counter {
        var calls = 0
        func hit() -> Int { calls += 1; return calls }
    }

    func testADroppedConnectionIsTriedThreeTimesThenHandedBack() async {
        let counter = Counter()
        do {
            _ = try await CommentRetry.run(pause: .milliseconds(1)) { () async throws -> Int in
                _ = await counter.hit()
                throw URLError(.notConnectedToInternet)
            }
            XCTFail("should have thrown")
        } catch {
            XCTAssertTrue(error is URLError)
        }
        let calls = await counter.calls
        XCTAssertEqual(calls, 3)
    }

    func testARefusalIsNotRetried() async {
        let counter = Counter()
        do {
            _ = try await CommentRetry.run(pause: .milliseconds(1)) { () async throws -> Int in
                _ = await counter.hit()
                throw APIError.http(status: 403, problem: nil)
            }
            XCTFail("should have thrown")
        } catch {}
        let calls = await counter.calls
        XCTAssertEqual(calls, 1)
    }

    func testASecondTryThatWorksIsTheAnswer() async throws {
        let counter = Counter()
        let value = try await CommentRetry.run(pause: .milliseconds(1)) { () async throws -> Int in
            let n = await counter.hit()
            if n < 2 { throw APIError.http(status: 503, problem: nil) }
            return n
        }
        XCTAssertEqual(value, 2)
    }
}

/// P3-3: the body is the server's to refuse, but a commenter's phone never asks; a lost race names the winner.
final class NoteLevelWriteTests: XCTestCase {
    private func envelope(level: String) -> Data {
        Fixtures.json([
            "id": "n1", "code": "NOTE-1", "status": "draft", "current_version_number": 3, "title": "Call",
            "created_at": "2026-10-01T10:00:00Z", "updated_at": "2026-10-01T10:05:00Z",
            "my_level": level, "can_read_transcript": false,
            "content": ["template_id": "tpl-1", "template_schema_version": 1, "sections": []],
        ])
    }

    @MainActor
    private func open(level: String, draftStatus: Int = 200) async -> NoteViewModel {
        let client = makeClient(storage: InMemorySessionStorage(seed: Fixtures.record()))
        let body = envelope(level: level)
        StubServer.install { request in
            switch request.path {
            case "/auth/refresh": return (200, Fixtures.authenticated(), [:])
            case "/v1/notes/n1": return (200, body, [:])
            case "/v1/notes/n1/draft":
                return draftStatus == 200
                    ? (200, Fixtures.json(["version_number": 4]), [:])
                    : (draftStatus, Fixtures.problem("version_conflict"), [:])
            case "/v1/notes/n1/versions":
                return (200, Fixtures.json([
                    ["id": "v4", "version_number": 4, "created_by": "s-anna", "created_by_display": "Anna",
                     "created_at": "2026-10-01T10:06:00Z", "is_amendment": false],
                    ["id": "v3", "version_number": 3, "created_by": "s-me", "created_by_display": "Me",
                     "created_at": "2026-10-01T10:05:00Z", "is_amendment": false],
                ]), [:])
            default: return (404, Fixtures.problem("not_found"), [:])
            }
        }
        _ = await client.restoreSession()
        let model = NoteViewModel(noteId: "n1", jobId: nil, api: client)
        await model.load()
        return model
    }

    @MainActor
    func testACommenterNeverReachesTheDraftWrite() async {
        let model = await open(level: "comment")
        XCTAssertFalse(model.editable)
        model.setSectionText("notes", "my edit")
        await model.flush()
        XCTAssertTrue(StubServer.requests(to: "/v1/notes/n1/draft").isEmpty, "no updateDraft for a commenter")
    }

    @MainActor
    func testAnEditorDoesWrite() async {
        let model = await open(level: "edit")
        XCTAssertTrue(model.editable)
        model.setSectionText("notes", "my edit")
        await model.flush()
        XCTAssertEqual(StubServer.requests(to: "/v1/notes/n1/draft").count, 1)
    }

    @MainActor
    func testALostRaceNamesWhoSavedAndKeepsMyText() async {
        let model = await open(level: "edit", draftStatus: 409)
        model.setSectionText("notes", "my edit")
        await model.flush()
        XCTAssertTrue(model.conflict)
        XCTAssertEqual(model.conflictBy, "Anna")
        XCTAssertEqual(model.conflictLine, "Anna saved a newer version of this note.")
        XCTAssertTrue(model.markdown().contains("my edit"), "what was typed is still there to copy")
    }

    func testTheNewestVersionsAuthorIsNamedAndAnOlderServerIsAnonymous() throws {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let old = try decoder.decode([NoteVersionSummary].self, from: Data("""
        [{"id":"v1","version_number":1,"created_by":"s","created_at":"2026-10-01T10:00:00Z","is_amendment":false}]
        """.utf8))
        XCTAssertNil(NoteViewModel.newestAuthor(old))
    }

    func testPresenceRunsOnlyWithALevelAndTheAppInFront() {
        XCTAssertTrue(PresenceGate(level: .view, phase: .active).present)
        XCTAssertFalse(PresenceGate(level: .view, phase: .inactive).present)
        XCTAssertFalse(PresenceGate(level: .view, phase: .background).present)
        XCTAssertFalse(PresenceGate(level: nil, phase: .active).present, "a server without W3 keeps no presence")
        XCTAssertNotEqual(PresenceGate(level: .edit, phase: .active), PresenceGate(level: .edit, phase: .inactive),
                          "a phase change restarts the task, so going inactive ends the heartbeat")
    }
}
