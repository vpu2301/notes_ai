import Foundation

// MARK: - Per-note roles, comments and presence (W3, note-service)
//
// Wire shapes of `/v1/notes/{id}/sharing` (v2 parts), `/comments` and `/presence`,
// and the small rules both apps apply to them. `SharingView` itself lives in each
// `Models.swift` next to the link types it carries.

/// What the signed-in person may do with one note (`my_level`). Ordered: each level includes the ones below.
enum NoteLevel: String, Codable, CaseIterable, Comparable, Sendable {
    case view, comment, edit, manage

    private var rank: Int {
        switch self {
        case .view: return 0
        case .comment: return 1
        case .edit: return 2
        case .manage: return 3
        }
    }

    static func < (lhs: NoteLevel, rhs: NoteLevel) -> Bool { lhs.rank < rhs.rank }

    var canComment: Bool { self >= .comment }
    var canEdit: Bool { self >= .edit }
    var canManage: Bool { self == .manage }

    /// The roles an author can hand out; `manage` is the author team's alone.
    static let grantable: [NoteLevel] = [.view, .comment, .edit]

    var label: String {
        switch self {
        case .view: return "Can view"
        case .comment: return "Can comment"
        case .edit: return "Can edit"
        case .manage: return "Full access"
        }
    }

    /// The line over a note the person cannot change. Nil when they can.
    var readOnlyLine: String? {
        switch self {
        case .view: return "You can view this note"
        case .comment: return "You can comment on this note"
        case .edit, .manage: return nil
        }
    }

    /// A server that predates W3 sends no level: the draft stays editable, as before.
    static func allowsEdit(_ level: NoteLevel?) -> Bool { level?.canEdit ?? true }

    /// Comments exist only on a server that sends a level.
    static func allowsComment(_ level: NoteLevel?) -> Bool { level?.canComment ?? false }

    /// An unknown value from a newer server reads as nothing rather than failing the whole note.
    static func decode(_ raw: String?) -> NoteLevel? { raw.flatMap(NoteLevel.init(rawValue:)) }
}

/// The notes list's filter (`GET /v1/notes/search?scope=`).
enum NoteScope: String, CaseIterable, Sendable {
    case all
    case mine
    case sharedWithMe = "shared_with_me"

    var label: String {
        switch self {
        case .all: return "All notes"
        case .mine: return "My notes"
        case .sharedWithMe: return "Shared with me"
        }
    }

    var symbol: String {
        switch self {
        case .all: return "doc.text"
        case .mine: return "person"
        case .sharedWithMe: return "person.2"
        }
    }
}

/// What the shell offers in the active workspace. A guest reaches only the notes they were given:
/// no recording, no new notes, no spaces, no members. Absent, not disabled.
struct WorkspaceCapabilities: Equatable, Sendable {
    /// The membership role in the active workspace; nil before `/tenants` answers.
    let role: String?

    var isGuest: Bool { role == "guest" }
    var canRecord: Bool { !isGuest }
    var canCreateNotes: Bool { !isGuest }
    var showsSpaces: Bool { !isGuest }
    var canInvite: Bool { !isGuest }
    /// A guest's list is "Shared with me" by definition, so there is nothing to choose.
    var scopes: [NoteScope] { isGuest ? [] : NoteScope.allCases }
}

/// One person who can open the note, and why.
struct NotePerson: Decodable, Equatable, Identifiable, Sendable {
    let sub: String
    let email: String
    let displayName: String
    let level: NoteLevel
    /// `author`, `collaborator` or `workspace_role`.
    let source: String
    /// Their role in the workspace (`guest` for someone invited to this note only).
    let membershipRole: String?
    /// The author may change this person's role or remove them.
    let canChange: Bool

    var id: String { sub }

