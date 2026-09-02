import SwiftUI

/// One meeting row (menu-bar popover): title, time, and a status chip only
/// when there is something to say (in progress / failed). Click opens the
/// meeting in the app's window.
struct MeetingRow: View {
    @EnvironmentObject private var app: AppState
    let capture: RecentCapture
    var compact = false

    @State private var hover = false

    var body: some View {
        Button {
            app.select(jobId: capture.jobId)
        } label: {
            rowLabel
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .contextMenu {
            Button("Open") { app.select(jobId: capture.jobId) }
            if let noteId = capture.noteId {
                Button("Open in Web App") { app.openNoteInBrowser(noteId) }
                Button("Copy Note Link") {
                    if let url = app.noteURL(noteId) { copy(url.absoluteString) }
                }
            }
            Button("Copy Job ID") { copy(capture.jobId) }
            Divider()
            Button("Remove from List") { app.removeRecents(jobIds: [capture.jobId]) }
        }
    }

    private var rowLabel: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(capture.title)
                    .font(.ds(13, .medium))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                HStack(spacing: 6) {
                    Text(capture.createdAt.formatted(date: .omitted, time: .shortened))
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                    if let error = capture.errorMessage, !error.isEmpty,
                       capture.status == .failed || capture.noteId == nil {
                        Text("·").font(.dsMeta).foregroundStyle(DS.muted)
                        Text(error)
                            .font(.dsMeta)
                            .foregroundStyle(DS.dangerText)
                            .lineLimit(1)
                    }
                }
            }
            Spacer(minLength: 8)
            statusChip
            DSMenu(width: 220, dim: true, items: menuItems)
                .opacity(hover ? 1 : 0)
            Image(systemName: "chevron.right")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(DS.muted)
        }
        .padding(.leading, compact ? 12 : 16)
        .padding(.trailing, compact ? 8 : 12)
        .padding(.vertical, compact ? 8 : 10)
        .background(hover ? DS.surfaceHover : .clear)
        .contentShape(Rectangle())
    }

    @ViewBuilder
    private var statusChip: some View {
        switch capture.status {
        case .queued, .running:
            DSChip(text: "In progress", tint: DS.info, soft: DS.infoSoft, dot: true)
        case .failed:
            DSChip(text: "Failed", tint: DS.rec, soft: DS.recSoft)
        case .cancelled:
            DSChip(text: "Cancelled", tint: DS.warn, soft: DS.warnSoft)
        case .complete where capture.noteId == nil:
            Button {
                Task { await app.draftNote(for: capture) }
            } label: {
                if app.drafting.contains(capture.jobId) {
                    ProgressView().controlSize(.mini).frame(width: 70)
                } else {
                    Label("Create note", systemImage: "doc.text")
                }
            }
            .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
            .disabled(app.drafting.contains(capture.jobId))
            .help("The transcript is ready but no note was drafted")
        default:
            EmptyView()
        }
    }

    private func menuItems() -> [DSMenuItem] {
        var items: [DSMenuItem] = [
            .item("Open", symbol: "macwindow") { app.select(jobId: capture.jobId) },
        ]
        if let noteId = capture.noteId {
            items.append(.item("Open in web app", symbol: "safari") { app.openNoteInBrowser(noteId) })
            items.append(.item("Copy link", symbol: "link") {
                if let url = app.noteURL(noteId) { copy(url.absoluteString) }
            })
        }
        items.append(.item("Copy job ID", symbol: "number") { copy(capture.jobId) })
        items.append(.separator)
        items.append(.item("Remove from list", symbol: "trash", danger: true) {
            app.removeRecents(jobIds: [capture.jobId])
        })
        return items
    }

    private func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }
}

/// Captures grouped by day, newest first (the popover's list).
struct MeetingList: View {
    @EnvironmentObject private var app: AppState
    var compact = false
    var limit: Int? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: compact ? 10 : 14) {
            ForEach(MeetingGroups.make(app.recents, limit: limit), id: \.title) { group in
                let items = group.items
                VStack(alignment: .leading, spacing: 6) {
                    DSLabel(group.title)
                        .padding(.horizontal, compact ? 12 : 4)
                    VStack(spacing: 0) {
                        ForEach(Array(items.enumerated()), id: \.element.id) { index, item in
                            MeetingRow(capture: item, compact: compact)
                            if index < items.count - 1 {
                                DSDivider().padding(.leading, compact ? 12 : 16)
                            }
                        }
                    }
                    .clipShape(RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous))
                    .background(
                        RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous)
                            .fill(DS.surface)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous)
                            .strokeBorder(DS.line, lineWidth: DS.hairline)
                    )
                }
            }
        }
    }
}

struct MeetingsEmptyState: View {
    var compact = false

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: "waveform")
                .font(.system(size: compact ? 22 : 28))
                .foregroundStyle(DS.muted)
            Text("No meetings yet")
                .font(.dsDisplay(compact ? 15 : 17, .medium))
                .foregroundStyle(DS.text1)
            Text("Press New meeting when one starts. Stop when it ends and the note is drafted for you.")
                .font(.ds(12.5))
                .foregroundStyle(DS.muted)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 300)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, compact ? 28 : 56)
    }
}
