import AppKit
import SwiftUI

/// The left column, laid out like Claude's (as the web's sidebar): the
/// panel toggle and a serif wordmark under the traffic lights, one filled
/// "New meeting" row (a caret on hover for the other ways to start), plain
/// rows for All notes and the user's spaces, and the account as a single
/// row at the foot. Search lives on the home page, as on the web.
///
/// It collapses to an icon rail (the toggle beside the wordmark, ⌃⌘S). The
/// rail is wide enough to keep the window's traffic lights inside it, so
/// nothing ever floats over the detail pane.
struct SidebarView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel
    @State private var newSpaceName = ""
    @State private var addingSpace = false
    @State private var spacesHover = false
    @FocusState private var newSpaceFocused: Bool

    /// Wide enough for the traffic lights (they end around x = 61).
    static let railWidth: CGFloat = 64

    var body: some View {
        Group {
            if app.sidebarCollapsed { rail } else { full }
        }
        .frame(width: app.sidebarCollapsed ? Self.railWidth : DS.sidebarWidth)
        .background(DS.sidebar)
        .onChange(of: newSpaceFocused) { _, focused in
            if !focused, addingSpace { commitSpace() }
        }
    }

    private var onHome: Bool { app.selection == nil && app.selectedSpaceId == nil }

    // MARK: - Full column

    private var full: some View {
        VStack(spacing: 0) {
            HStack(spacing: 6) {
                Color.clear.frame(width: 66)
                collapseButton
                Spacer(minLength: 4)
                NotificationBell()
            }
            .padding(.trailing, 10)
            .frame(height: DS.titlebarInset + 2)

            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    Button { goHome() } label: {
                        DSWordmark(size: 16)
                            .padding(.horizontal, 10)
                            .frame(height: 36)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .help("Notes AI")
                    .padding(.bottom, 8)

                    SidebarNewRow()
                        .padding(.bottom, 2)

                    SidebarRow(title: "All notes", symbol: "doc.text", on: onHome) { goHome() }

                    spaces
                        .padding(.top, 22)
                }
                .padding(.horizontal, 8)
                .padding(.bottom, 12)
            }
            .scrollIndicators(.never)

            Rectangle().fill(DS.line2).frame(height: DS.hairline)
            accountRow
        }
    }

    private var spaces: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 6) {
                DSSectionLabel("Spaces", size: 12.5)
                Spacer()
                Button {
                    addingSpace = true
                    newSpaceFocused = true
                } label: {
                    Image(systemName: "plus")
                        .font(.dsIcon(11, .semibold))
                }
                .buttonStyle(DSIconButtonStyle(size: 24))
                .opacity(spacesHover || app.spaces.isEmpty ? 1 : 0)
                .help("New space")
                .accessibilityLabel("New space")
            }
            .padding(.leading, 10)
            .padding(.trailing, 4)
            .frame(height: 28)

            ForEach(app.spaces) { space in
                SpaceRow(space: space, count: app.notes.filter { app.spaceOf[$0.noteId] == space.id }.count,
                         selected: app.selectedSpaceId == space.id)
            }
            if addingSpace {
                HStack(spacing: 12) {
                    Image(systemName: "folder")
                        .font(.dsIcon(13, .regular))
                        .foregroundStyle(DS.text3)
                        .frame(width: 18)
                    TextField("Space name", text: $newSpaceName)
                        .textFieldStyle(.plain)
                        .font(.ds(14))
                        .foregroundStyle(DS.text1)
                        .focused($newSpaceFocused)
                        .onSubmit(commitSpace)
                        .onExitCommand { cancelSpace() }
                }
                .padding(.horizontal, 10)
                .frame(height: 36)
                .background(
                    RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                        .fill(DS.surface)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                        .strokeBorder(DS.lineActive, lineWidth: DS.hairline)
                )
                .padding(.vertical, 1)
            } else if app.spaces.isEmpty {
                Text("Spaces keep notes together — a client, a project, a team.")
                    .font(.ds(11.5))
                    .foregroundStyle(DS.muted)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 10)
                    .padding(.top, 4)
            }
        }
        .onHover { spacesHover = $0 }
    }

    private func goHome() {
        app.selection = nil
        app.selectedSpaceId = nil
    }

    // MARK: - Collapsed rail

    private var rail: some View {
        VStack(spacing: 4) {
            // The traffic lights sit here; the rail is wide enough for them.
            Color.clear.frame(height: DS.titlebarInset + 2)

            collapseButton
                .padding(.bottom, 6)
            railButton("Start recording now (⌘N)", symbol: "plus", filled: true) {
                capture.startNew()
            }
            .disabled(capture.isRecording || capture.phase.isBusy)
            railButton("All notes", symbol: "doc.text", on: onHome) { goHome() }

            ScrollView {
                VStack(spacing: 2) {
                    ForEach(app.spaces) { space in
                        railButton(space.name, symbol: "folder", on: app.selectedSpaceId == space.id) {
                            app.selectedSpaceId = space.id
                            app.selection = nil
                        }
                    }
                }
                .padding(.vertical, 4)
            }
            .scrollIndicators(.hidden)

            NotificationBell()
            Rectangle().fill(DS.line2).frame(height: DS.hairline)
            DSMenu(width: 236, edge: .top, items: accountItems) {
                DSAvatar(name: accountName, size: 28)
                    .padding(.vertical, 8)
                    .contentShape(Rectangle())
            }
            .help(app.email.isEmpty ? "Account" : app.email)
        }
    }

    private func railButton(_ help: String, symbol: String, on: Bool = false,
                            filled: Bool = false, action: @escaping () -> Void) -> some View {
        RailButton(help: help, symbol: symbol, on: on, filled: filled, action: action)
    }

    // MARK: - The chrome icon

    private var collapseButton: some View {
        Button {
            app.toggleSidebar()
        } label: {
            Image(systemName: "sidebar.left")
                .font(.dsIcon(14, .regular))
        }
        .buttonStyle(SidebarIconButtonStyle())
        .help(app.sidebarCollapsed ? "Expand sidebar (⌃⌘S)" : "Collapse sidebar (⌃⌘S)")
        .accessibilityLabel(app.sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar")
    }

    // MARK: - Spaces editing

    private func commitSpace() {
        let name = newSpaceName
        cancelSpace()
        guard !name.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        Task { await app.addSpace(named: name) }
    }

    private func cancelSpace() {
        addingSpace = false
        newSpaceName = ""
    }

    /// The account as one row: a neutral avatar, the name, a chevron.
    private var accountRow: some View {
        DSMenu(width: 248, edge: .top, items: accountItems) {
            AccountRowLabel(name: accountName)
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .help(app.email)
    }

    /// The person's name when the account has one, else the e-mail.
    private var accountName: String {
        let name = app.identity?.displayName.trimmingCharacters(in: .whitespaces) ?? ""
        if !name.isEmpty { return name }
        return app.email.isEmpty ? "Not signed in" : app.email
    }

    private var workspaceLine: String {
        let name = app.activeWorkspaceName
        if !name.isEmpty { return name }
        return URL(string: app.settings.authBaseURL)?.host() ?? app.settings.authBaseURL
    }

    /// "2 connected" next to the Connectors item; the calendar counts too.
    private var connectorsHint: String? {
        var count = app.connectors.connectors.filter {
            if case .connected = $0.status { return true }
            return false
        }.count
        if app.calendar.access == .granted { count += 1 }
        count += app.googleCalendar.connections.count
        return count == 0 ? nil : "\(count) connected"
    }

    private func accountItems() -> [DSMenuItem] {
        var items: [DSMenuItem] = [
            // The workspace, not the host: which company's notes these are
            // is the thing you can be wrong about (IDX-M2).
            .header(app.email.isEmpty ? "Not signed in" : app.email, hint: workspaceLine),
        ]
        // The workspace switcher, inline: switching is a thing people do
        // several times a day, and a settings sheet is the wrong distance
        // away from it (IDX-M2).
        if app.workspaces.count > 1 {
            items.append(.separator)
            items.append(.header("Workspace"))
            for workspace in app.workspaces.prefix(6) {
                items.append(.item(
                    workspace.title,
                    symbol: workspace.id == app.tenantId ? "checkmark.circle.fill" : "building.2",
                    hint: workspace.myRole?.capitalized,
                    disabled: app.switchingTo != nil,
                    checked: false
                ) {
                    Task { await app.switchWorkspace(to: workspace.id) }
                })
            }
            if app.workspaces.count > 6 {
                items.append(.item("All workspaces…", symbol: "ellipsis") {
                    app.settingsTab = .account
                    app.settingsPresented = true
                })
            }
        }
        items += [
            .separator,
            .item("Invite people…", symbol: "person.badge.plus") { app.invitePresented = true },
            .item("Settings…", symbol: "gearshape", hint: "⌘,") {
                app.settingsTab = .general
                app.settingsPresented = true
            },
            .item("Connectors…", symbol: "puzzlepiece.extension", hint: connectorsHint) { app.showConnectors() },
            .item("Open web app", symbol: "safari") { app.openWebApp() },
            .item("Clear finished meetings", symbol: "checkmark.circle") { app.clearFinishedRecents() },
            .separator,
            .item("Sign out", symbol: "rectangle.portrait.and.arrow.right", danger: true) {
                app.requestSignOut()
            },
            .item("Quit Notes AI Capture", symbol: "power", hint: "⌘Q") { NSApp.terminate(nil) },
        ]
        return items
    }
}

// MARK: - Rows

/// A plain sidebar row (`.sb-link`): icon and label on the sidebar ground;
/// hover and the row you are on take a soft neutral fill, never a frame.
struct SidebarRow: View {
    let title: String
    let symbol: String
    let on: Bool
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: symbol)
                    .font(.dsIcon(13, .regular))
                    .foregroundStyle(on ? DS.text1 : DS.text3)
                    .frame(width: 18)
                Text(title)
                    .font(.ds(14, on ? .medium : .regular))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 10)
            .frame(height: 36)
            .background(
                RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                    .fill(on ? DS.sidebarActive : (hover ? DS.sidebarHover : .clear))
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .padding(.vertical, 1)
        .onHover { hover = $0 }
    }
}

