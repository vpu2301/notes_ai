import Foundation

// MARK: - Workspace invitations (W2, auth-service)
//
// Wire shapes of `/tenants/{id}/invitations` and `/auth/invitations`. The token
// types differ between the apps, so the accept/leave answers live in each `Models.swift`.

/// `InvitationOut` — one invitation as the workspace's owners and admins see it.
struct Invitation: Decodable, Equatable, Identifiable, Sendable {
    let id: String
    let email: String
    let role: String
    let status: String
    let expiresAt: Date
    let sentCount: Int
    let lastSentAt: Date?
    let invitedByDisplay: String?
    let createdAt: Date
    /// Create and resend only: "sent", or "queued_failed" when the mail relay was down.
    let delivery: String?

    enum CodingKeys: String, CodingKey {
        case id, email, role, status, delivery
        case expiresAt = "expires_at"
        case sentCount = "sent_count"
        case lastSentAt = "last_sent_at"
        case invitedByDisplay = "invited_by_display"
        case createdAt = "created_at"
    }

    /// The row exists but no mail went out: the list offers "Not sent — Resend".
    var notSent: Bool { delivery == "queued_failed" || sentCount == 0 }
}

struct InvitationList: Decodable, Sendable {
    let items: [Invitation]
}

/// `GET /auth/invitations/{token}` — all the link reveals: never the full address.
struct InvitationLookup: Decodable, Equatable, Sendable {
    let workspaceName: String
    let inviterDisplay: String
    let role: String
    let emailMasked: String
    let expiresAt: Date
    let noteTitle: String?

    enum CodingKeys: String, CodingKey {
        case role
        case workspaceName = "workspace_name"
        case inviterDisplay = "inviter_display"
        case emailMasked = "email_masked"
        case expiresAt = "expires_at"
        case noteTitle = "note_title"
    }
}

/// `GET /auth/invitations` — an open invitation addressed to the signed-in person.
struct MyInvitation: Decodable, Equatable, Identifiable, Sendable {
    let id: String
    let workspaceName: String
    let inviterDisplay: String
    let role: String
    let expiresAt: Date

    enum CodingKeys: String, CodingKey {
        case id, role
        case workspaceName = "workspace_name"
        case inviterDisplay = "inviter_display"
        case expiresAt = "expires_at"
    }
}

struct MyInvitationList: Decodable, Sendable {
    let items: [MyInvitation]
}

/// `seat_meter` on the roster: display only, nothing is blocked on it.
struct SeatMeter: Decodable, Equatable, Sendable {
    let active: Int
    let limit: Int?
}

/// `POST /tenants/{id}/dissolve` — 202; the runbook can restore it until `restoreUntil`.
struct DissolveResult: Decodable, Sendable {
    let status: String
    let restoreUntil: Date?

    enum CodingKeys: String, CodingKey {
        case status
        case restoreUntil = "restore_until"
    }
}

/// The roles an invitation may carry, and how a role reads in a sentence.
enum WorkspaceRoles {
    /// Offered when inviting or changing a role; `owner` and `guest` are not.
    static let invitable = ["member", "admin", "viewer"]

    static func label(_ role: String) -> String {
        switch role {
        case "owner": return "Owner"
        case "admin": return "Admin"
        case "viewer": return "Viewer"
        case "guest": return "Guest"
        case "assistant": return "Assistant"
        default: return "Member"
        }
    }

    /// "as a member", "as an admin".
    static func asPhrase(_ role: String) -> String {
        let word = label(role).lowercased()
        return (word.first.map { "aeiou".contains($0) } ?? false) ? "as an \(word)" : "as a \(word)"
    }
}

/// What the invitation landing sheet shows (`notesai://invite/<token>`).
enum InvitationLandingState: Equatable, Sendable {
    case loading
    /// Unknown, revoked, expired or already accepted: the server answers one 404 for all.
    case invalid
    case ready(InvitationLookup)
    case joining(InvitationLookup)
    /// Signed in as another address: nothing was granted.
    case mismatch(InvitationLookup, signedInAs: String)
    case failed(InvitationLookup?, message: String)

    var lookup: InvitationLookup? {
        switch self {
        case .ready(let l), .joining(let l), .mismatch(let l, _): return l
        case .failed(let l, _): return l
        case .loading, .invalid: return nil
        }
    }
}

/// An invitation link the app is handling; the token is kept in memory only.
struct InvitationLanding: Identifiable, Equatable, Sendable {
    let token: String
    var state: InvitationLandingState = .loading

    var id: String { token }
}
