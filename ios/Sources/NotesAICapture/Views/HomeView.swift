import SwiftUI
import UIKit

/// The home page: a greeting, the spaces, then three lists on a dotted
/// ground — upcoming calendar events (start a meeting from one), meetings
/// still in flight on this phone, and every note, grouped by day. The
/// search box and the space chips narrow the notes.
struct HomeView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel
    @ObservedObject private var calendar: CalendarService
    @ObservedObject private var google: GoogleCalendarService
    @State private var pendingTrash: NoteSummary?
    @State private var trashError: String?
    @State private var addingSpace = false
    @State private var newSpaceName = ""
    @State private var renamingSpace: Space?
    @State private var renameDraft = ""

    init(calendar: CalendarService, google: GoogleCalendarService) {
        self.calendar = calendar
        self.google = google
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                header
                SpacesBar(add: { addingSpace = true }, rename: { space in
                    renameDraft = space.name
                    renamingSpace = space
                })
                if app.selectedSpaceId == nil, searchQuery.isEmpty, showComingUp {
                    ComingUpCard(calendar: calendar, google: google)
                }
                if app.selectedSpaceId == nil, !pendingCaptures.isEmpty {
                    section("Meetings") {
                        rows(pendingCaptures.map { AnyView(CaptureRow(capture: $0)) })
                    }
                }
                notesSection
            }
            .padding(.horizontal, DS.gutter)
            .padding(.top, 8)
            .padding(.bottom, 24)
        }
        .background(ZStack { DS.bg; DSDots() }.ignoresSafeArea())
        .scrollDismissesKeyboard(.immediately)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                DSWordmark(size: 15)
            }
            ToolbarItem(placement: .topBarTrailing) {
                DSMenu(items: accountItems) {
                    DSAvatar(name: app.email.isEmpty ? "?" : app.email, size: 30)
                }
            }
        }
        .searchable(text: $app.searchQuery, placement: .navigationBarDrawer(displayMode: .automatic),
                    prompt: "Search notes")
        .refreshable {
            await app.refreshNotes()
            await app.refreshRecents()
            calendar.refresh()
            await google.refresh(force: true)
        }
        .task { await app.refreshNotes(); calendar.refresh(); await google.refresh() }
        .onChange(of: app.path.isEmpty) { _, home in
            // Back from a note: its title or snippet may have changed.
            if home { Task { await app.refreshNotes() } }
        }
        .alert("Move this note to the trash?", isPresented: Binding(
            get: { pendingTrash != nil }, set: { if !$0 { pendingTrash = nil } }
        )) {
            Button("Move to Trash", role: .destructive) {
                if let note = pendingTrash { Task { await trash(note) } }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("It disappears from everyone's list and any public link stops working. The note is kept for the workspace's records.")
        }
        .alert("Couldn't move the note", isPresented: Binding(
            get: { trashError != nil }, set: { if !$0 { trashError = nil } }
        )) {
            Button("OK") { trashError = nil }
        } message: {
            Text(trashError ?? "")
        }
        .alert("New space", isPresented: $addingSpace) {
            TextField("Space name", text: $newSpaceName)
            Button("Add") {
                if let space = app.addSpace(named: newSpaceName) { app.selectedSpaceId = space.id }
                newSpaceName = ""
            }
            Button("Cancel", role: .cancel) { newSpaceName = "" }
        } message: {
            Text("Spaces keep notes together — a client, a project, a team.")
        }
        .alert("Rename space", isPresented: Binding(
            get: { renamingSpace != nil }, set: { if !$0 { renamingSpace = nil } }
        )) {
            TextField("Name", text: $renameDraft)
            Button("Rename") {
                if let space = renamingSpace { app.renameSpace(space.id, to: renameDraft) }
                renamingSpace = nil
            }
            Button("Cancel", role: .cancel) { renamingSpace = nil }
        }
    }

    private var searchQuery: String { app.searchQuery.trimmingCharacters(in: .whitespaces) }

    private var space: Space? { app.spaces.first { $0.id == app.selectedSpaceId } }

    // MARK: - Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(space?.name ?? greeting)
                .font(.dsDisplay(30))
                .foregroundStyle(DS.text1)
            HStack(spacing: 6) {
                if let space {
                    Text("\(app.visibleNotes.count) \(app.visibleNotes.count == 1 ? "note" : "notes") in \(space.name)")
                } else {
                    Text(Date().formatted(.dateTime.weekday(.wide).day().month(.wide)))
                }
                if app.notesLoading {
                    ProgressView().controlSize(.mini)
                }
            }
            .font(.dsBody)
            .foregroundStyle(DS.muted)
        }
    }

    private var greeting: String {
        let hour = Calendar.current.component(.hour, from: Date())
        switch hour {
        case 5..<12: return "Good morning"
        case 12..<18: return "Good afternoon"
        default: return "Good evening"
        }
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
        [
            .header(app.email.isEmpty ? "Not signed in" : app.email,
                    hint: URL(string: app.settings.authBaseURL)?.host()),
            .separator,
            .item("Settings…", symbol: "gearshape") {
                app.settingsTab = .general
                app.settingsPresented = true
            },
            .item("Connectors…", symbol: "puzzlepiece.extension", hint: connectorsHint) { app.showConnectors() },
            .item("Open web app", symbol: "safari") { app.openWebApp() },
            .item("Clear finished meetings", symbol: "checkmark.circle") { app.clearFinishedRecents() },
            .separator,
            .item("Sign out", symbol: "rectangle.portrait.and.arrow.right", danger: true) {
                Task { await app.signOut() }
            },
        ]
    }

    // MARK: - Coming up (calendar)

    /// Hidden only when there is nothing to offer: the server has no
    /// Google client, nothing is connected, and the bundle has no calendar
    /// usage description.
    private var showComingUp: Bool {
        google.isConnected || google.available != false || google.linkAvailable || calendar.access != .unavailable
    }

    // MARK: - Meetings in flight

    /// This phone's captures that are not (yet) a note: in progress,
    /// failed, or transcribed without a note.
    private var pendingCaptures: [RecentCapture] {
        app.recents
            .filter { $0.noteId == nil }
            .filter { searchQuery.isEmpty || $0.title.localizedCaseInsensitiveContains(searchQuery) }
            .sorted { $0.createdAt > $1.createdAt }
    }

    // MARK: - Notes

    @ViewBuilder
    private var notesSection: some View {
        let notes = app.visibleNotes
        if let error = app.notesError, notes.isEmpty {
            section("Notes") {
                VStack(alignment: .leading, spacing: 10) {
                    DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                    Button("Try again") { Task { await app.refreshNotes() } }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 34))
                }
            }
        } else if notes.isEmpty {
            section("Notes") {
                VStack(spacing: 6) {
                    Text(emptyTitle)
                        .font(.dsDisplay(17))
                        .foregroundStyle(DS.text1)
                    Text(emptyHint)
                        .font(.dsBody)
                        .foregroundStyle(DS.muted)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 32)
                .padding(.horizontal, 20)
                .dsCard(padding: 0, radius: DS.radiusLg)
            }
        } else {
            ForEach(groups(notes), id: \.title) { group in
                section(group.title) {
                    rows(group.items.map { note in
                        AnyView(NoteRow(note: note, trash: { pendingTrash = note }))
                    })
                }
            }
        }
    }

    private var emptyTitle: String {
        if !searchQuery.isEmpty { return "Nothing matches “\(searchQuery)”" }
        if app.selectedSpaceId != nil { return "Nothing in this space yet" }
        return "No notes yet"
    }

    private var emptyHint: String {
        if !searchQuery.isEmpty { return "Try other words — the search also looks inside the notes." }
        if app.selectedSpaceId != nil { return "Use “Move to …” in a note's ⋯ menu to file it here." }
        return "Tap New meeting when one starts. Stop when it ends and the note is drafted for you."
    }

    private func groups(_ notes: [NoteSummary]) -> [(title: String, items: [NoteSummary])] {
        var order: [String] = []
        var buckets: [String: [NoteSummary]] = [:]
        for note in notes.sorted(by: { $0.updatedAt > $1.updatedAt }) {
            let key = MeetingGroups.dayTitle(note.updatedAt)
            if buckets[key] == nil { order.append(key) }
            buckets[key, default: []].append(note)
        }
        return order.map { ($0, buckets[$0] ?? []) }
    }

    private func trash(_ note: NoteSummary) async {
        do {
            try await app.moveToTrash(noteId: note.noteId)
        } catch {
            trashError = error.localizedDescription
        }
    }

    // MARK: - Building blocks

    private func section(_ title: String, @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            DSLabel(title).padding(.leading, 4)
            content()
        }
    }

    /// Rows stacked in one hairline card, divided by hairlines.
    private func rows(_ items: [AnyView]) -> some View {
        VStack(spacing: 0) {
            ForEach(Array(items.enumerated()), id: \.offset) { index, row in
                row
                if index < items.count - 1 {
                    DSDivider().padding(.leading, 16)
                }
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous))
        .dsCard(padding: 0, radius: DS.radiusLg)
    }
}

