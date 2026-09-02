import SwiftUI

struct RecentsView: View {
    @EnvironmentObject private var app: AppState

    var body: some View {
        Group {
            if app.recents.isEmpty {
                emptyState
            } else {
                ScrollView {
                    VStack(spacing: 6) {
                        ForEach(app.recents) { recent in
                            RecentRow(recent: recent)
                        }
                    }
                    .padding(12)
                }
                .frame(maxHeight: 340)
            }
        }
        .task { await app.refreshRecents() }
    }

    private var emptyState: some View {
        VStack(spacing: 10) {
            Image(systemName: "tray")
                .font(.system(size: 30))
                .foregroundStyle(.tertiary)
            Text("No captures yet")
                .font(.callout.weight(.medium))
            Text("Your last 10 recordings will appear here.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 36)
    }
}

private struct RecentRow: View {
    @EnvironmentObject private var app: AppState
    let recent: RecentCapture

    var body: some View {
        HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 3) {
                Text(recent.title)
                    .font(.callout.weight(.medium))
                    .lineLimit(1)
                HStack(spacing: 6) {
                    Text(recent.createdAt.formatted(.relative(presentation: .named)))
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    StatusChip(status: recent.status)
                }
            }
            Spacer()
            if let noteId = recent.noteId {
                Button {
                    app.openNote(noteId)
                } label: {
                    Image(systemName: "arrow.up.right.square")
                        .font(.system(size: 15))
                }
                .buttonStyle(.plain)
                .foregroundStyle(Color.accentColor)
                .help("Open note in the web app")
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(.ultraThinMaterial)
        )
        .help(recent.errorMessage ?? recent.title)
    }
}