    enum CodingKeys: String, CodingKey {
        case sub, email, level, source
        case displayName = "display_name"
        case membershipRole = "membership_role"
        case canChange = "can_change"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sub = try c.decode(String.self, forKey: .sub)
        email = (try? c.decodeIfPresent(String.self, forKey: .email)) ?? ""
        displayName = (try? c.decodeIfPresent(String.self, forKey: .displayName)) ?? ""
        level = NoteLevel.decode(try? c.decodeIfPresent(String.self, forKey: .level)) ?? .view
        source = (try? c.decodeIfPresent(String.self, forKey: .source)) ?? "collaborator"
        membershipRole = try? c.decodeIfPresent(String.self, forKey: .membershipRole)
        canChange = (try? c.decodeIfPresent(Bool.self, forKey: .canChange)) ?? false
    }

    var isAuthor: Bool { source == "author" }
    var isCollaborator: Bool { source == "collaborator" }
    var isGuest: Bool { membershipRole == "guest" }

    var title: String {
        let name = displayName.trimmingCharacters(in: .whitespaces)
        return name.isEmpty ? email : name
    }
}

/// An invitation to this note that nobody has accepted yet (manage only).
struct PendingNoteInvite: Decodable, Equatable, Identifiable, Sendable {
    let invitationId: String
    let emailMasked: String
    let noteRole: NoteLevel
    let expiresAt: Date?

    var id: String { invitationId }

    enum CodingKeys: String, CodingKey {
        case invitationId = "invitation_id"
        case emailMasked = "email_masked"
        case noteRole = "note_role"
        case expiresAt = "expires_at"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        invitationId = try c.decode(String.self, forKey: .invitationId)
        emailMasked = (try? c.decodeIfPresent(String.self, forKey: .emailMasked)) ?? ""
        noteRole = NoteLevel.decode(try? c.decodeIfPresent(String.self, forKey: .noteRole)) ?? .view
        expiresAt = try? c.decodeIfPresent(Date.self, forKey: .expiresAt)
    }
}

/// `POST /v1/notes/{id}/share` — 201 for someone already in the workspace.
struct ShareGrant: Decodable, Sendable {
    let kind: String
    let sharing: SharingView?
}

/// What an "Invite" did for one address.
enum ShareOutcome: Equatable, Sendable {
    /// A member: access now.
    case granted
    /// Not a member: an e-mailed invitation; they sign in to see the note.
    case invited
}

extension APIClient {
    /// Members get the role at once; anyone else (404 `not_a_member`) gets a guest invitation to this note.
    func shareOrInvite(noteId: String, email: String, role: NoteLevel,
                       message: String) async throws -> (ShareOutcome, SharingView?) {
        do {
            let grant = try await shareNote(id: noteId, email: email, role: role, message: message)
            return (.granted, grant.sharing)
        } catch let error as APIError where error.code == "not_a_member" {
            guard let tenantId else { throw error }
            _ = try await inviteToNote(tenantId: tenantId, email: email, noteId: noteId,
                                       noteRole: role, message: message)
            return (.invited, nil)
        }
    }
}

// MARK: - Comments

/// Where a comment hangs: the note, a section (`section_key`) or an item (`item_key`).
struct CommentAnchor: Hashable, Sendable {
    let kind: String
    let key: String?

    static let note = CommentAnchor(kind: "note", key: nil)
    static func section(_ key: String) -> CommentAnchor { CommentAnchor(kind: "section", key: key) }
    static func item(_ key: String) -> CommentAnchor { CommentAnchor(kind: "item", key: key) }

    var isNote: Bool { kind == "note" }
}

struct CommentAuthor: Decodable, Equatable, Sendable {
    let sub: String
    let displayName: String

    enum CodingKeys: String, CodingKey {
        case sub
        case displayName = "display_name"
    }
}

struct NoteComment: Decodable, Equatable, Identifiable, Sendable {
    let id: String
    let author: CommentAuthor
    let anchorKind: String
    let anchorKey: String?
    /// False when the section or item it was left on is gone from the current version.
    let anchorPresent: Bool
    let body: String
    let createdAt: Date
    let editedAt: Date?
    let resolvedAt: Date?
    let resolvedByDisplay: String?
    let canEdit: Bool
    let canResolve: Bool
    let canDelete: Bool

