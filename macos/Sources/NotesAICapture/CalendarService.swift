import EventKit
import Foundation

/// Upcoming events from the Mac's calendars (EventKit), for the home
/// page's "Upcoming" list. Read-only. Access is only requested when the
/// bundle carries the usage description — a bare `swift run` binary has
/// no Info.plist, and asking there would crash the process.
@MainActor
final class CalendarService: ObservableObject {
    struct Event: Identifiable, Equatable {
        let id: String
        let title: String
        let start: Date
        let end: Date
        let isAllDay: Bool
        let calendarColor: CGColor?
    }

    enum Access: Equatable {
        case unavailable   // no usage description (development binary)
        case notAsked
        case denied
        case granted
    }

    @Published private(set) var access: Access
    @Published private(set) var events: [Event] = []

    private let store = EKEventStore()

    init() {
        let hasDescription = Bundle.main.object(forInfoDictionaryKey: "NSCalendarsFullAccessUsageDescription") != nil
        if !hasDescription {
            access = .unavailable
        } else {
            switch EKEventStore.authorizationStatus(for: .event) {
            case .fullAccess: access = .granted
            case .notDetermined: access = .notAsked
            default: access = .denied
            }
        }
        if access == .granted { refresh() }
    }

    func requestAccess() async {
        guard access == .notAsked || access == .denied else { return }
        do {
            let granted = try await store.requestFullAccessToEvents()
            access = granted ? .granted : .denied
        } catch {
            access = .denied
        }
        if access == .granted { refresh() }
    }

    /// The next seven days, all calendars, sorted by start.
    func refresh() {
        guard access == .granted else { return }
        let start = Calendar.current.startOfDay(for: Date())
        let end = Calendar.current.date(byAdding: .day, value: 7, to: start) ?? start
        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: nil)
        let now = Date()
        events = store.events(matching: predicate)
            .filter { $0.endDate > now }
            .sorted { $0.startDate < $1.startDate }
            .prefix(12)
            .map {
                Event(id: $0.eventIdentifier ?? UUID().uuidString,
                      title: $0.title ?? "Untitled event",
                      start: $0.startDate, end: $0.endDate, isAllDay: $0.isAllDay,
                      calendarColor: $0.calendar?.cgColor)
            }
    }
}
