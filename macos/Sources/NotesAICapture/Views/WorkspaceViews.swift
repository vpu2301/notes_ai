import AppKit
import SwiftUI

/// The workspace switcher, as a list of memberships with the active one
/// marked. Used in the sidebar's account menu and in Settings › Account.
struct WorkspaceList: View {
    @EnvironmentObject private var app: AppState
    var onSwitch: (() -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if app.workspaces.isEmpty {
                Text("No other workspaces.")
                    .font(.ds(12.5))
                    .foregroundStyle(DS.muted)
            }
            ForEach(app.workspaces, id: \.id) { workspace in
                row(workspace)
            }
        }
    }

    private func row(_ workspace: Tenant) -> some View {
        let active = workspace.id == app.tenantId
        let busy = app.switchingTo == workspace.id
        return Button {
            guard !active else { return }
            onSwitch?()
            Task { await app.switchWorkspace(to: workspace.id) }
        } label: {
            HStack(spacing: 10) {
                DSAvatar(name: workspace.title, size: 24)
                VStack(alignment: .leading, spacing: 1) {
                    Text(workspace.title)
                        .font(.ds(13, .medium))
                        .foregroundStyle(DS.text1)
                        .lineLimit(1)
                    Text(workspace.myRole?.capitalized ?? "")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                }
                Spacer()
                if busy {
                    ProgressView().controlSize(.small)
                } else if active {
                    Image(systemName: "checkmark")
                        .font(.ds(11, .semibold))
                        .foregroundStyle(DS.accentText)
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .fill(active ? DS.surface2 : .clear)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(app.switchingTo != nil)
    }
}

/// The line that appears when a workspace stops being reachable, a switch
/// fails, or a link arrives that this server cannot honour.
struct WorkspaceNoticeBanner: View {
    @EnvironmentObject private var app: AppState
    let text: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "person.2.slash")
                .font(.ds(12, .semibold))
                .foregroundStyle(DS.warn)
            Text(text)
                .font(.ds(12))
                .foregroundStyle(DS.text2)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            Button("Dismiss") { app.workspaceNotice = nil }
                .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 24))
                .foregroundStyle(DS.muted)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(DS.warnSoft)
    }
}

// MARK: - Pending uploads

/// The recordings this Mac is still holding, and the four things that can
/// be done with one: send it, send it somewhere else, save it, forget it.
///
/// It is deliberately a section of the home page rather than a corner of
/// Settings: a meeting that has not been sent is not a setting, it is
/// work in progress.
struct PendingUploadsSection: View {
    @EnvironmentObject private var app: AppState
    @ObservedObject var pending: PendingUploads
    /// On the sign-in screen there is no session, so only Export and
    /// Delete are offered.
    var canSend = true

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                DSLabel("Not uploaded yet")
                Spacer()
                if pending.isRetrying {
                    ProgressView().controlSize(.small)
                } else if canSend, pending.rows.contains(where: { $0.state == .waiting }) {
                    Button("Send all") { Task { await pending.retryAll() } }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 24))
                }
            }
            ForEach(pending.rows) { row in
                PendingUploadRow(pending: pending, row: row, canSend: canSend)
            }
            Text("These stay on this Mac until they are sent or you remove them.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dsCard()
        .task { pending.reload() }
    }
}

private struct PendingUploadRow: View {
    @EnvironmentObject private var app: AppState
    @ObservedObject var pending: PendingUploads
    let row: PendingUploads.Row
    var canSend: Bool