    enum CodingKeys: String, CodingKey {
        case id, author, body
        case anchorKind = "anchor_kind"
        case anchorKey = "anchor_key"
        case anchorPresent = "anchor_present"
        case createdAt = "created_at"
        case editedAt = "edited_at"
        case resolvedAt = "resolved_at"
        case resolvedByDisplay = "resolved_by_display"
        case canEdit = "can_edit"
        case canResolve = "can_resolve"
        case canDelete = "can_delete"
    }

    var anchor: CommentAnchor { CommentAnchor(kind: anchorKind, key: anchorKey) }
    var isResolved: Bool { resolvedAt != nil }
}

struct CommentList: Decodable, Sendable {
    let items: [NoteComment]
}

/// The comments on one anchor, in the order the anchors were first commented on; the note itself first.
struct CommentGroup: Identifiable, Equatable, Sendable {
    let anchor: CommentAnchor
    let comments: [NoteComment]
    /// The anchor no longer exists in the note.
    var removed: Bool { !anchor.isNote && comments.allSatisfy { !$0.anchorPresent } }

    var id: String { anchor.kind + ":" + (anchor.key ?? "") }

    static func make(_ comments: [NoteComment]) -> [CommentGroup] {
        var order: [CommentAnchor] = []
        var buckets: [CommentAnchor: [NoteComment]] = [:]
        for comment in comments.sorted(by: { $0.createdAt < $1.createdAt }) {
            if buckets[comment.anchor] == nil { order.append(comment.anchor) }
            buckets[comment.anchor, default: []].append(comment)
        }
        order.sort { $0.isNote && !$1.isNote }
        return order.map { CommentGroup(anchor: $0, comments: buckets[$0] ?? []) }
    }
}

/// Posting a comment: up to three tries for a dropped connection or a server error. A refusal
/// (4xx) is final — trying again cannot change it. The caller keeps the text until it is posted.
enum CommentRetry {
    static let attempts = 3

    static func run<T: Sendable>(attempts: Int = CommentRetry.attempts, pause: Duration = .seconds(2),
                                 _ post: () async throws -> T) async throws -> T {
        var attempt = 1
        while true {
            do {
                return try await post()
            } catch {
                guard attempt < attempts, isTransient(error) else { throw error }
                try? await Task.sleep(for: pause * attempt)
                attempt += 1
            }
        }
    }

    static func isTransient(_ error: Error) -> Bool {
        if error is CancellationError { return false }
        if let api = error as? APIError {
            guard let status = api.status else { return false }
            return status == 0 || status >= 500
        }
        // URLError and friends: the network, not the server.
        return true
    }
}

// MARK: - Presence

struct PresenceViewer: Decodable, Equatable, Identifiable, Sendable {
    let sub: String
    let displayName: String

    var id: String { sub }

    enum CodingKeys: String, CodingKey {
        case sub
        case displayName = "display_name"
    }
}

extension PresenceViewer {
    /// "Anna is viewing", "Anna and Tom are viewing", "Anna and 3 others are viewing".
    static func line(_ viewers: [PresenceViewer]) -> String {
        let names = viewers.map(\.displayName)
        switch names.count {
        case 0: return ""
        case 1: return "\(names[0]) is viewing"
        case 2: return "\(names[0]) and \(names[1]) are viewing"
        default: return "\(names[0]) and \(names.count - 1) others are viewing"
        }
    }
}

struct PresenceList: Decodable, Sendable {
    let viewers: [PresenceViewer]
}

// MARK: - Copy

/// What a refused collaboration call says. Everything else falls through to `AuthCopy`.
enum CollaborationCopy {
    static func message(for error: Error) -> String {
        switch (error as? APIError)?.code {
        case "insufficient_role":
            return "Your access to this note does not allow that. Ask its author for more."
        case "not_a_member":
            return "That person is not in this workspace."
        case "is_author":
            return "The note's author always has full access."
        case "personal_workspace":
            return "Notes in your personal workspace stay private. Move the note to a team workspace to share it with everyone."
        case "rate_limited":
            return "Too many comments in a short time. Try again in a few minutes."
        default:
            return AuthCopy.message(for: error)
        }
    }
}