// MARK: - Spaces

/// The user's spaces as a row of chips: All notes, each space (hold for
/// rename / delete), and ＋.
private struct SpacesBar: View {
    @EnvironmentObject private var app: AppState
    let add: () -> Void
    let rename: (Space) -> Void

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                chip("All notes", symbol: "tray.full", on: app.selectedSpaceId == nil) {
                    app.selectedSpaceId = nil
                }
                ForEach(app.spaces) { space in
                    let count = app.notes.filter { app.spaceOf[$0.noteId] == space.id }.count
                    chip(space.name, symbol: app.selectedSpaceId == space.id ? "folder.fill" : "folder",
                         count: count, on: app.selectedSpaceId == space.id) {
                        app.selectedSpaceId = space.id
                    }
                    .contextMenu {
                        Button { rename(space) } label: { Label("Rename", systemImage: "pencil") }
                        Button(role: .destructive) { app.deleteSpace(space.id) } label: {
                            Label("Delete space", systemImage: "trash")
                        }
                    }
                }
                Button(action: add) {
                    Image(systemName: "plus")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(DS.text3)
                        .frame(width: 34, height: 34)
                        .background(Circle().fill(DS.surface))
                        .overlay(Circle().strokeBorder(DS.line, lineWidth: DS.hairline))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("New space")
            }
            .padding(.horizontal, DS.gutter)
        }
        .padding(.horizontal, -DS.gutter)
    }

    private func chip(_ title: String, symbol: String, count: Int = 0, on: Bool,
                      action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: symbol)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(on ? DS.inkText : DS.text3)
                Text(title)
                    .font(.ds(14, .medium))
                    .foregroundStyle(on ? DS.inkText : DS.text1)
                    .lineLimit(1)
                if count > 0, !on {
                    Text("\(count)")
                        .font(.dsMono(11))
                        .foregroundStyle(DS.muted)
                }
            }
            .padding(.horizontal, 13)
            .frame(height: 34)
            .background(Capsule().fill(on ? DS.ink : DS.surface))
            .overlay(Capsule().strokeBorder(DS.line, lineWidth: on ? 0 : DS.hairline))
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Rows