    @State private var confirmingDelete = false

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: symbol)
                .font(.ds(13))
                .foregroundStyle(tint)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 1) {
                Text(row.title)
                    .font(.ds(13, .medium))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                Text(subtitle)
                    .font(.dsMeta)
                    .foregroundStyle(tint == DS.muted ? DS.muted : tint)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            controls
        }
        .padding(.vertical, 4)
        .alert("Delete this recording?", isPresented: $confirmingDelete) {
            Button("Delete", role: .destructive) { pending.delete(row.capture) }
            Button("Keep", role: .cancel) {}
        } message: {
            Text("“\(row.title)” has not been uploaded. Deleting it here removes the only copy.")
        }
    }

    @ViewBuilder
    private var controls: some View {
        if case .uploading = row.state {
            ProgressView().controlSize(.small)
        } else {
            HStack(spacing: 6) {
                if canSend {
                    if case .needsWorkspace = row.state {
                        retargetMenu
                    } else {
                        Button("Send") { Task { await pending.retry(row.capture) } }
                            .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 24))
                    }
                }
                DSMenu(width: 200) { menuItems }
            }
        }
    }

    /// The repair for "the workspace this was recorded in is gone".
    private var retargetMenu: some View {
        DSMenu(width: 240, items: {
            app.workspaces.map { workspace in
                DSMenuItem.item(workspace.title, symbol: "building.2") {
                    Task { await pending.retarget(row.capture, to: workspace.id) }
                }
            }
        }, label: {
            Text("Send to…")
                .font(.ds(12, .medium))
                .foregroundStyle(DS.text1)
                .padding(.horizontal, 10)
                .frame(height: 24)
                .background(
                    RoundedRectangle(cornerRadius: DS.radius, style: .continuous).fill(DS.surface)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                        .strokeBorder(DS.line, lineWidth: DS.hairline)
                )
        })
    }

    private var menuItems: [DSMenuItem] {
        [
            .item("Export…", symbol: "square.and.arrow.down") { export() },
            .item("Show in Finder", symbol: "folder") {
                NSWorkspace.shared.activateFileViewerSelecting([row.capture.audioURL])
            },
            .separator,
            .item("Delete", symbol: "trash", danger: true) { confirmingDelete = true },
        ]
    }

    private func export() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = PendingCaptures.exportName(row.capture)
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let url = panel.url else { return }
        pending.export(row.capture, to: url)
    }

    private var subtitle: String {
        switch row.state {
        case .waiting:
            return "\(formatDateTime(row.capture.info.recordedAt)) · \(size)"
        case .uploading:
            return "Sending…"
        case .failed(let message):
            return message
        case .needsWorkspace(let message):
            return message + " Choose another workspace, or export it."
        }
    }

    private var size: String {
        ByteCountFormatter.string(fromByteCount: row.capture.byteCount, countStyle: .file)
    }

    private var symbol: String {
        switch row.state {
        case .needsWorkspace: return "person.2.slash"
        case .failed: return "exclamationmark.triangle.fill"
        default: return "waveform"
        }
    }

    private var tint: Color {
        switch row.state {
        case .needsWorkspace, .failed: return DS.warn
        default: return DS.muted
        }
    }
}

// MARK: - Sessions

/// Where this account is signed in, and how to end one of them.
///
/// The list is the answer to a question people only ask when something is
/// wrong ("is someone else in my account?"), so it is worth being able to
/// answer it from the Mac rather than only from the web app.
struct SessionsList: View {
    @EnvironmentObject private var app: AppState

    @State private var sessions: [AuthSessionSummary] = []
    @State private var loading = true
    @State private var error: String?
    @State private var busy: String?
    @State private var revokedOthers: Int?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                DSLabel("Signed in on")
                Spacer()
                if loading {
                    ProgressView().controlSize(.small)
                } else if sessions.count > 1 {
                    Button("Sign out everywhere else") { Task { await revokeOthers() } }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 24))
                        .disabled(busy != nil)
                }
            }
            if let error {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
            }
            if let revokedOthers {
                DSNotice(tone: .ok, symbol: "checkmark.circle.fill",
                         text: revokedOthers == 0
                            ? "No other sessions were open."
                            : "Ended \(revokedOthers) other session\(revokedOthers == 1 ? "" : "s").")
            }
            ForEach(sessions) { session in
                row(session)
            }
        }
        .task { await load() }
    }

    private func row(_ session: AuthSessionSummary) -> some View {
        HStack(spacing: 10) {
            Image(systemName: symbol(session))
                .font(.ds(13))
                .foregroundStyle(session.current ? DS.accentText : DS.muted)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 1) {
                Text(session.title)
                    .font(.ds(13, .medium))
                    .foregroundStyle(DS.text1)
                Text("\(session.ipLast) · last used \(formatDateTime(session.lastUsedAt))")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .lineLimit(1)
            }
            Spacer()
            if busy == session.sid {
                ProgressView().controlSize(.small)
            } else if !session.current {
                Button("End") { Task { await revoke(session) } }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 24))
                    .foregroundStyle(DS.danger)
                    .disabled(busy != nil)
            }
        }
    }

    private func symbol(_ session: AuthSessionSummary) -> String {
        switch session.clientType {
        case "macos": return "laptopcomputer"
        case "ios": return "iphone"
        default: return "globe"
        }
    }

    private func load() async {
        loading = true
        defer { loading = false }
        do {
            sessions = try await app.api.sessions()
            error = nil
        } catch {
            // A deployment without the native account surface answers 404;
            // that is a fact about the server, not a failure to report in
            // red every time this tab opens.
            if (error as? APIError)?.isNotFound == true {
                sessions = []
                self.error = nil
            } else {
                self.error = AuthCopy.message(for: error)
            }
        }
    }

    private func revoke(_ session: AuthSessionSummary) async {
        busy = session.sid
        defer { busy = nil }
        do {
            try await app.api.revokeSession(sid: session.sid)
            await load()
        } catch {
            self.error = AuthCopy.message(for: error)
        }
    }

    private func revokeOthers() async {
        busy = "others"
        defer { busy = nil }
        do {
            // Gated on recent proof of identity: the step-up sheet appears
            // first, and the request is retried once when it is answered.
            revokedOthers = try await app.api.revokeOtherSessions()
            await load()
        } catch APIError.reauthRequired {
            error = "Confirm it is you to end other sessions."
        } catch {
            self.error = AuthCopy.message(for: error)
        }
    }
}
