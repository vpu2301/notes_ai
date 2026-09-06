import SwiftUI

/// Recordings that were made but never reached the server.
///
/// IDX-I1 started keeping them; this is where the person finally gets to
/// do something about them. Three actions, and the reason there are
/// exactly three: **Retry** is what they want, **Export** is what they
/// want when retrying cannot work (no workspace left, a server that will
/// not take it), and **Delete** is the only path in this app that destroys
/// a recording — behind a confirmation, because it cannot be undone and
/// the meeting cannot be held again.
struct PendingUploadsSection: View {
    @EnvironmentObject private var app: AppState
    let captures: [PendingCapture]
    /// "Old recordings": another identity's, kept more than 30 days.
    var stale = false

    @State private var exporting: PendingCapture?
    @State private var deleting: PendingCapture?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Text(stale ? "Old recordings" : "Recordings waiting")
                    .font(.ds(13, .semibold))
                    .foregroundStyle(DS.text3)
                    .textCase(.uppercase)
                    .kerning(0.4)
                Spacer()
                DSChip(text: "\(captures.count)", tint: DS.warn, soft: DS.warnSoft)
            }
            Text(stale
                 ? "Recorded by another account on this phone. They are kept until somebody decides what to happen to them."
                 : "These could not be uploaded. Open the app on Wi‑Fi to finish sending them — nothing uploads while Notes AI is in the background.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
            VStack(spacing: 0) {
                ForEach(Array(captures.enumerated()), id: \.element.id) { index, capture in
                    if index > 0 { DSDivider() }
                    PendingUploadRow(capture: capture, stale: stale,
                                     export: { exporting = capture },
                                     delete: { deleting = capture })
                }
            }
            .dsCard(padding: 0)
        }
        .sheet(item: $exporting) { capture in
            ShareSheet(items: [capture.audioURL])
        }
        .confirmationDialog(
            "Delete this recording?",
            isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }),
            titleVisibility: .visible,
            presenting: deleting
        ) { capture in
            Button("Delete recording", role: .destructive) {
                app.deletePending(capture)
                deleting = nil
            }
            Button("Keep it", role: .cancel) { deleting = nil }
        } message: { capture in
            Text("“\(capture.info.title)” has not been uploaded. Deleting it here is the only copy gone — export it first if you might want it.")
        }
    }
}

private struct PendingUploadRow: View {
    @EnvironmentObject private var app: AppState
    let capture: PendingCapture
    let stale: Bool
    let export: () -> Void
    let delete: () -> Void

    private var isRetrying: Bool { app.retrying.contains(capture.id) }
    private var error: String? { app.pendingErrors[capture.id] }
    /// Its workspace is one this identity has left, or never had.
    private var needsWorkspace: Bool { !stale && !app.canRetry(capture) }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Image(systemName: "waveform")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(needsWorkspace ? DS.warn : DS.accentText)
                    .frame(width: 32, height: 32)
                    .background(RoundedRectangle(cornerRadius: 9, style: .continuous)
                        .fill(needsWorkspace ? DS.warnSoft : DS.accentSoft))
                VStack(alignment: .leading, spacing: 2) {
                    Text(capture.info.title)
                        .font(.ds(15, .medium))
                        .foregroundStyle(DS.text1)
                        .lineLimit(1)
                    Text(subtitle)
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
                if !stale {
                    Button {
                        Task { await app.retryPending(capture) }
                    } label: {
                        if isRetrying {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("Retry")
                        }
                    }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 32))
                    .disabled(isRetrying || needsWorkspace || app.authState != .signedIn)
                }
                DSMenu(items: menuItems) {
                    Image(systemName: "ellipsis")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(DS.muted)
                        .frame(width: 30, height: 30)
                        .contentShape(Rectangle())
                }
            }
            if needsWorkspace {
                DSNotice(tone: .warn, symbol: "person.crop.circle.badge.exclamationmark",
                         text: "This recording was made for a workspace you are no longer in. Send it to another workspace, or export it.")
            } else if let error {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
            }
        }
        .padding(14)
    }

    private var subtitle: String {
        var parts = [relativeTime(capture.info.recordedAt)]
        if let workspace = workspaceName { parts.append(workspace) }
        return parts.joined(separator: " · ")
    }

    private var workspaceName: String? {
        guard let tenantId = capture.info.tenantId, !tenantId.isEmpty else { return nil }
        return app.workspaces.first { $0.id == tenantId }?.title ?? "Another workspace"
    }

    private func menuItems() -> [DSMenuItem] {
        var items: [DSMenuItem] = [
            .item("Export…", symbol: "square.and.arrow.up", action: export),
        ]
        // Re-targeting is offered whenever there is somewhere else to send
        // it — the usual reason is a lost membership, but a recording made
        // in the wrong workspace is just as real a mistake.
        let elsewhere = app.availableWorkspaces.filter { $0.id != capture.info.tenantId }
        if !stale, !elsewhere.isEmpty {
            items.append(.separator)
            items.append(.header("Send to"))
            for workspace in elsewhere {
                items.append(.item(workspace.title, symbol: "building.2") {
                    app.retargetPending(capture, to: workspace)
                })
            }
        }
        items.append(.separator)
        items.append(.item("Delete recording…", symbol: "trash", danger: true, action: delete))
        return items
    }
}

// MARK: - When the workspace is gone

/// The membership behind the open workspace was removed.
///
/// Nothing local is deleted: the notes list empties because the server
/// stops answering for that tenant, but the recordings this phone kept are
/// still the person's, and the way out is to move to a workspace they are
/// still in.
struct WorkspaceLostBanner: View {
    @EnvironmentObject private var app: AppState
    @State private var picking = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSNotice(tone: .danger, symbol: "person.crop.circle.badge.xmark",
                     text: "You are no longer a member of \(app.activeWorkspace?.title ?? "this workspace"). Notes here are not available to you any more.")
            HStack(spacing: 10) {
                if !app.availableWorkspaces.isEmpty {
                    Button("Switch workspace") { picking = true }
                        .buttonStyle(DSButtonStyle(kind: .primary, size: 14, height: 36))
                }
                Button("Sign out") { Task { await app.signOut() } }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 36))
            }
        }
        .sheet(isPresented: $picking) { WorkspacePicker() }
    }
}