/// A note from the tenant: title, status when not a draft, snippet, time.
private struct NoteRow: View {
    @EnvironmentObject private var app: AppState
    let note: NoteSummary
    let trash: () -> Void

    var body: some View {
        HStack(spacing: 4) {
            Button {
                app.openNote(note.noteId)
            } label: {
                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 8) {
                            Text(note.title.isEmpty ? "Untitled note" : note.title)
                                .font(.ds(15.5, .semibold))
                                .foregroundStyle(DS.text1)
                                .lineLimit(1)
                            if let status = note.status, status != .draft {
                                DSChip(text: status.label, tint: status.tint, soft: status.soft)
                            }
                        }
                        HStack(spacing: 6) {
                            if let spaceId = app.spaceOf[note.noteId],
                               app.selectedSpaceId == nil,
                               let space = app.spaces.first(where: { $0.id == spaceId }) {
                                Text(space.name)
                                    .font(.ds(11, .medium))
                                    .foregroundStyle(DS.text3)
                                    .padding(.horizontal, 6)
                                    .padding(.vertical, 2)
                                    .background(Capsule().fill(DS.surface2))
                            }
                            Text(note.snippet.isEmpty ? note.code : note.snippet)
                                .font(.dsMeta)
                                .foregroundStyle(DS.muted)
                                .lineLimit(1)
                        }
                    }
                    Spacer(minLength: 8)
                    Text(note.updatedAt.formatted(date: .omitted, time: .shortened))
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .monospacedDigit()
                }
                .padding(.leading, 16)
                .padding(.vertical, 12)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            DSMenu(dim: true, items: menuItems)
                .padding(.trailing, 6)
        }
        .contextMenu { DSMenuContent(items: menuItems()) }
    }

    private func menuItems() -> [DSMenuItem] {
        var items: [DSMenuItem] = [
            .item("Open", symbol: "doc.text") { app.openNote(note.noteId) },
            .item("Open in web app", symbol: "safari") { app.openNoteInBrowser(note.noteId) },
            .item("Copy link", symbol: "link") {
                if let url = app.noteURL(note.noteId) { copyToPasteboard(url.absoluteString) }
            },
        ]
        if !app.spaces.isEmpty {
            items.append(.separator)
            let current = app.spaceOf[note.noteId]
            for space in app.spaces {
                items.append(.item("Move to \(space.name)", symbol: "folder", checked: current == space.id) {
                    app.file(noteId: note.noteId, in: current == space.id ? nil : space.id)
                })
            }
        }
        items.append(.separator)
        items.append(.item("Move to trash", symbol: "trash", danger: true) { trash() })
        return items
    }
}

