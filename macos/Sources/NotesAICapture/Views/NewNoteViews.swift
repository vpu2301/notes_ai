import AppKit
import SwiftUI

// The other ways a note begins (web parity): blank, from a template, or
// from a recording made elsewhere. One menu, beside New meeting in the
// sidebar — the one place these live.

/// The "＋" beside New meeting.
struct NewNoteMenu: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel

    var body: some View {
        DSMenu(width: 224, items: items) {
            Image(systemName: "plus")
                .font(.dsIcon(12, .semibold))
                .foregroundStyle(DS.text2)
                .frame(width: 34, height: 34)
                .background(
                    RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                        .fill(DS.sidebarOn)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                        .strokeBorder(DS.line, lineWidth: DS.hairline)
                )
                .contentShape(Rectangle())
        }
        .help("New note, from a template or a recording")
        .accessibilityLabel("New note")
    }

    private func items() -> [DSMenuItem] {
        [
            .item("Blank note", symbol: "doc", disabled: app.creatingNote) {
                Task { await app.createBlankNote() }
            },
            .item("New from template…", symbol: "square.stack.3d.up", disabled: app.creatingNote) {
                app.templatePickerPresented = true
            },
            .separator,
            .item("Upload a recording…", symbol: "arrow.up.doc",
                  disabled: capture.isRecording || capture.phase.isBusy) {
                app.uploadRecording()
            },
        ]
    }
}

/// Pick a template to start from. Sections come pre-filled with their
/// defaults.
struct TemplatePickerSheet: View {
    @EnvironmentObject private var app: AppState
    let onClose: () -> Void
    @State private var templates: [TemplateSummary]?
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("New note")
                        .font(.dsDisplay(17, .medium))
                        .foregroundStyle(DS.text1)
                    Text("Pick a template to start from. Sections come pre-filled with their defaults.")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                }
                Spacer()
                Button("Cancel", action: onClose)
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 26))
                    .keyboardShortcut(.cancelAction)
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 16)
            DSDivider()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if let error {
                        DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill", text: error)
                    } else if let templates {
                        if templates.isEmpty {
                            Text("Your workspace has no note templates yet. Ask an administrator to add some.")
                                .font(.dsBody)
                                .foregroundStyle(DS.muted)
                        }
                        ForEach(grouped(templates), id: \.category) { group in
                            VStack(alignment: .leading, spacing: 8) {
                                DSLabel(group.category.replacingOccurrences(of: "_", with: " "))
                                LazyVGrid(columns: [GridItem(.adaptive(minimum: 200), spacing: 10)], spacing: 10) {
                                    ForEach(group.templates) { template in
                                        TemplateCard(template: template, busy: app.creatingNote) {
                                            Task { await app.createNote(fromTemplate: template.id) }
                                        }
                                    }
                                }
                            }
                        }
                    } else {
                        HStack(spacing: 8) {
                            ProgressView().controlSize(.small)
                            Text("Loading templates…")
                                .font(.dsBody)
                                .foregroundStyle(DS.muted)
                        }
                    }
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .background(DS.bg)
        .task {
            do {
                templates = try await app.templates()
            } catch {
                self.error = AuthCopy.message(for: error)
            }
        }
    }

    private struct Group {
        let category: String
        let templates: [TemplateSummary]
    }

    private func grouped(_ list: [TemplateSummary]) -> [Group] {
        var buckets: [String: [TemplateSummary]] = [:]
        for t in list { buckets[t.category ?? "templates", default: []].append(t) }
        return buckets.keys.sorted().map { key in
            Group(category: key, templates: buckets[key]!.sorted { $0.name.localizedCompare($1.name) == .orderedAscending })
        }
    }
}

private struct TemplateCard: View {
    let template: TemplateSummary
    let busy: Bool
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: "doc.text")
                    .font(.dsIconLg)
                    .foregroundStyle(DS.accentText)
                    .frame(width: 30, height: 30)
                    .background(RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous).fill(DS.accentSoft))
                VStack(alignment: .leading, spacing: 2) {
                    Text(template.name)
                        .font(.ds(13, .semibold))
                        .foregroundStyle(DS.text1)
                        .lineLimit(1)
                    Text(template.language.uppercased())
                        .font(.dsMono(10.5))
                        .foregroundStyle(DS.muted)
                }
                Spacer(minLength: 0)
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous)
                    .fill(hover ? DS.surfaceHover : DS.surface)
            )
            .overlay(
                RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous)
                    .strokeBorder(hover ? DS.lineHover : DS.line, lineWidth: DS.hairline)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(busy)
        .onHover { hover = $0 }
    }
}

// MARK: - The bell

/// Unread count on the bell; the latest fifteen in a panel.
struct NotificationBell: View {
    @EnvironmentObject private var app: AppState
    var size: CGFloat = 24
    @State private var open = false

    var body: some View {
        Button {
            open.toggle()
        } label: {
            Image(systemName: app.unreadNotifications > 0 ? "bell.badge" : "bell")
                .symbolRenderingMode(.palette)
                .foregroundStyle(DS.rec, DS.text3)
        }
        .buttonStyle(DSIconButtonStyle(size: size))
        .help(app.unreadNotifications > 0 ? "\(app.unreadNotifications) unread" : "Notifications")
        .accessibilityLabel(app.unreadNotifications > 0
                            ? "Notifications, \(app.unreadNotifications) unread" : "Notifications")
        .popover(isPresented: $open, arrowEdge: .bottom) {
            NotificationsPanel { open = false }
        }
    }
}

private struct NotificationsPanel: View {
    @EnvironmentObject private var app: AppState
    let close: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Notifications")
                    .font(.ds(13, .semibold))
                    .foregroundStyle(DS.text1)
                Spacer()
                if app.unreadNotifications > 0 {
                    Button("Mark all read") { Task { await app.markAllNotificationsRead() } }
                        .buttonStyle(DSButtonStyle(kind: .ghost, size: 11.5, height: 22))
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            DSDivider()
            if let error = app.notificationsError {
                DSNotice(tone: .warn, symbol: "exclamationmark.triangle.fill", text: error)
                    .padding(10)
            } else if app.notificationFeed.isEmpty {
                Text(app.notificationsLoading ? "Loading…" : "Nothing yet.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .padding(14)
            } else {
                ScrollView {
                    VStack(spacing: 1) {
                        ForEach(app.notificationFeed) { item in
                            NotificationRow(item: item) {
                                close()
                                Task { await app.open(notification: item) }
                            }
                        }
                    }
                    .padding(6)
                }
                .frame(maxHeight: 360)
            }
        }
        .frame(width: 340)
        .background(DS.surface)
        .task { await app.loadNotificationFeed() }
    }
}

private struct NotificationRow: View {
    let item: NotificationItem
    let open: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: open) {
            HStack(alignment: .top, spacing: 10) {
                Circle()
                    .fill(item.isUnread ? DS.accent : .clear)
                    .frame(width: 6, height: 6)
                    .padding(.top, 6)
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.title)
                        .font(.ds(12.5, item.isUnread ? .semibold : .medium))
                        .foregroundStyle(DS.text1)
                        .lineLimit(2)
                    if !item.bodyText.isEmpty {
                        Text(item.bodyText)
                            .font(.dsMeta)
                            .foregroundStyle(DS.text3)
                            .lineLimit(2)
                    }
                    Text(relativeTime(item.createdAt))
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                }
                Spacer(minLength: 0)
            }
            .padding(8)
            .background(
                RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                    .fill(hover ? DS.surface2 : .clear)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .accessibilityLabel(item.isUnread ? "Unread: \(item.title)" : item.title)
    }
}