/// "New meeting": the one filled row (`.sb-new`). The row starts recording
/// at once; a caret that surfaces on hover holds the other ways to start
/// (blank note, template, upload).
private struct SidebarNewRow: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel
    @State private var hover = false
    @State private var menuOpen = false
    @State private var pressed = false

    var body: some View {
        ZStack(alignment: .trailing) {
            Button {
                capture.startNew()
            } label: {
                HStack(spacing: 12) {
                    Image(systemName: "plus")
                        .font(.dsIcon(14, .regular))
                        .foregroundStyle(DS.text2)
                        .frame(width: 18)
                    Text("New meeting")
                        .font(.ds(14, .medium))
                        .foregroundStyle(DS.text1)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 10)
                .frame(height: 36)
                .background(SidebarRaisedFill(hover: hover))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(capture.isRecording || capture.phase.isBusy)
            .help("Start recording now (⌘N)")

            DSMenu(width: 224, onOpenChange: { menuOpen = $0 }, items: { NewNoteMenu.items(app: app, capture: capture) }) {
                CaretLabel()
            }
            .help("More ways to start")
            .accessibilityLabel("More ways to start")
            .opacity(hover || menuOpen ? 1 : 0)
            .padding(.trailing, 4)
        }
        .onHover { hover = $0 }
    }
}