/// A capture that is not a note yet.
private struct CaptureRow: View {
    @EnvironmentObject private var app: AppState
    let capture: RecentCapture

    var body: some View {
        HStack(spacing: 4) {
            Button {
                app.select(jobId: capture.jobId)
            } label: {
                HStack(spacing: 12) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(capture.title)
                            .font(.ds(15.5, .semibold))
                            .foregroundStyle(DS.text1)
                            .lineLimit(1)
                        Text(capture.createdAt.formatted(date: .omitted, time: .shortened))
                            .font(.dsMeta)
                            .foregroundStyle(DS.muted)
                    }
                    Spacer(minLength: 8)
                    switch capture.status {
                    case .queued, .running:
                        DSChip(text: "In progress", tint: DS.info, soft: DS.infoSoft, dot: true)
                    case .failed:
                        DSChip(text: "Failed", tint: DS.rec, soft: DS.recSoft)
                    case .cancelled:
                        DSChip(text: "Cancelled", tint: DS.warn, soft: DS.warnSoft)
                    case .complete:
                        DSChip(text: "No note yet", tint: DS.warn, soft: DS.warnSoft)
                    case .none:
                        EmptyView()
                    }
                }
                .padding(.leading, 16)
                .padding(.vertical, 12)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            DSMenu(dim: true) {
                [
                    .item("Copy job ID", symbol: "number") { copyToPasteboard(capture.jobId) },
                    .separator,
                    .item("Remove from list", symbol: "trash", danger: true) {
                        app.removeRecents(jobIds: [capture.jobId])
                    },
                ]
            }
            .padding(.trailing, 6)
        }
    }
}

/// "Coming up": today's date, then the next days' events — from the Google
/// accounts and calendar links connected on the server and from this
/// phone's own calendars, merged. One button connects Google (or adds a
/// link when the server has no Google client); the ⋯ menu holds the rest
/// (choose calendars, another account, disconnect).
private struct ComingUpCard: View {
    @EnvironmentObject private var app: AppState
    @ObservedObject var calendar: CalendarService
    @ObservedObject var google: GoogleCalendarService
    @State private var pendingDisconnect: CalendarConnection?
    @State private var addingLink = false

    private var items: [ComingUpItem] {
        ComingUpItem.merge(google: google.events, device: calendar.access == .granted ? calendar.events : [])
    }

