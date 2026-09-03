import AppKit
import Foundation
import SwiftUI

/// The calendar connections that live on the server (note-service, 0019
/// and 0020): which Google accounts and calendar links are connected,
/// their next days' events, and the connect / add-link / disconnect /
/// choose-calendars actions.
///
/// Connect opens Google's consent page in an `ASWebAuthenticationSession`;
/// note-service does the OAuth exchange and sends the browser back to
/// `notesai://calendar/connected`, which the session intercepts. Tokens
/// never touch this Mac — the same account then shows up in the web app.
@MainActor
final class GoogleCalendarService: ObservableObject {
    static let returnTo = "notesai://calendar/connected"

    /// nil until the first answer; false when the server has no Google client.
    @Published private(set) var available: Bool?
    /// The server takes calendar links (private iCal addresses; 0020) —
    /// the way in that needs no Google client at all.
    @Published private(set) var linkAvailable = false
    @Published private(set) var connections: [CalendarConnection] = []
    @Published private(set) var events: [UpcomingEvent] = []
    @Published private(set) var problems: [CalendarProblem] = []
    @Published private(set) var loading = false
    @Published private(set) var connecting = false
    /// The last refresh's failure, for the Connectors tab. The home page
    /// stays quiet about it — a stale list is better than a red banner.
    @Published private(set) var error: String?
    /// Calendars per connection, loaded on demand for the picker.
    @Published private(set) var calendars: [String: [RemoteCalendar]] = [:]
    @Published private(set) var calendarsLoading: Set<String> = []

    private let api: APIClient
    private var lastRefresh: Date?
    private var ticker: Task<Void, Never>?

    init(api: APIClient) {
        self.api = api
    }

    var isConnected: Bool { !connections.isEmpty }

    // MARK: - Reading

    /// Reload connections and events. Quiet refreshes within a minute of
    /// the last one are skipped — the home page asks on every appearance.
    func refresh(force: Bool = false) async {
        if !force, let last = lastRefresh, Date().timeIntervalSince(last) < 60 { return }
        loading = true
        defer { loading = false }
        do {
            async let connectionsTask = api.calendarConnections()
            async let eventsTask = api.upcomingEvents(days: 7)
            let (list, upcoming) = try await (connectionsTask, eventsTask)
            available = list.available
            linkAvailable = list.linkAvailable ?? false
            connections = list.connections
            events = upcoming.events
            problems = upcoming.problems
            error = nil
            lastRefresh = Date()
            startTicker()
        } catch APIError.notAuthenticated {
            reset()
        } catch let APIError.http(status, _) where status == 404 {
            // An older note-service without the calendar routes.
            available = false
        } catch {
            self.error = error.localizedDescription
            if available == nil { available = false }
        }
    }

    /// Every five minutes while signed in, so a meeting added from the
    /// phone shows up without a click.
    private func startTicker() {
        guard ticker == nil else { return }
        ticker = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(300))
                guard !Task.isCancelled, let self else { return }
                await self.refresh(force: true)
            }
        }
    }

    /// Signed out: forget everything (the next sign-in refreshes).
    func reset() {
        ticker?.cancel()
        ticker = nil
        lastRefresh = nil
        connections = []
        events = []
        problems = []
        calendars = [:]
        error = nil
    }

    // MARK: - Connecting

    /// Google sign-in in a sheet; on success the list refreshes. `loginHint`
    /// pre-selects an account (used by "Sign in again").
    func connect(loginHint: String? = nil) async {
        guard !connecting else { return }
        connecting = true
        defer { connecting = false }
        do {
            let url = try await api.startGoogleCalendarConnect(returnTo: Self.returnTo, loginHint: loginHint)
            let callback = try await BrowserSession.shared.run(url: url)
            let query = URLComponents(url: callback, resolvingAgainstBaseURL: false)?.queryItems ?? []
            let outcome = query.first { $0.name == "calendar" }?.value
            if outcome != "connected" {
                let reason = query.first { $0.name == "reason" }?.value ?? "unknown"
                error = Self.describe(reason: reason)
                return
            }
            error = nil
            await refresh(force: true)
        } catch MCPOAuth.Failure.cancelled {
            // The user closed the sheet; nothing to say.
        } catch {
            self.error = error.localizedDescription
        }
    }

    private static func describe(reason: String) -> String {
        switch reason {
        case "access_denied": return "Google sign-in was cancelled."
        case "no_refresh_token": return "Google did not grant offline access. Try again and approve every permission."
        case "not_configured": return "Google Calendar is not set up on the server."
        default: return "Couldn't connect Google Calendar (\(reason))."
        }
    }

    /// 0020: add a calendar link. The server fetches it before answering,
    /// so a wrong address fails right here. Returns the message to show,
    /// or nil when the calendar was added (and the list refreshed).
    func addLink(url: String) async -> String? {
        do {
            _ = try await api.connectCalendarLink(url: url.trimmingCharacters(in: .whitespacesAndNewlines), label: nil)
            error = nil
            await refresh(force: true)
            return nil
        } catch {
            return error.localizedDescription
        }
    }

    func disconnect(_ id: String) async {
        do {
            try await api.disconnectCalendar(id: id)
            connections.removeAll { $0.id == id }
            events.removeAll { $0.connectionId == id }
            problems.removeAll { $0.connectionId == id }
            calendars[id] = nil
            error = nil
        } catch {
            self.error = error.localizedDescription
        }
    }

    // MARK: - Calendars of one account

    func loadCalendars(for connectionId: String) async {
        guard !calendarsLoading.contains(connectionId) else { return }
        calendarsLoading.insert(connectionId)
        defer { calendarsLoading.remove(connectionId) }
        do {
            calendars[connectionId] = try await api.remoteCalendars(connectionId: connectionId).calendars
        } catch {
            self.error = error.localizedDescription
        }
    }

    /// For SwiftUI bindings, which cannot await.
    func setCalendarAsync(connectionId: String, calendarId: String, shown: Bool) {
        Task { await setCalendar(connectionId: connectionId, calendarId: calendarId, shown: shown) }
    }

    func setCalendar(connectionId: String, calendarId: String, shown: Bool) async {
        guard let list = calendars[connectionId] else { return }
        let next = list.map { cal in
            cal.id == calendarId
                ? RemoteCalendar(id: cal.id, name: cal.name, color: cal.color, primary: cal.primary, shown: shown)
                : cal
        }
        calendars[connectionId] = next
        do {
            let updated = try await api.setHiddenCalendars(
                connectionId: connectionId, hidden: next.filter { !$0.shown }.map(\.id))
            if let index = connections.firstIndex(where: { $0.id == connectionId }) {
                connections[index] = updated
            }
            await refresh(force: true)
        } catch {
            calendars[connectionId] = list
            self.error = error.localizedDescription
        }
    }
}