/// The "New meeting" button's ground (`.sb-new-main`): raised off the
/// sidebar — surface, hairline, a soft shadow — so it never reads as the
/// row you are on, which takes the flat `sidebarActive` fill.
private struct SidebarRaisedFill: View {
    let hover: Bool

    var body: some View {
        RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
            .fill(hover ? DS.surfaceHover : DS.surface)
            .shadow(color: .black.opacity(0.06), radius: 1.5, y: 1)
            .overlay(
                RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                    .strokeBorder(DS.line, lineWidth: DS.hairline)
            )
    }
}

private struct CaretLabel: View {
    @State private var hover = false

    var body: some View {
        Image(systemName: "chevron.down")
            .font(.dsIcon(10.5, .semibold))
            .foregroundStyle(hover ? DS.text1 : DS.muted)
            .frame(width: 28, height: 28)
            .background(
                RoundedRectangle(cornerRadius: DS.radiusXs + 2, style: .continuous)
                    .fill(hover ? DS.sidebarActive : .clear)
            )
            .contentShape(Rectangle())
            .onHover { hover = $0 }
    }
}

/// One icon on the collapsed rail: 40 pt wide, the same neutral fills as a
/// row; `filled` is the "New meeting" button.
private struct RailButton: View {
    let help: String
    let symbol: String
    var on = false
    var filled = false
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.dsIcon(14, .regular))
                .foregroundStyle(on || filled ? DS.text1 : DS.text3)
                .frame(width: 40, height: 36)
                .background(
                    RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                        .fill(on ? DS.sidebarActive : (hover && !filled ? DS.sidebarHover : .clear))
                )
                .background { if filled { SidebarRaisedFill(hover: hover) } }
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help(help)
        .accessibilityLabel(help)
    }
}