    private var anySource: Bool { google.isConnected || calendar.access == .granted }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                DSLabel("Coming up").padding(.leading, 4)
                Spacer()
                if google.loading, google.isConnected {
                    ProgressView().controlSize(.mini)
                }
                DSMenu(dim: true, items: menuItems)
            }
            VStack(alignment: .leading, spacing: 12) {
                dateBlock
                ForEach(google.problems, id: \.connectionId) { problem in
                    problemRow(problem)
                }
                content
            }
            .padding(14)
            .dsCard(padding: 0, radius: DS.radiusXl)
        }
        .alert(Text(pendingDisconnect?.isLink == true ? "Remove this calendar link?" : "Disconnect this Google account?"),
               isPresented: Binding(
            get: { pendingDisconnect != nil }, set: { if !$0 { pendingDisconnect = nil } }
        )) {
            Button(pendingDisconnect?.isLink == true ? "Remove" : "Disconnect", role: .destructive) {
                if let connection = pendingDisconnect { Task { await google.disconnect(connection.id) } }
                pendingDisconnect = nil
            }
            Button("Cancel", role: .cancel) { pendingDisconnect = nil }
        } message: {
            Text(pendingDisconnect?.isLink == true
                 ? "Its events leave the list here and in the web app. The calendar itself is untouched."
                 : "Its events leave the list here and in the web app. Nothing changes in Google Calendar.")
        }
        .sheet(isPresented: $addingLink) {
            CalendarLinkSheet(google: google) { addingLink = false }
        }
    }

    private var dateBlock: some View {
        let now = Date()
        return HStack(alignment: .top, spacing: 10) {
            Text(now.formatted(.dateTime.day()))
                .font(.dsDisplay(34, .medium))
                .foregroundStyle(DS.text1)
                .monospacedDigit()
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 5) {
                    Text(now.formatted(.dateTime.month(.wide)))
                        .font(.ds(15, .semibold))
                        .foregroundStyle(DS.text1)
                    Circle().fill(DS.accent).frame(width: 6, height: 6)
                }
                Text(now.formatted(.dateTime.weekday(.wide)))
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
            }
            .padding(.top, 6)
        }
    }

    @ViewBuilder
    private var content: some View {
        if !anySource {
            dashed {
                VStack(spacing: 12) {
                    Image(systemName: "calendar.badge.clock")
                        .font(.system(size: 26, weight: .light))
                        .foregroundStyle(DS.muted)
                    Text("See your next meetings here and start a note from one.")
                        .font(.dsBody)
                        .foregroundStyle(DS.muted)
                        .multilineTextAlignment(.center)
                    VStack(spacing: 8) {
                        if google.available != false {
                            Button(google.connecting ? "Opening Google…" : "Connect Google Calendar") {
                                Task { await google.connect() }
                            }
                            .buttonStyle(DSButtonStyle(kind: .primary, size: 14, height: 38, fill: true))
                            .disabled(google.connecting)
                        }
                        if google.linkAvailable {
                            Button("Add calendar link") { addingLink = true }
                                .buttonStyle(DSButtonStyle(kind: google.available == false ? .primary : .secondary,
                                                           size: 14, height: 38, fill: true))
                        }
                        if calendar.access == .notAsked {
                            Button("Use this phone's calendars") { Task { await calendar.requestAccess() } }
                                .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 38, fill: true))
                        }
                    }
                    if let error = google.error {
                        Text(error)
                            .font(.dsMeta)
                            .foregroundStyle(DS.dangerText)
                            .multilineTextAlignment(.center)
                    }
                }
            }
        } else if items.isEmpty {
            dashed {
                VStack(spacing: 10) {
                    Image(systemName: "calendar.badge.clock")
                        .font(.system(size: 26, weight: .light))
                        .foregroundStyle(DS.muted)
                    Text(google.loading && google.events.isEmpty ? "Loading…" : "No upcoming events")
                        .font(.dsBody)
                        .foregroundStyle(DS.muted)
                }
            }
        } else {
            VStack(spacing: 0) {
                ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
                    ComingUpRow(item: item)
                    if index < items.count - 1 {
                        DSDivider().padding(.leading, 12)
                    }
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous))
            .dsCard(padding: 0, radius: DS.radiusLg)
        }
    }

    private func dashed(@ViewBuilder _ inner: () -> some View) -> some View {
        inner()
            .frame(maxWidth: .infinity, minHeight: 140)
            .padding(16)
            .background(
                RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous)
                    .strokeBorder(style: StrokeStyle(lineWidth: 1.2, dash: [5, 4]))
                    .foregroundStyle(DS.line)
            )
    }

    private func problemRow(_ problem: CalendarProblem) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.ds(12, .semibold))
                    .foregroundStyle(DS.warn)
                    .padding(.top, 2)
                Text(problem.needsReauth
                     ? "Google asked to sign in again for \(problem.accountEmail)."
                     : "\(problem.accountEmail): \(problem.message)")
                    .font(.ds(14))
                    .foregroundStyle(DS.text1)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if problem.needsReauth {
                Button("Sign in again") { Task { await google.connect(loginHint: problem.accountEmail) } }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 13, height: 32))
                    .disabled(google.connecting)
            }
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: DS.radius, style: .continuous).fill(DS.warnSoft))
    }

    private func menuItems() -> [DSMenuItem] {
        var items: [DSMenuItem] = []
        if google.isConnected || calendar.access == .granted {
            items.append(.item("Choose calendars…", symbol: "calendar") { app.showConnectors() })
            items.append(.item("Refresh", symbol: "arrow.clockwise") {
                calendar.refresh()
                Task { await google.refresh(force: true) }
            })
        }
        if google.available != false {
            if !items.isEmpty { items.append(.separator) }
            items.append(.item(google.isConnected ? "Connect another Google account" : "Connect Google Calendar",
                               symbol: "plus") { Task { await google.connect() } })
        }
        if google.linkAvailable {
            if google.available == false, !items.isEmpty { items.append(.separator) }
            items.append(.item("Add calendar link…", symbol: "link") { addingLink = true })
        }
        if calendar.access == .notAsked {
            items.append(.item("Use this phone's calendars", symbol: "iphone") {
                Task { await calendar.requestAccess() }
            })
        }
        if !google.connections.isEmpty {
            items.append(.separator)
            for connection in google.connections {
                items.append(.item(connection.isLink ? "Remove \(connection.accountEmail)" : "Disconnect \(connection.accountEmail)",
                                   symbol: "xmark.circle", danger: true) {
                    pendingDisconnect = connection
                })
            }
        }
        return items
    }
}

