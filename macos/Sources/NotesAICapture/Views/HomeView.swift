import AppKit
import SwiftUI

/// The home page, as the web's: one compact header row (greeting, date, search, New meeting with a ⋯), then upcoming events, captures in flight, and every note grouped by day.
struct HomeView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel
    @ObservedObject private var calendar: CalendarService
    @ObservedObject private var google: GoogleCalendarService
    @State private var pendingTrash: NoteSummary?
    @State private var trashError: String?
    @State private var accessError: String?
    @State private var searchOpen = false
    @State private var allCaptures = false
    @FocusState private var searchFocused: Bool

    /// In-progress captures shown before "Show N more" — the notes come first.
    private static let capturesShown = 3

    init(calendar: CalendarService, google: GoogleCalendarService) {
        self.calendar = calendar
        self.google = google
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Color.clear.frame(height: DS.titlebarInset - 24)
                header
                if app.isFirstRun {
                    FirstRunCard()
                }
                if case .idle = capture.phase {} else {
                    ActiveCaptureCard()
                        .dsCard(padding: 16, radius: DS.radiusXl)
                }
                if app.selectedSpaceId == nil, searchQuery.isEmpty, showComingUp {
                    ComingUpCard(calendar: calendar, google: google)
                }
                if app.selectedSpaceId == nil, !pendingCaptures.isEmpty {
                    let shown = allCaptures ? pendingCaptures : Array(pendingCaptures.prefix(Self.capturesShown))
                    section("In progress", count: pendingCaptures.count) {
                        VStack(alignment: .leading, spacing: 4) {
                            rows(shown.map { AnyView(CaptureRow(capture: $0)) })
                            if pendingCaptures.count > Self.capturesShown {
                                ShowMoreButton(title: allCaptures
                                               ? "Show fewer"
                                               : "Show \(pendingCaptures.count - Self.capturesShown) more") {
                                    withAnimation(.easeOut(duration: 0.2)) { allCaptures.toggle() }
                                }
                            }
                        }
                    }
                }
                // Recordings the server never got, above the notes: unfinished work outranks finished work.
                if app.selectedSpaceId == nil, !app.pending.isEmpty {
                    PendingUploadsSection(pending: app.pending)
                }
                notesSection
            }
            .frame(maxWidth: 760, alignment: .leading)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 40)
            .padding(.bottom, 60)
        }
        .background(ZStack { DS.bg; DSDots() }.ignoresSafeArea())
        .task { await app.refreshNotes(); await app.refreshRecents(); await app.refreshSpaces(); calendar.refresh(); await google.refresh() }
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
        .alert("Couldn't change who can open the note", isPresented: Binding(
            get: { accessError != nil }, set: { if !$0 { accessError = nil } }
        )) {
            Button("OK") { accessError = nil }
        } message: {
            Text(accessError ?? "")
        }
    }

    private var searchQuery: String { app.searchQuery.trimmingCharacters(in: .whitespaces) }

    private var space: Space? { app.spaces.first { $0.id == app.selectedSpaceId } }

    // MARK: - Header

    /// One row: the title, then search and the ways to start, so the notes begin right under it.
    private var header: some View {
        HStack(alignment: .center, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.dsSerif(30))
                    .tracking(-0.5)
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                    .truncationMode(.tail)
                HStack(spacing: 6) {
                    if space != nil {
                        Text("\(app.visibleNotes.count) \(app.visibleNotes.count == 1 ? "note" : "notes")")
                    } else {
                        Text(Date().formatted(.dateTime.weekday(.wide).day().month(.wide)))
                    }
                    if app.notesLoading {
                        ProgressView().controlSize(.mini)
                    }
                }
                .font(.ds(12.5))
                .foregroundStyle(DS.muted)
            }
            .layoutPriority(searchShown ? 0 : 1)
            Spacer(minLength: 8)
            search
            if case .idle = capture.phase {
                HStack(spacing: 4) {
                    NewMeetingButton(height: 34)
                    DSMenu(width: 236, items: startItems) {
                        HomeIconLabel(symbol: "ellipsis")
                    }
                    .help("More ways to start")
                    .accessibilityLabel("More ways to start")
                }
                .accessibilityElement(children: .contain)
                .accessibilityLabel("Start a note")
            }
        }
        .frame(minHeight: 44)
    }

    private var title: String {
        if let space { return space.name }
        let name = app.identity?.displayName.trimmingCharacters(in: .whitespaces) ?? ""
        // "Good afternoon, Volodymyr" — the first word of a real name, never an e-mail.
        let first = name.contains("@") ? "" : String(name.split(separator: " ").first ?? "")
        return first.isEmpty ? greeting : "\(greeting), \(first)"
    }

    private var searchShown: Bool { searchOpen || !app.searchQuery.isEmpty }

    /// The magnifier opens a search capsule that takes the row; Escape or an empty field closing hands the room back.
    @ViewBuilder
    private var search: some View {
        if searchShown {
            HStack(spacing: 7) {
                Image(systemName: "magnifyingglass")
                    .font(.dsIcon(12, .medium))
                    .foregroundStyle(DS.muted)
                TextField("Search notes", text: $app.searchQuery)
                    .textFieldStyle(.plain)
                    .font(.ds(13.5))
                    .foregroundStyle(DS.text1)
                    .focused($searchFocused)
                    .onExitCommand { closeSearch() }
                if !app.searchQuery.isEmpty {
                    Button { app.searchQuery = "" } label: {
                        Image(systemName: "xmark.circle.fill")
                            .font(.dsIcon(11.5, .regular))
                            .foregroundStyle(DS.muted)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Clear search")
                }
            }
            .padding(.horizontal, 12)
            .frame(minWidth: 220, maxWidth: 340)
            .frame(height: 34)
            .background(Capsule().fill(DS.surface))
            .overlay(Capsule().strokeBorder(searchFocused ? DS.lineActive : DS.line, lineWidth: DS.hairline))
            .onChange(of: searchFocused) { _, focused in
                if !focused, app.searchQuery.isEmpty { searchOpen = false }
            }
            .transition(.opacity)
        } else {
            Button {
                withAnimation(.easeOut(duration: 0.18)) { searchOpen = true }
                DispatchQueue.main.async { searchFocused = true }
            } label: {
                HomeIconLabel(symbol: "magnifyingglass")
            }
            .buttonStyle(.plain)
            .help("Search notes")
            .accessibilityLabel("Search notes")
        }
    }

    private func closeSearch() {
        app.searchQuery = ""
        searchFocused = false
        withAnimation(.easeOut(duration: 0.18)) { searchOpen = false }
    }

    /// The ⋯ beside New meeting: the other ways to start, then what kind of meeting the next one is.
    private func startItems() -> [DSMenuItem] {
        var items = NewNoteMenu.items(app: app, capture: capture)
        items.append(.separator)
        items.append(.header("Kind of meeting"))
        for type in MeetingType.allCases {
            items.append(.item(type.label, checked: capture.meetingType == type) {
                capture.meetingType = type
            })
        }
        return items
    }

    private var greeting: String {
        let hour = Calendar.current.component(.hour, from: Date())
        switch hour {
        case 5..<12: return "Good morning"
        case 12..<18: return "Good afternoon"
        default: return "Good evening"
        }
    }

    // MARK: - Coming up (calendar)

    /// Hidden only when there is nothing to offer: no Google client, nothing connected, and no calendar access.
    private var showComingUp: Bool {
        google.isConnected || google.available != false || google.linkAvailable || calendar.access != .unavailable
    }

    // MARK: - Meetings in flight

    /// This Mac's captures that are not (yet) a note.
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
                HStack(spacing: 10) {
                    DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                    Button("Try again") { Task { await app.refreshNotes() } }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
                }
            }
        } else if notes.isEmpty {
            // No card behind it: the same dotted ground with or without rows.
            section("Notes") {
                VStack(spacing: 6) {
                    Text(emptyTitle)
                        .font(.dsDisplay(16))
                        .foregroundStyle(DS.text1)
                    Text(emptyHint)
                        .font(.dsBody)
                        .foregroundStyle(DS.muted)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 360)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 36)
            }
        } else {
            ForEach(groups(notes), id: \.title) { group in
                section(group.title) {
                    rows(group.items.map { note in
                        AnyView(NoteRow(note: note, trash: { pendingTrash = note }, failed: { accessError = $0 }))
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
        return "Press New meeting when one starts. Stop when it ends and the note is drafted for you."
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

    /// A sentence-case label (Claude's "Active"), the count beside it when given.
    private func section(_ title: String, count: Int? = nil,
                         @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 4) {
                DSSectionLabel(title)
                if let count {
                    Text("\(count)")
                        .font(.ds(13))
                        .foregroundStyle(DS.muted.opacity(0.8))
                        .monospacedDigit()
                }
            }
            .padding(.leading, 4)
            content()
        }
    }

    /// The lists, as Claude's: no card, rows divided by a hairline, a soft fill under the one you point at.
    private func rows(_ items: [AnyView]) -> some View {
        VStack(spacing: 0) {
            ForEach(Array(items.enumerated()), id: \.offset) { index, row in
                row
                if index < items.count - 1 {
                    DSDivider().padding(.horizontal, 12)
                }
            }
        }
    }
}

// MARK: - Rows

/// A note from the tenant: title, status when not a draft, snippet, time.
private struct NoteRow: View {
    @EnvironmentObject private var app: AppState
    let note: NoteSummary
    let trash: () -> Void
    let failed: (String) -> Void
    @State private var hover = false
    @State private var accessMenuOpen = false

    var body: some View {
        Button {
            app.openNote(note.noteId)
        } label: {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 8) {
                        Text(note.title.isEmpty ? "Untitled note" : note.title)
                            .font(.ds(14.5, .medium))
                            .foregroundStyle(DS.text1)
                            .lineLimit(1)
                        if let status = note.status, status != .draft {
                            DSChip(text: status.label, tint: status.tint, soft: status.soft)
                        }
                        if let spaceId = app.spaceOf[note.noteId],
                           app.selectedSpaceId == nil,
                           let space = app.spaces.first(where: { $0.id == spaceId }) {
                            Text(space.name)
                                .font(.ds(10.5, .medium))
                                .foregroundStyle(DS.text3)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Capsule().fill(DS.surface2))
                        }
                    }
                    Text(note.snippet.isEmpty ? "No summary yet" : note.snippet)
                        .font(.ds(12.5))
                        .foregroundStyle(DS.muted)
                        .lineLimit(1)
                }
                Spacer(minLength: 8)
                if hover || accessMenuOpen, let access = note.access {
                    DSMenu(width: 250, onOpenChange: { accessMenuOpen = $0 }, items: { accessItems(access) }) {
                        AccessPill(access: access)
                    }
                }
                Text(note.updatedAt.formatted(date: .omitted, time: .shortened))
                    .font(.ds(12.5))
                    .foregroundStyle(DS.muted)
                    .monospacedDigit()
                DSMenu(width: 220, dim: true, items: menuItems)
                    .opacity(hover ? 1 : 0)
            }
            .padding(.leading, 12)
            .padding(.trailing, 6)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                    .fill(hover ? DS.text1.opacity(0.04) : .clear)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .accessibilityValue(note.access?.help ?? "")
        .contextMenu {
            Button("Open") { app.openNote(note.noteId) }
            Button("Open in Web App") { app.openNoteInBrowser(note.noteId) }
            Divider()
            Button("Move to Trash") { trash() }
        }
    }

    /// The pill's menu: who can open the note. The server decides whether this person may change it.
    private func accessItems(_ access: NoteAccess) -> [DSMenuItem] {
        let id = note.noteId
        var items: [DSMenuItem] = [
            .header("Who can open this note"),
            .item("Private", symbol: "lock", checked: !access.isWorkspace) {
                if access.isWorkspace { run { try await app.setVisibility(noteId: id, workspace: false) } }
            },
            .item("Everyone in the workspace", symbol: "person.2", checked: access.isWorkspace) {
                if !access.isWorkspace { run { try await app.setVisibility(noteId: id, workspace: true) } }
            },
            .separator,
            .header("Public link", hint: access.publicLinkHint),
            .item(access.hasPublicLink ? "Copy public link" : "Create public link", symbol: "globe") {
                run {
                    if let url = try await app.publicLink(noteId: id) { copy(url.absoluteString) }
                }
            },
        ]
        if access.hasPublicLink {
            items.append(.item("Turn off public link", symbol: "xmark.circle") {
                run { try await app.revokePublicLink(noteId: id) }
            })
        }
        return items
    }

    private func run(_ work: @escaping () async throws -> Void) {
        Task {
            do { try await work() } catch { failed(error.localizedDescription) }
        }
    }

    private func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    private func menuItems() -> [DSMenuItem] {
        var items: [DSMenuItem] = [
            .item("Open", symbol: "doc.text") { app.openNote(note.noteId) },
            .item("Open in web app", symbol: "safari") { app.openNoteInBrowser(note.noteId) },
            .item("Copy link", symbol: "link") {
                if let url = app.noteURL(note.noteId) { copy(url.absoluteString) }
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

/// Private or public, shown on hover: the lock (or globe), the word, and a chevron that opens the access menu.
private struct AccessPill: View {
    let access: NoteAccess
    @State private var hover = false

    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: access.symbol)
                .font(.dsIcon(10, .semibold))
            Text(access.label)
                .font(.ds(12, .medium))
                .lineLimit(1)
            if access.hasPublicLink {
                Image(systemName: "globe")
                    .font(.dsIcon(10, .semibold))
                    .help("A public link is on")
            }
            Image(systemName: "chevron.down")
                .font(.dsIcon(8, .bold))
                .opacity(0.75)
        }
        .foregroundStyle(access.isPublic ? DS.accentText : DS.text3)
        .padding(.horizontal, 10)
        .frame(height: 24)
        .background(
            Capsule().fill(access.isPublic ? DS.accentSoft : (hover ? DS.lineHover : DS.surface2))
        )
        .contentShape(Capsule())
        .onHover { hover = $0 }
        .help(access.help)
        .accessibilityLabel(access.help)
    }
}

