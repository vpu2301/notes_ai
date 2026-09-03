import SwiftUI

/// A meeting that has no note yet: its progress while the capture is in
/// flight, its failure, or a Create note button when the transcript
/// finished without a note.
struct MeetingStatusView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var live: CaptureViewModel
    let row: RecentCapture

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text(row.title)
                    .font(.dsDoc)
                    .foregroundStyle(DS.text1)
                Text(formatDateTime(row.createdAt))
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                if isLive {
                    liveCard
                } else {
                    status
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, DS.gutter)
            .padding(.top, 12)
            .padding(.bottom, 40)
        }
        .background(DS.bg)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                DSMenu(items: menuItems)
            }
        }
    }

    /// The capture in flight is this row: the bar below shows it live, so
    /// the page only says what is happening.
    private var isLive: Bool {
        if case .idle = live.phase { return false }
        return live.activeJobId == row.jobId
    }

    private var liveCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            PipelineSteps(phase: live.phase)
            Text("The note appears here when it is ready.")
                .font(.dsBody)
                .foregroundStyle(DS.text2)
        }
        .dsCard()
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
                Text("The transcript is ready but no note was drafted (the app was closed mid-pipeline).")
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
                        ProgressView().tint(DS.inkText).frame(width: 100)
                    } else {
                        Label("Create note", systemImage: "doc.text")
                    }
                }
                .buttonStyle(DSButtonStyle(kind: .primary, height: 40))
                .disabled(app.drafting.contains(row.jobId))
            }
            .dsCard()
        case .none:
            Text("Status unknown — pull down on the home page to refresh.")
                .font(.dsBody)
                .foregroundStyle(DS.muted)
        }
    }

    private func menuItems() -> [DSMenuItem] {
        [
            .item("Copy job ID", symbol: "number") { copyToPasteboard(row.jobId) },
            .separator,
            .item("Remove from list", symbol: "trash", danger: true) {
                app.removeRecents(jobIds: [row.jobId])
            },
        ]
    }
}
