import Foundation

/// Where a `notesai://` URL goes.
///
/// The app already answers this scheme — the MCP OAuth callback and the
/// calendar return both come back on it — but never through the app
/// itself: `ASWebAuthenticationSession` and a loopback listener intercept
/// them before macOS does. A link somebody clicks in a mail client has no
/// such interceptor, so it arrives at the app, and until IDX-M2 there was
/// nothing here to receive it.
enum AppURL: Equatable {
    /// `notesai://invite/<token>` — an invitation to a workspace.
    case invite(token: String)
    /// `notesai://calendar/connected` — the server-side Google flow came back.
    case calendarConnected
    /// `notesai://oauth/callback?...` — an MCP sign-in came back.
    case oauthCallback(URL)

    static let scheme = "notesai"

    /// Parse a URL the system handed us, or nil if it is not ours.
    ///
    /// Deliberately strict: an unknown host is nil rather than a guess,
    /// because the one thing worse than ignoring a link is acting on the
    /// wrong reading of it.
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