/// A capture that is not a note yet.
private struct CaptureRow: View {
    @EnvironmentObject private var app: AppState
    let capture: RecentCapture
    @State private var hover = false

    var body: some View {
        Button {
            app.selection = .capture(jobId: capture.jobId)
        } label: {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(capture.title)
                        .font(.ds(14.5, .medium))
                        .foregroundStyle(DS.text1)
                        .lineLimit(1)
                    Text(capture.createdAt.formatted(date: .omitted, time: .shortened))
                        .font(.ds(12.5))
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
                DSMenu(width: 200, dim: true) {
                    var items: [DSMenuItem] = [
                        .item("Copy job ID", symbol: "number") {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(capture.jobId, forType: .string)
                        },
                    ]
                    if capture.status == .queued || capture.status == .running {
                        items.append(.item("Cancel transcription", symbol: "xmark.circle", danger: true) {
                            Task { await app.cancelCapture(jobId: capture.jobId) }
                        })
                    }
                    items.append(.separator)
                    items.append(.item("Remove from list", symbol: "trash", danger: true) {
                        app.removeRecents(jobIds: [capture.jobId])
                    })
                    return items
                }
                .opacity(hover ? 1 : 0)
            }
            .padding(.leading, 12)
            .padding(.trailing, 6)
            .padding(.vertical, 8)
            .background(
                RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                    .fill(hover ? DS.text1.opacity(0.04) : .clear)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
    }
}

/// "Coming up": today's date on the left, the next days' events on the right, from the server's connections and this Mac's calendars merged. One button connects; the ⋯ menu holds the rest.
private struct ComingUpCard: View {
    @EnvironmentObject private var app: AppState
    @ObservedObject var calendar: CalendarService
    @ObservedObject var google: GoogleCalendarService
    @State private var pendingDisconnect: CalendarConnection?
    @State private var addingLink = false