// MARK: - The open note's comments and viewers

/// Comments and "who else is here" for one open note. The compose box keeps what was typed until
/// the server has it: three tries, then the text is handed back to copy. Nothing is stored on disk.
@MainActor
final class NoteCollaboration: ObservableObject {
    let noteId: String
    private let api: APIClient

    @Published private(set) var comments: [NoteComment] = []
    @Published private(set) var loaded = false
    @Published var showResolved = false
    @Published var error: String?
    @Published var draft = ""
    @Published var anchor = CommentAnchor.note
    @Published private(set) var sending = false
    /// A comment that could not be posted after three tries: shown back with Copy.
    @Published private(set) var unsent: String?
    @Published private(set) var busyId: String?
    /// Everyone else with the note open right now.
    @Published private(set) var viewers: [PresenceViewer] = []

    static let heartbeat: Duration = .seconds(20)

    init(noteId: String, api: APIClient) {
        self.noteId = noteId
        self.api = api
    }

    var openCount: Int { comments.filter { !$0.isResolved }.count }
    var resolvedCount: Int { comments.count - openCount }
    var groups: [CommentGroup] {
        CommentGroup.make(showResolved ? comments : comments.filter { !$0.isResolved })
    }

    func load() async {
        do {
            comments = try await api.comments(noteId: noteId)
            loaded = true
        } catch {
            // 404 = a server without comments; nothing to show, nothing to say.
            if (error as? APIError)?.status != 404 { self.error = CollaborationCopy.message(for: error) }
        }
    }

    /// Start a comment on a section or an item.
    func compose(on anchor: CommentAnchor) {
        self.anchor = anchor
        unsent = nil
    }

    func send() async {
        let body = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !body.isEmpty, !sending else { return }
        let anchor = self.anchor
        sending = true
        unsent = nil
        error = nil
        draft = ""
        defer { sending = false }
        do {
            let posted = try await CommentRetry.run {
                try await self.api.postComment(noteId: self.noteId, anchor: anchor, body: body)
            }
            comments.append(posted)
            if self.anchor == anchor { self.anchor = .note }
        } catch {
            // Handed back, never dropped: into the box when it is still empty, and on screen to copy.
            if draft.isEmpty { draft = body }
            unsent = body
            self.error = CollaborationCopy.message(for: error)
        }
    }

    func dismissUnsent() { unsent = nil }

    func edit(_ comment: NoteComment, body: String) async -> Bool {
        let text = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return false }
        return await act(comment) {
            try await self.api.editComment(noteId: self.noteId, commentId: comment.id, body: text)
        }
    }

    func setResolved(_ comment: NoteComment, _ resolved: Bool) async {
        _ = await act(comment) {
            try await self.api.setCommentResolved(noteId: self.noteId, commentId: comment.id, resolved: resolved)
        }
    }

    func delete(_ comment: NoteComment) async {
        busyId = comment.id
        error = nil
        defer { busyId = nil }
        do {
            try await api.deleteComment(noteId: noteId, commentId: comment.id)
            comments.removeAll { $0.id == comment.id }
        } catch {
            self.error = CollaborationCopy.message(for: error)
        }
    }

    private func act(_ comment: NoteComment, _ work: () async throws -> NoteComment) async -> Bool {
        busyId = comment.id
        error = nil
        defer { busyId = nil }
        do {
            let updated = try await work()
            if let index = comments.firstIndex(where: { $0.id == comment.id }) { comments[index] = updated }
            return true
        } catch {
            self.error = CollaborationCopy.message(for: error)
            return false
        }
    }

    /// Say "I am here" every 20 s and read who else is, until the calling task ends. Fail-open: no list on error.
    func stayPresent() async {
        while !Task.isCancelled {
            try? await api.heartbeat(noteId: noteId)
            viewers = (try? await api.presence(noteId: noteId)) ?? []
            try? await Task.sleep(for: Self.heartbeat)
        }
        viewers = []
    }
}
