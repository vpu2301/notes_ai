import AppKit
import SwiftUI

/// The left column: the wordmark under the traffic lights, search, the one
/// button, Home, and the user's spaces. Lists live on the home page.
///
/// It collapses to an icon rail (the toggle beside the wordmark, ⌃⌘S). The
/// rail is wide enough to keep the window's traffic lights inside it, so
/// nothing ever floats over the detail pane.
struct SidebarView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel
    @State private var newSpaceName = ""
    @State private var addingSpace = false
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

    // MARK: - Full column

    private var full: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Color.clear.frame(width: 62)
                DSWordmark(size: 14)
                Spacer(minLength: 4)
                inviteButton
                collapseButton
            }
            .padding(.trailing, 8)
            .frame(height: DS.titlebarInset + 8)
            .padding(.top, 2)

            VStack(spacing: 8) {
                DSSearchField(text: $app.searchQuery, placeholder: "Search notes")
                NewMeetingButton(fill: true, height: 34)
                navRow("Home", symbol: "house", on: app.selection == nil && app.selectedSpaceId == nil) {
                    app.selection = nil
                    app.selectedSpaceId = nil
                }
            }
            .padding(.horizontal, 12)
            .padding(.top, 6)
            .padding(.bottom, 14)

            HStack {
                DSLabel("Spaces")
                Spacer()
                Button {
                    addingSpace = true
                    newSpaceFocused = true
                } label: {
                    Image(systemName: "plus")
                }
                .buttonStyle(DSIconButtonStyle(size: 22))
                .help("New space")
            }
            .padding(.leading, 22)
            .padding(.trailing, 12)
            .padding(.bottom, 4)

            ScrollView {
                VStack(spacing: 2) {
                    ForEach(app.spaces) { space in
                        SpaceRow(space: space, count: app.notes.filter { app.spaceOf[$0.noteId] == space.id }.count,
                                 selected: app.selectedSpaceId == space.id)
                    }
                    if addingSpace {
                        HStack(spacing: 8) {
                            Image(systemName: "folder")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(DS.text3)
                                .frame(width: 16)
                            TextField("Space name", text: $newSpaceName)
                                .textFieldStyle(.plain)
                                .font(.ds(13, .medium))
                                .foregroundStyle(DS.text1)
                                .focused($newSpaceFocused)
                                .onSubmit(commitSpace)
                                .onExitCommand { cancelSpace() }
                        }
                        .padding(.horizontal, 10)
                        .frame(height: 32)
                        .background(
                            RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                                .fill(DS.sidebarOn)
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                                .strokeBorder(DS.text3, lineWidth: 1)
                        )
                    } else if app.spaces.isEmpty {
                        Text("Spaces keep notes together — a client, a project, a team.")
                            .font(.dsMeta)
                            .foregroundStyle(DS.muted)
                            .multilineTextAlignment(.leading)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.horizontal, 10)
                            .padding(.top, 4)
                    }
                }
                .padding(.horizontal, 12)
                .padding(.bottom, 12)
            }

            DSDivider()
            accountRow
        }
    }

    // MARK: - Collapsed rail

    private var rail: some View {
        VStack(spacing: 6) {
            // The traffic lights sit here; the rail is wide enough for them.
            Color.clear.frame(height: DS.titlebarInset + 8)

            collapseButton
            railButton("Search notes", symbol: "magnifyingglass") {
                app.toggleSidebar()
            }
            railButton("Start recording now (⌘N)", symbol: "mic.fill", accent: true) {
                capture.startNew()
            }
            .disabled(capture.isRecording || capture.phase.isBusy)
            railButton("Home", symbol: "house", on: app.selection == nil && app.selectedSpaceId == nil) {
                app.selection = nil
                app.selectedSpaceId = nil
            }

            ScrollView {
                VStack(spacing: 4) {
                    ForEach(app.spaces) { space in
                        railButton(space.name,
                                   symbol: app.selectedSpaceId == space.id ? "folder.fill" : "folder",
                                   on: app.selectedSpaceId == space.id) {
                            app.selectedSpaceId = space.id
                            app.selection = nil
                        }
                    }
                }
                .padding(.vertical, 4)
            }
            .scrollIndicators(.hidden)

            inviteButton
            DSDivider()
            DSMenu(width: 236, edge: .top, items: accountItems) {
                DSAvatar(name: app.email.isEmpty ? "?" : app.email, size: 28)
                    .padding(.vertical, 8)
                    .contentShape(Rectangle())
            }
            .help(app.email.isEmpty ? "Account" : app.email)
        }
    }

    private func railButton(_ help: String, symbol: String, on: Bool = false,
                            accent: Bool = false, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(accent ? DS.inkText : (on ? DS.text1 : DS.text3))
                .frame(width: 32, height: 30)
                .background(
                    RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                        .fill(accent ? DS.ink : (on ? DS.sidebarOn : .clear))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                        .strokeBorder(DS.line, lineWidth: on && !accent ? DS.hairline : 0)
                )
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(help)
    }

    // MARK: - The two chrome icons

    private var collapseButton: some View {
        Button {
            app.toggleSidebar()
        } label: {
            Image(systemName: app.sidebarCollapsed ? "sidebar.left" : "sidebar.leading")
        }
        .buttonStyle(DSIconButtonStyle(size: 24))
        .help(app.sidebarCollapsed ? "Expand sidebar (⌃⌘S)" : "Collapse sidebar (⌃⌘S)")
    }

    private var inviteButton: some View {
        Button {
            app.invitePresented = true
        } label: {
            Image(systemName: "person.badge.plus")
        }
        .buttonStyle(DSIconButtonStyle(size: 24))
        .help("Invite people to this workspace")
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

    private func navRow(_ title: String, symbol: String, on: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: symbol)
                    .font(.system(size: 12, weight: .medium))
                    .frame(width: 16)
                Text(title)
                    .font(.ds(13, .medium))
                Spacer()
            }
            .foregroundStyle(on ? DS.text1 : DS.text3)
            .padding(.horizontal, 10)
            .frame(height: 30)
            .background(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .fill(on ? DS.sidebarOn : .clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .strokeBorder(DS.line, lineWidth: on ? DS.hairline : 0)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private var accountRow: some View {
        DSMenu(width: 236, edge: .top, items: accountItems) {
            HStack(spacing: 9) {
                DSAvatar(name: app.email.isEmpty ? "?" : app.email, size: 26)
                VStack(alignment: .leading, spacing: 0) {
                    Text(app.email.isEmpty ? "Not signed in" : app.email)
                        .font(.ds(12.5, .medium))
                        .foregroundStyle(DS.text1)
                        .lineLimit(1)
                    // The workspace, not the host: which company's notes
                    // these are is the thing you can be wrong about
                    // (IDX-M2). The server address moved into the menu.
                    Text(workspaceLine)
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .lineLimit(1)
                }
                Spacer(minLength: 4)
                Image(systemName: "chevron.up.chevron.down")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(DS.muted)
            }
            .padding(.horizontal, 10)
            .frame(height: 44)
            .contentShape(Rectangle())
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .help(app.email)
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
            .header(app.email.isEmpty ? "Not signed in" : app.email,
                    hint: URL(string: app.settings.authBaseURL)?.host()),
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

/// One space in the sidebar; click filters the home page to it.
private struct SpaceRow: View {
    @EnvironmentObject private var app: AppState
    let space: Space
    let count: Int
    let selected: Bool
    @State private var hover = false
    @State private var renaming = false
    @State private var draft = ""
    @FocusState private var focused: Bool

    var body: some View {
        Button {
            app.selectedSpaceId = space.id
            app.selection = nil
        } label: {
            HStack(spacing: 8) {
                Image(systemName: selected ? "folder.fill" : "folder")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(selected ? DS.accentText : DS.text3)
                    .frame(width: 16)
                if renaming {
                    TextField("Name", text: $draft)
                        .textFieldStyle(.plain)
                        .font(.ds(13, .medium))
                        .focused($focused)
                        .onSubmit { app.renameSpace(space.id, to: draft); renaming = false }
                        .onExitCommand { renaming = false }
                } else {
                    Text(space.name)
                        .font(.ds(13, selected ? .semibold : .medium))
                        .foregroundStyle(selected ? DS.text1 : DS.text2)
                        .lineLimit(1)
                }
                Spacer(minLength: 4)
                if hover {
                    DSMenu(width: 200, dim: true) {
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
                    }
                } else if count > 0 {
                    Text("\(count)")
                        .font(.dsMono(10.5))
                        .foregroundStyle(DS.muted)
                        .padding(.trailing, 8)
                }
            }
            .padding(.leading, 10)
            .padding(.trailing, 4)
            .frame(height: 32)
            .background(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .fill(selected ? DS.sidebarOn : (hover ? DS.sidebarHover : .clear))
            )
            .overlay(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .strokeBorder(DS.line, lineWidth: selected ? DS.hairline : 0)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
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