/// One upcoming event, with Join (when it has a video link) and a Start
/// button that begins a meeting note with the event's title.
private struct ComingUpRow: View {
    @EnvironmentObject private var capture: CaptureViewModel
    let item: ComingUpItem

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                if !Calendar.current.isDateInToday(item.start) {
                    Text(dayLabel.uppercased())
                        .font(.dsLabel)
                        .tracking(0.5)
                        .foregroundStyle(DS.muted)
                }
                Text(item.isLive ? "Now" : when)
                    .font(.ds(12.5, item.isLive ? .semibold : .regular))
                    .foregroundStyle(item.isLive ? DS.accentText : DS.text3)
                    .monospacedDigit()
                    .lineLimit(2)
            }
            .frame(width: 64, alignment: .leading)
            RoundedRectangle(cornerRadius: 2, style: .continuous)
                .fill(item.color ?? DS.accent)
                .frame(width: 3, height: 30)
            VStack(alignment: .leading, spacing: 2) {
                Text(item.title)
                    .font(.ds(15, .semibold))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                if let detail = item.detail, !detail.isEmpty {
                    Text(detail)
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 6)
            if let url = item.meetingURL {
                Button {
                    UIApplication.shared.open(url)
                } label: {
                    Image(systemName: "video")
                }
                .buttonStyle(DSIconButtonStyle())
                .accessibilityLabel("Join the video call")
            }
            if !capture.isRecording, !capture.phase.isBusy {
                Button {
                    capture.startNew(title: item.title)
                } label: {
                    Image(systemName: "mic.fill")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(DS.inkText)
                        .frame(width: 34, height: 34)
                        .background(Circle().fill(DS.ink))
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Start a meeting note for this event")
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
    }

    private var dayLabel: String {
        let calendar = Calendar.current
        if calendar.isDateInTomorrow(item.start) { return "Tomorrow" }
        return item.start.formatted(.dateTime.weekday(.abbreviated).day().month(.abbreviated))
    }

    private var when: String {
        if item.isAllDay { return "All day" }
        let start = item.start.formatted(date: .omitted, time: .shortened)
        let end = item.end.formatted(date: .omitted, time: .shortened)
        return "\(start)\n– \(end)"
    }
}