// MARK: - Colours

extension Color {
    /// Google hands calendar colours as "#rrggbb".
    init?(hexString: String?) {
        guard var hex = hexString?.trimmingCharacters(in: .whitespaces), !hex.isEmpty else { return nil }
        if hex.hasPrefix("#") { hex.removeFirst() }
        guard hex.count == 6, let value = UInt32(hex, radix: 16) else { return nil }
        self.init(
            red: Double((value >> 16) & 0xff) / 255,
            green: Double((value >> 8) & 0xff) / 255,
            blue: Double(value & 0xff) / 255)
    }
}

// MARK: - One list for the home page

/// A row of the "Coming up" card, whichever calendar it came from: the
/// server-side Google connection or this Mac's own calendars (EventKit).
struct ComingUpItem: Identifiable, Equatable {
    enum Source: Equatable { case google, mac }

    let id: String
    let title: String
    let start: Date
    let end: Date
    let isAllDay: Bool
    let color: Color?
    let meetingURL: URL?
    let detail: String?
    let source: Source

    var isLive: Bool { start <= Date() && end > Date() }

    /// Both sources, merged and sorted; an event present in both (the
    /// same Google account added to the Mac) is kept once.
    static func merge(google: [UpcomingEvent], mac: [CalendarService.Event]) -> [ComingUpItem] {
        var seen = Set<String>()
        var out: [ComingUpItem] = []
        func key(_ title: String, _ start: Date) -> String {
            "\(title.lowercased().trimmingCharacters(in: .whitespaces))|\(Int(start.timeIntervalSince1970 / 60))"
        }
        for event in google {
            let k = key(event.title, event.start)
            guard seen.insert(k).inserted else { continue }
            var parts: [String] = [event.calendarName]
            if event.attendeeCount > 0 {
                parts.append("\(event.attendeeCount) \(event.attendeeCount == 1 ? "guest" : "guests")")
            }
            if let location = event.location, !location.hasPrefix("http") { parts.append(location) }
            out.append(ComingUpItem(
                id: "google:\(event.connectionId):\(event.calendarId):\(event.id)",
                title: event.title, start: event.start, end: event.end, isAllDay: event.allDay,
                color: Color(hexString: event.color),
                meetingURL: event.meetingUrl.flatMap(URL.init(string:)),
                detail: parts.joined(separator: " · "), source: .google))
        }
        for event in mac {
            let k = key(event.title, event.start)
            guard seen.insert(k).inserted else { continue }
            out.append(ComingUpItem(
                id: "mac:\(event.id)", title: event.title, start: event.start, end: event.end,
                isAllDay: event.isAllDay, color: event.calendarColor.map { Color(cgColor: $0) },
                meetingURL: nil, detail: nil, source: .mac))
        }
        return out.sorted { ($0.start, $0.isAllDay ? 0 : 1) < ($1.start, $1.isAllDay ? 0 : 1) }
    }
}
