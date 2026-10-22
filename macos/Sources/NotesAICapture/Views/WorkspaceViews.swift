import AppKit
import SwiftUI

/// The workspace switcher: memberships with the active one marked. Sidebar account menu and Settings › Account;
/// with `manage` (Settings only) each team workspace can also be left, archived or (the open one) deleted by its owner.
/// Archived ones the person owns are listed apart, with Restore.
struct WorkspaceList: View {
    @EnvironmentObject private var app: AppState
    var onSwitch: (() -> Void)? = nil
    var manage = false

    @State private var leaving: Tenant?
    @State private var archiving: Tenant?
    /// Delete first offers archiving; only "Delete anyway" reaches the type-the-name step.
    @State private var deleteOffer: Tenant?
    @State private var dissolving: Tenant?
    @State private var dissolveName = ""
    @State private var working: String?
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if app.workspaces.isEmpty {
                Text("No other workspaces.")
                    .font(.ds(12.5))
                    .foregroundStyle(DS.muted)
            }
            ForEach(app.workspaces, id: \.id) { workspace in
                HStack(spacing: 4) {
                    row(workspace)
                    if manage, !workspace.isPersonal {
                        if working == workspace.id {
                            ProgressView().controlSize(.small).frame(width: 24)
                        } else {
                            DSMenu(width: 200, dim: true) { actions(workspace) }
                        }
                    }
                }
            }
            if !app.archivedWorkspaces.isEmpty {
                DSLabel("Archived")
                    .padding(.top, 6)
                ForEach(app.archivedWorkspaces, id: \.id) { workspace in
                    archivedRow(workspace)
                }
            }
            if let error {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
            }
        }
        .alert("Archive \(archiving?.title ?? "")?",
               isPresented: Binding(get: { archiving != nil }, set: { if !$0 { archiving = nil } })) {
            Button("Archive") {
                guard let workspace = archiving else { return }
                run(workspace) { await app.archive(workspace) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Nobody can open it until you restore it. Notes and members stay as they are; open invitations are cancelled.")
        }
        .alert("Archive \(deleteOffer?.title ?? "") instead?",
               isPresented: Binding(get: { deleteOffer != nil }, set: { if !$0 { deleteOffer = nil } })) {
            Button("Archive instead") {
                guard let workspace = deleteOffer else { return }
                run(workspace) { await app.archive(workspace) }
            }
            .keyboardShortcut(.defaultAction)
            Button("Delete anyway…", role: .destructive) {
                guard let workspace = deleteOffer else { return }
                dissolveName = ""
                // The next alert can only present once this one is gone.
                DispatchQueue.main.async { dissolving = workspace }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Archiving closes it for everyone just like deleting, but keeps every note and member. You can restore it any time.")
        }
        .alert("Leave \(leaving?.title ?? "")?",
               isPresented: Binding(get: { leaving != nil }, set: { if !$0 { leaving = nil } })) {
            Button("Leave", role: .destructive) {
                guard let workspace = leaving else { return }
                run(workspace) { await app.leave(workspace) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("You lose access to its notes and meetings until someone invites you again.")
        }
        .alert("Delete \(dissolving?.title ?? "")?",
               isPresented: Binding(get: { dissolving != nil }, set: { if !$0 { dissolving = nil } })) {
            TextField("Workspace name", text: $dissolveName)
            Button("Delete", role: .destructive) {
                guard let workspace = dissolving else { return }
                let typed = dissolveName
                run(workspace) { await app.dissolve(workspace, confirmName: typed) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Type the workspace name to confirm. Remove everyone else first; nobody can open it afterwards.")
        }
    }

    /// Leave for any team workspace; archive for one you own; delete for the open one you own. The server has the last word.
    private func actions(_ workspace: Tenant) -> [DSMenuItem] {
        var items: [DSMenuItem] = [
            .item("Leave workspace…", symbol: "rectangle.portrait.and.arrow.right") { leaving = workspace },
        ]
        if workspace.myRole == "owner" {
            items.append(.item("Archive…", symbol: "archivebox") { archiving = workspace })
        }
        if workspace.myRole == "owner", workspace.id == app.tenantId {
            items.append(.item("Delete…", symbol: "trash", danger: true) { deleteOffer = workspace })
        }
        return items
    }

    /// Not enterable: the name, dimmed, and Restore.
    private func archivedRow(_ workspace: Tenant) -> some View {
        HStack(spacing: 10) {
            DSAvatar(name: workspace.title, size: 24)
                .opacity(0.55)
            Text(workspace.title)
                .font(.ds(13, .medium))
                .foregroundStyle(DS.text3)
                .lineLimit(1)
            Spacer()
            if working == workspace.id {
                ProgressView().controlSize(.small)
            } else {
                Button("Restore") { run(workspace) { await app.unarchive(workspace) } }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 24))
                    .disabled(working != nil)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
    }

    private func run(_ workspace: Tenant, _ work: @escaping () async -> String?) {
        working = workspace.id
        error = nil
        Task {
            error = await work()
            working = nil
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
                    Text(workspace.switcherTitle)
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

/// The line shown when a workspace stops being reachable, a switch fails, or a link cannot be honoured;
/// with `good`, a membership change the person made ("You joined …").
struct WorkspaceNoticeBanner: View {
    @EnvironmentObject private var app: AppState
    let text: String
    var good = false

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: good ? "person.2" : "person.2.slash")
                .font(.ds(12, .semibold))
                .foregroundStyle(good ? DS.accentText : DS.warn)
            Text(text)
                .font(.ds(12))
                .foregroundStyle(DS.text2)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            Button("Dismiss") {
                if good { app.membershipNotice = nil } else { app.workspaceNotice = nil }
            }
                .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 24))
                .foregroundStyle(DS.muted)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(good ? DS.accentSoft : DS.warnSoft)
    }
}

// MARK: - Creating, joining (W2)

/// "New workspace…": a name, then the Mac is in it.
struct NewWorkspaceSheet: View {
    @EnvironmentObject private var app: AppState
    let onClose: () -> Void

    @State private var name = ""
    @State private var creating = false
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("New workspace")
                .font(.dsDisplay(18, .medium))
                .foregroundStyle(DS.text1)
            Text("A shared place for a team's notes and meetings. You can invite people once you are in it.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
            DSTextField(placeholder: "Sunrise Studio", text: $name)
                .onSubmit { Task { await create() } }
            if let error {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
            }
            HStack {
                Spacer()
                Button("Cancel", action: onClose)
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                    .keyboardShortcut(.cancelAction)
                Button {
                    Task { await create() }
                } label: {
                    if creating {
                        ProgressView().controlSize(.small).frame(width: 60)
                    } else {
                        Text("Create")
                    }
                }
                .buttonStyle(DSButtonStyle(kind: .primary, height: 28))
                .keyboardShortcut(.defaultAction)
                .disabled(creating || trimmed.isEmpty)
            }
        }
        .padding(20)
        .frame(width: 400)
        .background(DS.bg)
    }

    private var trimmed: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }

    private func create() async {
        guard !trimmed.isEmpty, !creating else { return }
        creating = true
        error = await app.createWorkspace(named: trimmed)
        creating = false
        if error == nil { onClose() }
    }
}

/// Invitations addressed to this person: join with one click, or decline.
struct InvitationsSheet: View {
    @EnvironmentObject private var app: AppState
    let onClose: () -> Void

    @State private var busy: String?
    @State private var error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Invitations")
                    .font(.dsDisplay(18, .medium))
                    .foregroundStyle(DS.text1)
                Spacer()
                Button("Done", action: onClose)
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 26))
                    .keyboardShortcut(.cancelAction)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)
            DSDivider()
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    if app.myInvitations.isEmpty {
                        Text("No open invitations.")
                            .font(.dsBody)
                            .foregroundStyle(DS.muted)
                    }
                    ForEach(app.myInvitations) { invite in
                        row(invite)
                    }
                    if let error {
                        DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                    }
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .background(DS.bg)
        .task { await app.refreshMyInvitations(force: true) }
    }

    private func row(_ invite: MyInvitation) -> some View {
        HStack(spacing: 10) {
            DSAvatar(name: invite.workspaceName, size: 28)
            VStack(alignment: .leading, spacing: 1) {
                Text(invite.workspaceName)
                    .font(.ds(13, .medium))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                Text("\(invite.inviterDisplay) invited you \(WorkspaceRoles.asPhrase(invite.role))")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
            if busy == invite.id {
                ProgressView().controlSize(.small)
            } else {
                Button("Decline") { run(invite) { await app.decline(invite) } }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 26))
                    .foregroundStyle(DS.muted)
                Button("Accept") { run(invite, closes: true) { await app.accept(invite) } }
                    .buttonStyle(DSButtonStyle(kind: .primary, size: 12, height: 26))
            }
        }
        .disabled(busy != nil)
        .dsCard(padding: 12)
    }

    private func run(_ invite: MyInvitation, closes: Bool = false, _ work: @escaping () async -> String?) {
        busy = invite.id
        error = nil
        Task {
            error = await work()
            busy = nil
            // Accepting moves the Mac into the workspace; close onto it.
            if error == nil, closes { onClose() }
        }
    }
}

