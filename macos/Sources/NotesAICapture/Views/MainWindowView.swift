import AppKit
import SwiftUI

/// The full window: a sidebar of meetings on the left, and on the right
/// whatever is selected — the note itself, opened natively; the live card
/// while a capture is running; or the home pane. Settings is a sheet.
struct MainWindowView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel

    var body: some View {
        Group {
            switch app.authState {
            case .restoring:
                VStack(spacing: 10) {
                    ProgressView().controlSize(.small)
                    Text("Connecting…")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(ZStack { DSWash(); DSDots() })
            case .signedOut:
                SignInView()
                    .dsCard(padding: 24, radius: DS.radiusXl)
                    .frame(width: 380)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(ZStack { DSWash(); DSDots() })
            case .signedIn:
                HStack(spacing: 0) {
                    SidebarView()
                    Rectangle().fill(DS.line).frame(width: DS.hairline).frame(maxHeight: .infinity)
                    detail
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(DS.bg)
                }
            }
        }
        .frame(minWidth: 860, minHeight: 540)
        .sheet(isPresented: $app.settingsPresented) {
            SettingsView(onClose: { app.settingsPresented = false })
                .frame(width: 760, height: 620)
        }
        .onAppear {
            NSApp.setActivationPolicy(.regular)
            NSApp.activate(ignoringOtherApps: true)
        }
        .onDisappear {
            // Back to a menu-bar-only app once the window is gone.
            NSApp.setActivationPolicy(.accessory)
        }
    }

    // MARK: - Detail

    @ViewBuilder
    private var detail: some View {
        switch app.selection {
        case .capture(let jobId):
            if let recent = app.recents.first(where: { $0.jobId == jobId }) {
                if let noteId = recent.noteId {
                    NoteView(capture: recent, noteId: noteId, api: app.api)
                        .id(noteId)
                } else {
                    MeetingStatusPane(row: recent)
                }
            } else {
                HomeView(calendar: app.calendar, google: app.googleCalendar)
            }
        case .note(let noteId):
            NoteView(capture: app.recents.first { $0.noteId == noteId }, noteId: noteId, api: app.api)
                .id(noteId)
        case nil:
            HomeView(calendar: app.calendar, google: app.googleCalendar)
        }
    }
}

// MARK: - A meeting without a note yet

/// Selected a meeting that has no note: the live card if it is the capture
/// in flight, otherwise its status (in progress, failed, transcript ready).
private struct MeetingStatusPane: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var live: CaptureViewModel
    let row: RecentCapture

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Spacer()
                DSMenu(width: 220, items: menuItems)
            }
            .padding(.horizontal, 16)
            .frame(height: DS.topbarHeight)
            DSDivider()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text(row.title)
                        .font(.dsDoc)
                        .foregroundStyle(DS.text1)
                    Text(formatDateTime(row.createdAt))
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                    if isLive {
                        ActiveCaptureCard()
                            .dsCard(padding: 16, radius: DS.radiusXl)
                    } else {
                        status
                    }
                }
                .frame(maxWidth: 680, alignment: .leading)
                .frame(maxWidth: .infinity)
                .padding(.horizontal, 40)
                .padding(.top, 28)
            }
        }
    }

    /// The capture in flight is this row: show the live card, not the status.
    private var isLive: Bool {
        if case .idle = live.phase { return false }
        return live.activeJobId == row.jobId
    }

    @ViewBuilder
    private var status: some View {
        switch row.status {
        case .queued, .running:
            HStack(spacing: 10) {
                ProgressView().controlSize(.small)
                Text("Transcribing… the note appears here when it is ready.")
                    .font(.dsBody)
                    .foregroundStyle(DS.text2)
            }
            .dsCard()
        case .failed, .cancelled:
            DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill",
                     text: row.errorMessage ?? "Transcription failed.")
        case .complete:
            VStack(alignment: .leading, spacing: 12) {
                Text("The transcript is ready but no note was drafted (the app was quit mid-pipeline).")
                    .font(.dsBody)
                    .foregroundStyle(DS.text2)
                    .fixedSize(horizontal: false, vertical: true)
                if let error = row.errorMessage, !error.isEmpty {
                    DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                }
                Button {
                    Task { await app.draftNote(for: row) }
                } label: {
                    if app.drafting.contains(row.jobId) {
                        ProgressView().controlSize(.small).frame(width: 90)
                    } else {
                        Label("Create note", systemImage: "doc.text")
                    }
                }
                .buttonStyle(DSButtonStyle(kind: .primary, height: 30))
                .disabled(app.drafting.contains(row.jobId))
            }
            .dsCard()
        case .none:
            Text("Status unknown — try refreshing.")
                .font(.dsBody)
                .foregroundStyle(DS.muted)
        }
    }

    private func menuItems() -> [DSMenuItem] {
        [
            .item("Copy job ID", symbol: "number") {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(row.jobId, forType: .string)
            },
            .separator,
            .item("Remove from list", symbol: "trash", danger: true) {
                app.removeRecents(jobIds: [row.jobId])
            },
        ]
    }
}