    private var items: [ComingUpItem] {
        ComingUpItem.merge(google: google.events, mac: calendar.access == .granted ? calendar.events : [])
    }

    private var anySource: Bool { google.isConnected || calendar.access == .granted }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                DSSectionLabel("Coming up").padding(.leading, 4)
                Spacer()
                if google.loading, google.isConnected {
                    ProgressView().controlSize(.mini)
                }
                DSMenu(width: 260, dim: true, items: menuItems)
            }
            HStack(alignment: .top, spacing: 20) {
                dateBlock
                    .frame(width: 118, alignment: .leading)
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(google.problems, id: \.connectionId) { problem in
                        problemRow(problem)
                    }
                    content
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(.horizontal, 18)
            .padding(.vertical, 14)
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
                .frame(width: 420)
        }
    }

    private var dateBlock: some View {
        let now = Date()
        return HStack(alignment: .top, spacing: 10) {
            Text(now.formatted(.dateTime.day()))
                .font(.dsSerif(34))
                .foregroundStyle(DS.text1)
                .monospacedDigit()
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 5) {
                    Text(now.formatted(.dateTime.month(.wide)))
                        .font(.ds(13.5, .semibold))
                        .foregroundStyle(DS.text1)
                    Circle().fill(DS.accent).frame(width: 6, height: 6)
                }
                Text(now.formatted(.dateTime.weekday(.abbreviated)))
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
            }
            .padding(.top, 6)
        }
    }

    @ViewBuilder
    private var content: some View {
        if !anySource {
            emptyLine {
                Text("See your next meetings here and start a note from one.")
                    .font(.dsBody)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 8) {
                    if google.available != false {
                        Button(google.connecting ? "Opening Google…" : "Connect Google Calendar") {
                            Task { await google.connect() }
                        }
                        .buttonStyle(DSButtonStyle(kind: .primary, size: 12.5, height: 28))
                        .disabled(google.connecting)
                    }
                    if google.linkAvailable {
                        Button("Add calendar link") { addingLink = true }
                            .buttonStyle(DSButtonStyle(kind: google.available == false ? .primary : .secondary,
                                                       size: 12.5, height: 28))
                    }
                    if calendar.access == .notAsked {
                        Button("Use this Mac's calendars") { Task { await calendar.requestAccess() } }
                            .buttonStyle(DSButtonStyle(kind: .secondary, size: 12.5, height: 28))
                    }
                }
                if let error = google.error {
                    Text(error)
                        .font(.dsMeta)
                        .foregroundStyle(DS.dangerText)
                }
            }
        } else if items.isEmpty {
            emptyLine {
                Text(google.loading && google.events.isEmpty ? "Loading…" : "No upcoming events")
                    .font(.dsBody)
                    .foregroundStyle(DS.muted)
            }
        } else {
            VStack(spacing: 0) {
                ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
                    ComingUpRow(item: item)
                    if index < items.count - 1 {
                        DSDivider()
                    }
                }
            }
        }
    }

    /// A line, not a box: the day column already frames it, so the card stays one row tall.
    private func emptyLine(@ViewBuilder _ inner: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            inner()
        }
        .frame(maxWidth: .infinity, minHeight: 40, alignment: .leading)
        .padding(.leading, 14)
        .overlay(alignment: .leading) {
            Rectangle().fill(DS.line).frame(width: 3)
        }
    }

    private func problemRow(_ problem: CalendarProblem) -> some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.ds(11, .semibold))
                .foregroundStyle(DS.warn)
            Text(problem.needsReauth
                 ? "Google asked to sign in again for \(problem.accountEmail)."
                 : "\(problem.accountEmail): \(problem.message)")
                .font(.ds(12.5))
                .foregroundStyle(DS.text1)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 6)
            if problem.needsReauth {
                Button("Sign in again") { Task { await google.connect(loginHint: problem.accountEmail) } }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
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
            items.append(.item("Use this Mac's calendars", symbol: "desktopcomputer") {
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

/// One upcoming event; hover shows Join (with a video link) and a Start button.
private struct ComingUpRow: View {
    @EnvironmentObject private var capture: CaptureViewModel
    let item: ComingUpItem
    @State private var hover = false

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 1) {
                if !Calendar.current.isDateInToday(item.start) {
                    Text(dayLabel.uppercased())
                        .font(.dsLabel)
                        .tracking(0.5)
                        .foregroundStyle(DS.muted)
                }
                Text(item.isLive ? "Now" : when)
                    .font(.ds(12, item.isLive ? .semibold : .regular))
                    .foregroundStyle(item.isLive ? DS.accentText : DS.text3)
                    .monospacedDigit()
            }
            .frame(width: 124, alignment: .leading)
            Capsule()
                .fill(item.color ?? DS.accent)
                .frame(width: 3, height: 28)
            VStack(alignment: .leading, spacing: 2) {
                Text(item.title)
                    .font(.ds(13.5, .semibold))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                if let detail = item.detail, !detail.isEmpty {
                    Text(detail)
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 8)
            if hover {
                if let url = item.meetingURL {
                    Button {
                        NSWorkspace.shared.open(url)
                    } label: {
                        Label("Join", systemImage: "video")
                    }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
                    .help("Open the video call")
                }
                if !capture.isRecording, !capture.phase.isBusy {
                    Button {
                        capture.startNew(title: item.title, context: item.captureContext,
                                         calendar: item.meetingCalendar)
                    } label: {
                        Label("Start", systemImage: "mic.fill")
                    }
                    .buttonStyle(DSButtonStyle(kind: .primary, size: 12, height: 26))
                    .help("Start a meeting note for this event")
                }
            }
        }
        .padding(.vertical, 10)
        .contentShape(Rectangle())
        .onHover { hover = $0 }
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
        return "\(start) – \(end)"
    }
}

/// "Show 2 more" under a shortened list (`.home-list-more`).
private struct ShowMoreButton: View {
    let title: String
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.ds(12.5))
                .foregroundStyle(hover ? DS.text1 : DS.text3)
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(
                    RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                        .fill(hover ? DS.sidebarHover : .clear)
                )
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .padding(.leading, 4)
    }
}

/// A 34 pt square icon on the home header — the magnifier and the ⋯.
private struct HomeIconLabel: View {
    let symbol: String
    @State private var hover = false

    var body: some View {
        Image(systemName: symbol)
            .font(.dsIcon(13.5, .medium))
            .foregroundStyle(hover ? DS.text1 : DS.text3)
            .frame(width: 34, height: 34)
            .background(
                RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                    .fill(hover ? DS.surface2 : .clear)
            )
            .contentShape(Rectangle())
            .onHover { hover = $0 }
    }
}

/// The one thing a brand-new workspace should do first. Shown once per device; `AppState.dismissFirstRun` remembers.
struct FirstRunCard: View {
    @EnvironmentObject private var app: AppState

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "mic.fill")
                .foregroundStyle(DS.accent)
                .padding(.top, 2)
            VStack(alignment: .leading, spacing: 4) {
                Text("Record your first meeting")
                    .font(.ds(15, .semibold))
                    .foregroundStyle(DS.text1)
                Text("Your notes will be ready to share in minutes.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            Button("Got it") { app.dismissFirstRun() }
                .buttonStyle(.plain)
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
        }
        .dsCard()
    }
}