/// The panel toggle (`.sb-toggle`): 32 pt, muted until hovered.
struct SidebarIconButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        SidebarIconButtonBody(configuration: configuration)
    }

    private struct SidebarIconButtonBody: View {
        let configuration: ButtonStyleConfiguration
        @State private var hover = false

        var body: some View {
            configuration.label
                .foregroundStyle(hover ? DS.text1 : DS.text3)
                .frame(width: 32, height: 32)
                .background(
                    RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                        .fill(configuration.isPressed ? DS.sidebarPress : (hover ? DS.sidebarHover : .clear))
                )
                .contentShape(Rectangle())
                .onHover { hover = $0 }
        }
    }
}

/// The foot of the sidebar (`.sb-user`): avatar, name, chevron.
private struct AccountRowLabel: View {
    let name: String
    @State private var hover = false

    var body: some View {
        HStack(spacing: 10) {
            DSAvatar(name: name, size: 28)
            Text(name)
                .font(.ds(14))
                .foregroundStyle(DS.text1)
                .lineLimit(1)
            Spacer(minLength: 4)
            Image(systemName: "chevron.down")
                .font(.dsIcon(10, .semibold))
                .foregroundStyle(DS.muted)
        }
        .padding(.horizontal, 8)
        .frame(height: 44)
        .background(
            RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                .fill(hover ? DS.sidebarHover : .clear)
        )
        .contentShape(Rectangle())
        .onHover { hover = $0 }
    }
}

/// One space in the sidebar; click filters the home page to it. A row like
/// any other — the count on the right gives way to a ⋯ on hover.
private struct SpaceRow: View {
    @EnvironmentObject private var app: AppState
    let space: Space
    let count: Int
    let selected: Bool
    @State private var hover = false
    @State private var menuOpen = false
    @State private var renaming = false
    @State private var draft = ""
    @FocusState private var focused: Bool

    var body: some View {
        Button {
            app.selectedSpaceId = space.id
            app.selection = nil
        } label: {
            HStack(spacing: 12) {
                Image(systemName: "folder")
                    .font(.dsIcon(13, .regular))
                    .foregroundStyle(selected ? DS.text1 : DS.text3)
                    .frame(width: 18)
                if renaming {
                    TextField("Name", text: $draft)
                        .textFieldStyle(.plain)
                        .font(.ds(14))
                        .focused($focused)
                        .onSubmit { app.renameSpace(space.id, to: draft); renaming = false }
                        .onExitCommand { renaming = false }
                } else {
                    Text(space.name)
                        .font(.ds(14, selected ? .medium : .regular))
                        .foregroundStyle(DS.text1)
                        .lineLimit(1)
                }
                Spacer(minLength: 4)
                if hover || menuOpen {
                    DSMenu(width: 200, onOpenChange: { menuOpen = $0 }, items: {
                        [
                            .item("Rename", symbol: "pencil") {
                                draft = space.name
                                renaming = true
                                focused = true
                            },
                            .separator,
                            .item("Delete space", symbol: "trash", danger: true) {
                                app.deleteSpace(space.id)
                            },
                        ]
                    }) {
                        DSMoreLabel(dim: true)
                    }
                } else if count > 0 {
                    Text("\(count)")
                        .font(.ds(10.5, .semibold))
                        .foregroundStyle(DS.muted)
                        .monospacedDigit()
                        .padding(.trailing, 6)
                }
            }
            .padding(.leading, 10)
            .padding(.trailing, 4)
            .frame(height: 36)
            .background(
                RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                    .fill(selected ? DS.sidebarActive : (hover ? DS.sidebarHover : .clear))
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .padding(.vertical, 1)
        .onHover { hover = $0 }
        .onChange(of: focused) { _, on in
            if !on, renaming { app.renameSpace(space.id, to: draft); renaming = false }
        }
    }
}

/// Captures grouped by day, newest first.
enum MeetingGroups {
    struct Group {
        let title: String
        let items: [RecentCapture]
    }

    static func make(_ recents: [RecentCapture], limit: Int? = nil) -> [Group] {
        let items = recents.sorted { $0.createdAt > $1.createdAt }
        let shown = limit.map { Array(items.prefix($0)) } ?? items
        var order: [String] = []
        var buckets: [String: [RecentCapture]] = [:]
        for item in shown {
            let key = dayTitle(item.createdAt)
            if buckets[key] == nil { order.append(key) }
            buckets[key, default: []].append(item)
        }
        return order.map { Group(title: $0, items: buckets[$0] ?? []) }
    }

    static func dayTitle(_ date: Date) -> String {
        let calendar = Calendar.current
        if calendar.isDateInToday(date) { return "Today" }
        if calendar.isDateInYesterday(date) { return "Yesterday" }
        if calendar.isDateInTomorrow(date) { return "Tomorrow" }
        return date.formatted(.dateTime.weekday(.wide).day().month(.wide))
    }
}