/// What an invitation link opens: who invited you where, and one button. Nothing is granted
/// unless the signed-in address is the invited one.
struct InviteLandingSheet: View {
    @EnvironmentObject private var app: AppState
    let landing: InvitationLanding

    /// The live state (the sheet's item is a snapshot).
    private var state: InvitationLandingState { app.invitation?.state ?? landing.state }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Invitation")
                    .font(.dsDisplay(18, .medium))
                    .foregroundStyle(DS.text1)
                Spacer()
                Button("Close") { app.invitation = nil }
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 26))
                    .keyboardShortcut(.cancelAction)
            }
            content
        }
        .padding(20)
        .frame(width: 420)
        .background(DS.bg)
    }

    @ViewBuilder
    private var content: some View {
        switch state {
        case .loading:
            ProgressView().controlSize(.small).frame(maxWidth: .infinity, minHeight: 80)
        case .invalid:
            DSNotice(tone: .info, symbol: "envelope.badge",
                     text: "This invitation is no longer valid. Ask the person who invited you for a new one.")
        case .ready(let lookup):
            card(lookup)
            if app.authState == .signedIn {
                primary("Join \(lookup.workspaceName)") { Task { await app.joinInvitation() } }
            } else {
                primary("Continue as \(lookup.emailMasked)") { Task { await app.joinInvitation() } }
                Text("Sign in, or create an account, with that address. You join right after.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
            }
        case .joining(let lookup):
            card(lookup)
            HStack {
                Spacer()
                ProgressView().controlSize(.small)
            }
        case .mismatch(let lookup, let signedInAs):
            card(lookup)
            DSNotice(tone: .warn, symbol: "person.crop.circle.badge.exclamationmark",
                     text: "You're signed in as \(signedInAs). This invitation is for \(lookup.emailMasked); nothing was shared.")
            primary("Sign out and continue as \(lookup.emailMasked)") { app.signOutForInvitation() }
        case .failed(let lookup, let message):
            if let lookup { card(lookup) }
            DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: message)
            primary("Try again") {
                Task {
                    if lookup == nil {
                        await app.openInvitation(token: landing.token)
                    } else {
                        await app.joinInvitation()
                    }
                }
            }
        }
    }

    private func card(_ lookup: InvitationLookup) -> some View {
        HStack(spacing: 12) {
            DSAvatar(name: lookup.workspaceName, size: 34)
            VStack(alignment: .leading, spacing: 2) {
                Text("\(lookup.inviterDisplay) invited you to")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                Text(lookup.workspaceName)
                    .font(.ds(15, .semibold))
                    .foregroundStyle(DS.text1)
                    .lineLimit(2)
                Text("\(WorkspaceRoles.label(lookup.role)) · for \(lookup.emailMasked)")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
            }
            Spacer(minLength: 0)
        }
        .dsCard(padding: 12)
    }

    private func primary(_ title: String, action: @escaping () -> Void) -> some View {
        HStack {
            Spacer()
            Button(action: action) { Text(title).lineLimit(1) }
                .buttonStyle(DSButtonStyle(kind: .primary, height: 30))
                .keyboardShortcut(.defaultAction)
        }
    }
}

