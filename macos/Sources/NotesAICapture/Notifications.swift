import AppKit
import Foundation

/// The bell: an unread count while the window is open (polled every thirty seconds, like the web), the latest fifteen on demand, and read marks. A failed poll is a blip.
@MainActor
extension AppState {
    static let notificationPollInterval: Duration = .seconds(30)

    /// Start keeping the count warm; a second call while one runs is a no-op.
    func startNotificationPolling() {
        guard notificationTask == nil else { return }
        notificationTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refreshUnreadNotifications()
                try? await Task.sleep(for: Self.notificationPollInterval)
            }
        }
    }

    func stopNotificationPolling() {
        notificationTask?.cancel()
        notificationTask = nil
    }

    func refreshUnreadNotifications() async {
        guard authState == .signedIn, !reconnecting else { return }
        if let count = try? await api.unreadNotifications() { unreadNotifications = count }
    }

    /// The latest fifteen, for the panel.
    func loadNotificationFeed() async {
        guard authState == .signedIn else { return }
        notificationsLoading = true
        notificationsError = nil
        defer { notificationsLoading = false }
        do {
            let feed = try await api.notificationFeed(limit: 15)
            notificationFeed = feed.items
            unreadNotifications = feed.unreadCount
        } catch {
            notificationsError = AuthCopy.message(for: error)
        }
    }

    /// Opening one marks it read and follows its link when it points at a note.
    func open(notification item: NotificationItem) async {
        if item.isUnread {
            if let idx = notificationFeed.firstIndex(where: { $0.id == item.id }) {
                notificationFeed[idx].readAt = ISO8601DateFormatter().string(from: Date())
            }
            unreadNotifications = max(0, unreadNotifications - 1)
            if let result = try? await api.markNotificationRead(id: item.id) {
                unreadNotifications = result.unreadCount
            }
        }
        if let noteId = item.noteId { openNote(noteId) }
    }

    func markAllNotificationsRead() async {
        let stamp = ISO8601DateFormatter().string(from: Date())
        notificationFeed = notificationFeed.map { var copy = $0; copy.readAt = copy.readAt ?? stamp; return copy }
        unreadNotifications = 0
        do {
            let result = try await api.markAllNotificationsRead()
            unreadNotifications = result.unreadCount
        } catch {
            notificationsError = AuthCopy.message(for: error)
        }
    }
}
