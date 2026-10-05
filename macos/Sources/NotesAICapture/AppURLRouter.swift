import Foundation

/// Where a `notesai://` URL goes. OAuth and calendar callbacks are intercepted before macOS; a link clicked in a mail client arrives here.
enum AppURL: Equatable {
    /// `notesai://invite/<token>` — an invitation to a workspace.
    case invite(token: String)
    /// `notesai://calendar/connected` — the server-side Google flow came back.
    case calendarConnected
    /// `notesai://oauth/callback?...` — an MCP sign-in came back.
    case oauthCallback(URL)

    static let scheme = "notesai"

    /// Parse a URL the system handed us, or nil if it is not ours. Strict: an unknown host is nil, never a guess.
    static func parse(_ url: URL) -> AppURL? {
        guard url.scheme?.lowercased() == scheme else { return nil }
        let path = url.path.split(separator: "/").map(String.init)
        switch url.host()?.lowercased() {
        case "invite":
            // notesai://invite/<token>, and notesai://invite?token=<token>
            let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?
                .queryItems?.first { $0.name == "token" }?.value
            guard let token = path.first ?? query, !token.isEmpty else { return nil }
            return .invite(token: token)
        case "calendar" where path.first == "connected":
            return .calendarConnected
        case "oauth" where path.first == "callback":
            return .oauthCallback(url)
        default:
            return nil
        }
    }
}