// MARK: - Pending uploads

/// The recordings this Mac is still holding: send, send elsewhere, save, forget. A section of the home page, not Settings: an unsent meeting is work in progress.
struct PendingUploadsSection: View {
    @ObservedObject var pending: PendingUploads
    /// On the sign-in screen there is no session, so only Export and Delete are offered.
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
            // A deployment without the native account surface answers 404; not an error to report in red.
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
            // Gated on recent proof of identity: the step-up sheet appears first, then one retry.
            revokedOthers = try await app.api.revokeOtherSessions()
            await load()
        } catch APIError.reauthRequired {
            error = "Confirm it is you to end other sessions."
        } catch {
            self.error = AuthCopy.message(for: error)
        }
    }
}

// MARK: - Meeting notes whose workspace refused them

/// Typed offline for a workspace this identity is no longer in. The file stays until moved.
struct OrphanedMeetingNotesSection: View {
    @EnvironmentObject private var app: AppState
    let notes: [PendingMeetingNote]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSLabel("Meeting notes not synced")
            ForEach(notes, id: \.clientCaptureId) { note in
                HStack(spacing: 10) {
                    Image(systemName: "person.2.slash")
                        .font(.ds(13))
                        .foregroundStyle(DS.warn)
                        .frame(width: 18)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(note.title.isEmpty ? "Meeting notes" : note.title)
                            .font(.ds(13, .medium))
                            .foregroundStyle(DS.text1)
                            .lineLimit(1)
                        Text(app.personalWorkspace == nil
                             ? "Workspace no longer available."
                             : "Workspace no longer available — move to Personal?")
                            .font(.dsMeta)
                            .foregroundStyle(DS.warn)
                    }
                    Spacer(minLength: 8)
                    if app.personalWorkspace != nil {
                        Button("Move to Personal") {
                            Task { await app.moveMeetingNoteToPersonal(note) }
                        }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 24))
                    }
                }
                .padding(.vertical, 4)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dsCard()
    }
}
