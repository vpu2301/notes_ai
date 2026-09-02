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
    @State private var pendingTrash: NoteSummary?
    @State private var trashError: String?

    init(calendar: CalendarService) {
        self.calendar = calendar
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
                if app.selectedSpaceId == nil, searchQuery.isEmpty, calendar.access != .unavailable {
                    upcoming
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
        .task { await app.refreshNotes(); calendar.refresh() }
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

    // MARK: - Upcoming (calendar)

    @ViewBuilder
    private var upcoming: some View {
        switch calendar.access {
        case .granted:
            if !calendar.events.isEmpty {
                section("Upcoming") {
                    rows(calendar.events.map { AnyView(EventRow(event: $0)) })
                }
            }
        case .notAsked:
            section("Upcoming") {
                promptRow("See your next meetings here and start a note from one.",
                          button: "Connect calendar") {
                    Task { await calendar.requestAccess() }
                }
            }
        case .denied:
            section("Upcoming") {
                promptRow("Calendar access is off for Notes AI in System Settings.",
                          button: "Open System Settings") {
                    if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars") {
                        NSWorkspace.shared.open(url)
                    }
                }
            }
        case .unavailable:
            EmptyView()
        }
    }

    private func promptRow(_ text: String, button: String, action: @escaping () -> Void) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "calendar")
                .font(.system(size: 14, weight: .regular))
                .foregroundStyle(DS.accentText)
            Text(text)
                .font(.dsBody)
                .foregroundStyle(DS.text2)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            Button(button, action: action)
                .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 28))
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .dsCard(padding: 0, radius: DS.radiusLg)
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

/// A calendar event; hover shows a Start button that begins a meeting
/// with the event's title.
private struct EventRow: View {
    @EnvironmentObject private var capture: CaptureViewModel
    let event: CalendarService.Event
    @State private var hover = false

    var body: some View {
        HStack(spacing: 12) {
            RoundedRectangle(cornerRadius: 2, style: .continuous)
                .fill(event.calendarColor.map { Color(cgColor: $0) } ?? DS.accent)
                .frame(width: 3, height: 28)
            VStack(alignment: .leading, spacing: 2) {
                Text(event.title)
                    .font(.ds(13.5, .semibold))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                Text(when)
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
            }
            Spacer(minLength: 8)
            if hover, !capture.isRecording, !capture.phase.isBusy {
                Button {
                    capture.startNew(title: event.title)
                } label: {
                    Label("Start", systemImage: "mic.fill")
                }
                .buttonStyle(DSButtonStyle(kind: .primary, size: 12, height: 26))
                .help("Start a meeting note for this event")
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(hover ? DS.surfaceHover : .clear)
        .contentShape(Rectangle())
        .onHover { hover = $0 }
    }

    private var when: String {
        let day = MeetingGroups.dayTitle(event.start)
        if event.isAllDay { return "\(day) · all day" }
        let start = event.start.formatted(date: .omitted, time: .shortened)
        let end = event.end.formatted(date: .omitted, time: .shortened)
        return "\(day) · \(start) – \(end)"
    }
}
