import AppKit
import SwiftUI

/// The home page: a greeting, then three lists on a dotted ground —
/// upcoming calendar events (start a meeting from one), meetings still in
/// flight on this Mac, and every note, grouped by day. The sidebar's
/// search and space filter narrow the notes.
struct HomeView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel
    @ObservedObject private var calendar: CalendarService
    @ObservedObject private var google: GoogleCalendarService
    @State private var pendingTrash: NoteSummary?
    @State private var trashError: String?

    init(calendar: CalendarService, google: GoogleCalendarService) {
        self.calendar = calendar
        self.google = google
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                Color.clear.frame(height: DS.titlebarInset - 12)
                header
                if case .idle = capture.phase {} else {
                    ActiveCaptureCard()
                        .dsCard(padding: 16, radius: DS.radiusXl)
                }
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
            .frame(maxWidth: 760, alignment: .leading)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 40)
            .padding(.bottom, 60)
        }
        .background(ZStack { DS.bg; DSDots() }.ignoresSafeArea())
        .task { await app.refreshNotes(); calendar.refresh(); await google.refresh() }
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
    }

    private var searchQuery: String { app.searchQuery.trimmingCharacters(in: .whitespaces) }

    private var space: Space? { app.spaces.first { $0.id == app.selectedSpaceId } }

    // MARK: - Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text(space?.name ?? greeting)
                    .font(.dsDisplay(30))
                    .foregroundStyle(DS.text1)
                Spacer()
                if case .idle = capture.phase {
                    NewMeetingButton(height: 32)
                }
            }
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

    // MARK: - Coming up (calendar)

    /// Hidden only when there is nothing to offer: the server has no
    /// Google client, nothing is connected, and this is a dev binary
    /// without calendar access.
    private var showComingUp: Bool {
        google.isConnected || google.available != false || google.linkAvailable || calendar.access != .unavailable
    }

    // MARK: - Meetings in flight

    /// This Mac's captures that are not (yet) a note: in progress, failed,
    /// or transcribed without a note.
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

// MARK: - Rows

/// A note from the tenant: title, status when not a draft, snippet, time.
private struct NoteRow: View {
    @EnvironmentObject private var app: AppState
    let note: NoteSummary
    let trash: () -> Void
    @State private var hover = false

    var body: some View {
        Button {
            app.openNote(note.noteId)
        } label: {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 8) {
                        Text(note.title.isEmpty ? "Untitled note" : note.title)
                            .font(.ds(13.5, .semibold))
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
                    Text(note.snippet.isEmpty ? note.code : note.snippet)
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .lineLimit(1)
                }
                Spacer(minLength: 8)
                Text(note.updatedAt.formatted(date: .omitted, time: .shortened))
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .monospacedDigit()
                DSMenu(width: 220, dim: true, items: menuItems)
                    .opacity(hover ? 1 : 0)
            }
            .padding(.leading, 16)
            .padding(.trailing, 8)
            .padding(.vertical, 10)
            .background(hover ? DS.surfaceHover : .clear)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .contextMenu {
            Button("Open") { app.openNote(note.noteId) }
            Button("Open in Web App") { app.openNoteInBrowser(note.noteId) }
            Divider()
            Button("Move to Trash") { trash() }
        }
    }

    private func menuItems() -> [DSMenuItem] {
        var items: [DSMenuItem] = [
            .item("Open", symbol: "doc.text") { app.openNote(note.noteId) },
            .item("Open in web app", symbol: "safari") { app.openNoteInBrowser(note.noteId) },
            .item("Copy link", symbol: "link") {
                if let url = app.noteURL(note.noteId) {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(url.absoluteString, forType: .string)
                }
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
    @State private var hover = false

    var body: some View {
        Button {
            app.selection = .capture(jobId: capture.jobId)
        } label: {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(capture.title)
                        .font(.ds(13.5, .semibold))
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
                DSMenu(width: 200, dim: true) {
                    [
                        .item("Copy job ID", symbol: "number") {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(capture.jobId, forType: .string)
                        },
                        .separator,
                        .item("Remove from list", symbol: "trash", danger: true) {
                            app.removeRecents(jobIds: [capture.jobId])
                        },
                    ]
                }
                .opacity(hover ? 1 : 0)
            }
            .padding(.leading, 16)
            .padding(.trailing, 8)
            .padding(.vertical, 10)
            .background(hover ? DS.surfaceHover : .clear)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
    }
}

/// "Coming up": today's date on the left, the next days' events on the
/// right — from the Google accounts and calendar links connected on the
/// server and from this Mac's own calendars, merged. One button connects
/// Google (or adds a link when the server has no Google client); the ⋯
/// menu holds the rest (choose calendars, another account, disconnect).
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
                DSLabel("Coming up").padding(.leading, 4)
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
            .padding(16)
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
                .font(.dsDisplay(34, .medium))
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
            dashed {
                VStack(spacing: 10) {
                    Image(systemName: "calendar.badge.clock")
                        .font(.system(size: 26, weight: .light))
                        .foregroundStyle(DS.muted)
                    Text("See your next meetings here and start a note from one.")
                        .font(.dsBody)
                        .foregroundStyle(DS.muted)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 320)
                    HStack(spacing: 8) {
                        if google.available != false {
                            Button(google.connecting ? "Opening Google…" : "Connect Google Calendar") {
                                Task { await google.connect() }
                            }
                            .buttonStyle(DSButtonStyle(kind: .primary, size: 12.5, height: 30))
                            .disabled(google.connecting)
                        }
                        if google.linkAvailable {
                            Button("Add calendar link") { addingLink = true }
                                .buttonStyle(DSButtonStyle(kind: google.available == false ? .primary : .secondary,
                                                           size: 12.5, height: 30))
                        }
                        if calendar.access == .notAsked {
                            Button("Use this Mac's calendars") { Task { await calendar.requestAccess() } }
                                .buttonStyle(DSButtonStyle(kind: .secondary, size: 12.5, height: 30))
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
                        DSDivider().padding(.leading, 16)
                    }
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous))
            .dsCard(padding: 0, radius: DS.radiusLg)
        }
    }

    private func dashed(@ViewBuilder _ inner: () -> some View) -> some View {
        inner()
            .frame(maxWidth: .infinity, minHeight: 150)
            .padding(20)
            .background(
                RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous)
                    .strokeBorder(style: StrokeStyle(lineWidth: 1.2, dash: [5, 4]))
                    .foregroundStyle(DS.line)
            )
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

/// One upcoming event; hover shows Join (when it has a video link) and a
/// Start button that begins a meeting note with the event's title.
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
            .frame(width: 96, alignment: .leading)
            RoundedRectangle(cornerRadius: 2, style: .continuous)
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
                        capture.startNew(title: item.title)
                    } label: {
                        Label("Start", systemImage: "mic.fill")
                    }
                    .buttonStyle(DSButtonStyle(kind: .primary, size: 12, height: 26))
                    .help("Start a meeting note for this event")
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(hover ? DS.surfaceHover : .clear)
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
