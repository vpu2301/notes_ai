import EventKit
import Foundation

/// Upcoming events from the Mac's calendars (EventKit), for the home
/// page's "Upcoming" list. Read-only. Access is only requested when the
/// bundle carries the usage description — a bare `swift run` binary has
/// no Info.plist, and asking there would crash the process.
///
/// Google, Outlook and iCloud calendars all arrive through the same
/// store once their account is added in System Settings › Internet
/// Accounts; the Connectors tab lets the user pick which calendars feed
/// the list.
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

    /// One calendar as shown in the Connectors tab.
    struct CalendarInfo: Identifiable, Equatable {
        let id: String
        let title: String
        /// The account it belongs to ("iCloud", "Google", "Exchange", "On My Mac").
        let source: String
        let color: CGColor?
    }

    enum Access: Equatable {
        case unavailable   // no usage description (development binary)
        case notAsked
        case denied
        case granted
    }

    @Published private(set) var access: Access
    @Published private(set) var events: [Event] = []
    @Published private(set) var calendars: [CalendarInfo] = []
    /// Calendars the user switched off in Connectors (ids). Empty = all.
    @Published private(set) var hiddenCalendarIds: Set<String> {
        didSet { UserDefaults.standard.set(Array(hiddenCalendarIds), forKey: Self.hiddenKey) }
    }

    private static let hiddenKey = "hiddenCalendarIds"
    private let store = EKEventStore()
    private var changeObserver: NSObjectProtocol?

    init() {
        hiddenCalendarIds = Set(UserDefaults.standard.stringArray(forKey: Self.hiddenKey) ?? [])
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
        // Calendars come and go (an account added in System Settings, an
        // event moved in Calendar.app): keep the list current.
        changeObserver = NotificationCenter.default.addObserver(
            forName: .EKEventStoreChanged, object: store, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
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

    /// Re-read the authorization state (the user may have flipped the
    /// switch in System Settings while the app was open).
    func recheckAccess() {
        guard access != .unavailable else { return }
        switch EKEventStore.authorizationStatus(for: .event) {
        case .fullAccess: access = .granted
        case .notDetermined: access = .notAsked
        default: access = .denied
        }
        if access == .granted { refresh() }
    }

    var isCalendarShown: (CalendarInfo) -> Bool {
        { [hiddenCalendarIds] in !hiddenCalendarIds.contains($0.id) }
    }

    func setCalendar(_ id: String, shown: Bool) {
        if shown { hiddenCalendarIds.remove(id) } else { hiddenCalendarIds.insert(id) }
        refresh()
    }

    /// The next seven days, the chosen calendars, sorted by start.
    func refresh() {
        guard access == .granted else { return }
        let all = store.calendars(for: .event)
        calendars = all
            .map {
                CalendarInfo(id: $0.calendarIdentifier, title: $0.title,
                             source: $0.source?.title ?? "Other", color: $0.cgColor)
            }
            .sorted { ($0.source, $0.title) < ($1.source, $1.title) }
        let chosen = all.filter { !hiddenCalendarIds.contains($0.calendarIdentifier) }
        guard !chosen.isEmpty else { events = []; return }

        let start = Calendar.current.startOfDay(for: Date())
        let end = Calendar.current.date(byAdding: .day, value: 7, to: start) ?? start
        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: chosen)
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
