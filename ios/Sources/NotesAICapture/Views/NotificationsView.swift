import SwiftUI

/// The bell: unread count polled while the app is in front, the last
/// fifteen notifications in a sheet, read on tap, all read at once.
@MainActor
final class NotificationsModel: ObservableObject {
    @Published private(set) var unread = 0
    @Published private(set) var items: [NotificationItem]?
    @Published private(set) var loading = false

    private let api: APIClient
    static let pollInterval: Duration = .seconds(30)

    init(api: APIClient) {
        self.api = api
    }

    /// Ask for the count now and every half minute until cancelled.
    func poll() async {
        while !Task.isCancelled {
            await refreshCount()
            try? await Task.sleep(for: Self.pollInterval)
        }
    }

    func refreshCount() async {
        // Keep the last known count when the service is down.
        if let count = try? await api.unreadNotifications() { unread = count.unreadCount }
    }

    func loadFeed() async {
        loading = true
        defer { loading = false }
        do {
            let page = try await api.notifications(limit: 15)
            items = page.items
            unread = page.unreadCount
        } catch {
            items = items ?? []
        }
    }

    func markRead(_ item: NotificationItem) async {
        guard item.readAt == nil else { return }
        if let index = items?.firstIndex(where: { $0.id == item.id }) { items?[index].readAt = Date() }
        if let count = try? await api.markNotificationRead(id: item.id) { unread = count.unreadCount }
    }

    func markAllRead() async {
        items = items?.map { var copy = $0; copy.readAt = copy.readAt ?? Date(); return copy }
        if let count = try? await api.markAllNotificationsRead() { unread = count.unreadCount }
    }

    func forget() {
        unread = 0
        items = nil
    }
}

/// The bell in the home page's bar, with its unread badge.
struct NotificationBell: View {
    @ObservedObject var model: NotificationsModel
    let open: () -> Void

    var body: some View {
        Button(action: open) {
            Image(systemName: "bell")
                .font(.dsSymbol(16, .medium))
                .foregroundStyle(DS.text3)
                .frame(width: 34, height: 34)
                .overlay(alignment: .topTrailing) {
                    if model.unread > 0 {
                        Text(model.unread > 99 ? "99+" : "\(model.unread)")
                            .font(.dsMono(9, .semibold))
                            .foregroundStyle(DS.inkText)
                            .padding(.horizontal, 4)
                            .frame(minWidth: 16, minHeight: 16)
                            .background(Capsule().fill(DS.rec))
                            .offset(x: 2, y: 2)
                    }
                }
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(model.unread > 0 ? "Notifications, \(model.unread) unread" : "Notifications")
    }
}

/// The feed, as a sheet.
struct NotificationsSheet: View {
    @EnvironmentObject private var app: AppState
    @ObservedObject var model: NotificationsModel
    let onClose: () -> Void

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if let items = model.items {
                        if items.isEmpty {
                            VStack(spacing: 6) {
                                Image(systemName: "bell.slash")
                                    .font(.dsSymbol(26, .light))
                                    .foregroundStyle(DS.muted)
                                Text("You're all caught up.")
                                    .font(.dsBody)
                                    .foregroundStyle(DS.muted)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 40)
                        } else {
                            VStack(spacing: 0) {
                                ForEach(items) { item in
                                    row(item)
                                    if item.id != items.last?.id { DSDivider().padding(.leading, 16) }
                                }
                            }
                            .dsCard(padding: 0)
                        }
                    } else {
                        DSSkeleton(height: 56)
                        DSSkeleton(height: 56)
                        DSSkeleton(height: 56)
                    }
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(DS.bg)
            .navigationTitle("Notifications")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    if model.unread > 0 {
                        Button("Mark all read") { Task { await model.markAllRead() } }
                            .font(.ds(14, .medium))
                    }
                }
                ToolbarItem(placement: .topBarTrailing) { Button("Done", action: onClose) }
            }
            .task { await model.loadFeed() }
        }
    }

    private func row(_ item: NotificationItem) -> some View {
        Button {
            Task { await model.markRead(item) }
            if let noteId = item.noteId {
                onClose()
                app.openNote(noteId)
            }
        } label: {
            HStack(alignment: .top, spacing: 10) {
                Circle()
                    .fill(item.readAt == nil ? DS.accent : .clear)
                    .frame(width: 7, height: 7)
                    .padding(.top, 6)
                VStack(alignment: .leading, spacing: 3) {
                    Text(item.title)
                        .font(.ds(15, item.readAt == nil ? .semibold : .medium))
                        .foregroundStyle(DS.text1)
                        .fixedSize(horizontal: false, vertical: true)
                    if !item.bodyText.isEmpty {
                        Text(item.bodyText)
                            .font(.dsMeta)
                            .foregroundStyle(DS.text3)
                            .lineLimit(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Text(relativeTime(item.createdAt))
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                }
                Spacer(minLength: 0)
                if item.noteId != nil {
                    Image(systemName: "chevron.right")
                        .font(.dsSymbol(12, .semibold))
                        .foregroundStyle(DS.muted)
                        .padding(.top, 4)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 11)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityValue(item.readAt == nil ? "Unread" : "Read")
        .accessibilityHint(item.noteId != nil ? "Opens the note" : "Marks it read")
    }
}
