import SwiftUI

/// Which workspace this phone is in, and how to change it. Always visible:
/// a meeting recorded into the wrong workspace is a disclosure.
struct WorkspaceChip: View {
    @EnvironmentObject private var app: AppState
    @State private var picking = false

    var body: some View {
        // Shown with one workspace too: "Personal" is still a place a note can land.
        if let active = app.activeWorkspace {
            Button { picking = true } label: {
                HStack(spacing: 5) {
                    Image(systemName: active.isPersonal ? "house" : "building.2")
                        .font(.dsSymbol(11, .semibold))
                    Text(active.switcherTitle)
                        .font(.ds(12.5, .semibold))
                        .lineLimit(1)
                    Image(systemName: "chevron.up.chevron.down")
                        .font(.dsSymbol(9, .semibold))
                }
                .foregroundStyle(DS.accentText)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(Capsule().fill(DS.accentSoft))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Workspace: \(active.switcherTitle)")
            .accessibilityHint("Switch workspace")
            .sheet(isPresented: $picking) { WorkspacePicker() }
        }
    }
}

/// The head of the home page: the chip, whether the place is private or shared, who is in it, and Invite.
struct SpaceHeader: View {
    @EnvironmentObject private var app: AppState
    @State private var members: [TenantMember] = []

    private static let shown = 4

    var body: some View {
        if let active = app.activeWorkspace {
            HStack(spacing: 8) {
                WorkspaceChip()
                Text(active.isPersonal ? "Private · only you" : "Workspace")
                    .font(.ds(12.5))
                    .foregroundStyle(DS.muted)
                    .lineLimit(1)
                Spacer(minLength: 6)
                if !active.isPersonal, !members.isEmpty {
                    Button {
                        app.settingsTab = .account
                        app.settingsPresented = true
                    } label: {
                        people
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(members.count) \(members.count == 1 ? "person" : "people") in \(active.title)")
                }
                if !active.isPersonal, app.canManageMembers {
                    Button("Invite") { app.invitePresented = true }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 13, height: 30))
                        .accessibilityHint("Invite people to \(active.title)")
                }
            }
            .task(id: app.tenantId) { await loadMembers() }
            // The invite sheet is also where members are removed: the row follows it.
            .onChange(of: app.invitePresented) { _, shown in
                if !shown { Task { await loadMembers() } }
            }
        }
    }

    /// The roster's avatars, overlapping; the rest as "+N".
    private var people: some View {
        HStack(spacing: -6) {
            ForEach(members.prefix(Self.shown)) { member in
                DSAvatar(name: member.title, size: 24)
                    .overlay(Circle().strokeBorder(DS.bg, lineWidth: 1.5))
            }
            if members.count > Self.shown {
                Text("+\(members.count - Self.shown)")
                    .font(.ds(11, .medium))
                    .foregroundStyle(DS.muted)
                    .padding(.leading, 10)
            }
        }
        .contentShape(Capsule())
    }

    /// A guest cannot read the roster, and Personal has nobody else in it: no request either way.
    private func loadMembers() async {
        guard let active = app.activeWorkspace, !active.isPersonal, !active.isGuest else {
            members = []
            return
        }
        let loaded = (try? await app.api.tenantMembers(tenantId: active.id)) ?? []
        members = loaded.filter { $0.status == "active" }
    }
}

/// The switcher itself.
struct WorkspacePicker: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.dismiss) private var dismiss
    @State private var creating = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Notes, spaces and meetings belong to one workspace. Switching changes everything this app shows.")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .fixedSize(horizontal: false, vertical: true)
                    if !app.myInvitations.isEmpty {
                        NavigationLink {
                            InvitationsView(onJoined: { dismiss() })
                        } label: {
                            HStack(spacing: 12) {
                                Image(systemName: "envelope.open")
                                    .font(.dsSymbol(15, .medium))
                                    .foregroundStyle(DS.accentText)
                                    .frame(width: 34)
                                Text("Invitations (\(app.myInvitations.count))")
                                    .font(.ds(15, .medium))
                                    .foregroundStyle(DS.text1)
                                Spacer(minLength: 0)
                                Image(systemName: "chevron.right")
                                    .font(.dsSymbol(12, .semibold))
                                    .foregroundStyle(DS.muted)
                            }
                            .padding(14)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .dsCard(padding: 0)
                    }
                    VStack(spacing: 0) {
                        ForEach(Array(app.pickerWorkspaces.enumerated()), id: \.element.id) { index, workspace in
                            if index > 0 { DSDivider() }
                            row(workspace)
                        }
                        if !app.workspaces.isEmpty { DSDivider() }
                        Button { creating = true } label: {
                            HStack(spacing: 12) {
                                Image(systemName: "plus")
                                    .font(.dsSymbol(15, .medium))
                                    .foregroundStyle(DS.text3)
                                    .frame(width: 34)
                                Text("New workspace…")
                                    .font(.ds(15, .medium))
                                    .foregroundStyle(DS.text1)
                                Spacer(minLength: 0)
                            }
                            .padding(14)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .disabled(app.switchingTo != nil)
                    }
                    .dsCard(padding: 0)
                    if !app.canSwitchWorkspace, app.workspaces.count > 1 {
                        // Name the reason (ADR-0047) rather than leave a dead row.
                        DSNotice(tone: .info, symbol: "key.fill",
                                 text: "Switching needs the new sign-in. Sign out and sign in with an emailed code, or switch in the web app.")
                    }
                    if app.workspaces.isEmpty {
                        DSNotice(tone: .info, symbol: "building.2",
                                 text: "No workspaces yet. Ask a colleague to add you to theirs.")
                    }
                }
                .padding(.horizontal, DS.gutter)
                .padding(.vertical, 12)
            }
            .background(DS.bg)
            .navigationTitle("Workspace")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .font(.ds(15, .semibold))
                }
            }
        }
        .tint(DS.accentText)
        .sheet(isPresented: $creating) {
            NewWorkspaceSheet(onCreated: { dismiss() })
        }
        .task {
            await app.refreshWorkspaces(force: true)
            await app.refreshMyInvitations(force: true)
        }
    }

    private func row(_ workspace: Workspace) -> some View {
        let isActive = workspace.id == app.tenantId
        let isSwitching = app.switchingTo == workspace.id
        return Button {
            guard !isActive else { return dismiss() }
            Task {
                await app.switchWorkspace(to: workspace)
                dismiss()
            }
        } label: {
            HStack(spacing: 12) {
                DSAvatar(name: workspace.title, size: 34)
                VStack(alignment: .leading, spacing: 1) {
                    Text(workspace.switcherTitle)
                        .font(.ds(15, .medium))
                        .foregroundStyle(DS.text1)
                        .lineLimit(1)
                    Text(workspace.roleLabel)
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                }
                Spacer(minLength: 0)
                if isSwitching {
                    ProgressView().controlSize(.small)
                } else if isActive {
                    Image(systemName: "checkmark")
                        .font(.dsSymbol(14, .semibold))
                        .foregroundStyle(DS.accentText)
                }
            }
            .padding(14)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(app.switchingTo != nil || (!isActive && !app.canSwitchWorkspace))
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(workspace.switcherTitle), \(workspace.roleLabel)")
        .accessibilityAddTraits(isActive ? .isSelected : [])
    }
}

/// "New workspace…": a name, then the app is in it.
struct NewWorkspaceSheet: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.dismiss) private var dismiss
    let onCreated: () -> Void

    @State private var name = ""
    @State private var creating = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 12) {
                Text("A shared place for a team's notes and meetings. You can invite people once you are in it.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
                DSTextField(placeholder: "Sunrise Studio", text: $name)
                    .textContentType(.organizationName)
                    .submitLabel(.done)
                    .onSubmit { Task { await create() } }
                if let error {
                    DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                }
                Button {
                    Task { await create() }
                } label: {
                    if creating {
                        ProgressView().tint(DS.inkText)
                    } else {
                        Text("Create workspace")
                    }
                }
                .buttonStyle(DSButtonStyle(kind: .primary, height: DS.control, fill: true))
                .disabled(creating || trimmed.isEmpty)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, DS.gutter)
            .padding(.vertical, 12)
            .background(DS.bg)
            .navigationTitle("New workspace")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
        .tint(DS.accentText)
        .presentationDetents([.medium])
    }

    private var trimmed: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }

    private func create() async {
        guard !trimmed.isEmpty, !creating else { return }
        creating = true
        error = await app.createWorkspace(named: trimmed)
        creating = false
        if error == nil {
            dismiss()
            onCreated()
        }
    }
}

/// Invitations addressed to this person: join with one tap, or decline.
struct InvitationsView: View {
    @EnvironmentObject private var app: AppState
    let onJoined: () -> Void

    @State private var busy: String?
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
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
            .padding(.horizontal, DS.gutter)
            .padding(.vertical, 12)
        }
        .background(DS.bg)
        .navigationTitle("Invitations")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func row(_ invite: MyInvitation) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                DSAvatar(name: invite.workspaceName, size: 34)
                VStack(alignment: .leading, spacing: 1) {
                    Text(invite.workspaceName)
                        .font(.ds(15, .medium))
                        .foregroundStyle(DS.text1)
                        .lineLimit(1)
                    Text("\(invite.inviterDisplay) invited you \(WorkspaceRoles.asPhrase(invite.role))")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .lineLimit(2)
                }
                Spacer(minLength: 0)
            }
            HStack(spacing: 8) {
                if busy == invite.id {
                    ProgressView().controlSize(.small)
                } else {
                    Button("Accept") { run(invite) { await app.accept(invite) } }
                        .buttonStyle(DSButtonStyle(kind: .primary, size: 14, height: 34))
                        .accessibilityLabel("Accept the invitation to \(invite.workspaceName)")
                    Button("Decline") { run(invite) { await app.decline(invite) } }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 34))
                        .accessibilityLabel("Decline the invitation to \(invite.workspaceName)")
                }
                Spacer()
            }
            .disabled(busy != nil)
        }
        .dsCard()
    }

    private func run(_ invite: MyInvitation, _ work: @escaping () async -> String?) {
        busy = invite.id
        error = nil
        let accepting = app.tenantId
        Task {
            error = await work()
            busy = nil
            // An accept moves the session; the picker closes onto the new workspace.
            if error == nil, app.tenantId != accepting { onJoined() }
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
        NavigationStack {
            VStack(alignment: .leading, spacing: 16) {
                content
                Spacer(minLength: 0)
            }
            .padding(.horizontal, DS.gutter)
            .padding(.vertical, 16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(DS.bg)
            .navigationTitle("Invitation")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Close") { app.invitation = nil }
                }
            }
        }
        .tint(DS.accentText)
        .presentationDetents([.medium, .large])
    }

    @ViewBuilder
    private var content: some View {
        switch state {
        case .loading:
            ProgressView().frame(maxWidth: .infinity, minHeight: 120)
        case .invalid:
            DSNotice(tone: .info, symbol: "envelope.badge",
                     text: "This invitation is no longer valid. Ask the person who invited you for a new one.")
        case .ready(let lookup):
            card(lookup)
            if app.authState == .signedIn {
                primary("Join \(lookup.workspaceName)") { Task { await app.joinInvitation() } }
            } else {
                primary("Sign in with \(lookup.emailMasked)") { Task { await app.joinInvitation() } }
                caption("Sign in, or create an account, with that address. You join right after.")
            }
        case .joining(let lookup):
            card(lookup)
            Button {} label: { ProgressView().tint(DS.inkText) }
                .buttonStyle(DSButtonStyle(kind: .primary, height: DS.control, fill: true))
                .disabled(true)
        case .mismatch(let lookup, let signedInAs):
            card(lookup)
            DSNotice(tone: .warn, symbol: "person.crop.circle.badge.exclamationmark",
                     text: "You're signed in as \(signedInAs). This invitation is for \(lookup.emailMasked); nothing was shared.")
            primary("Sign out and continue as \(lookup.emailMasked)") {
                Task { await app.signOutForInvitation() }
            }
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
            DSAvatar(name: lookup.workspaceName, size: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text("\(lookup.inviterDisplay) invited you to")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                Text(lookup.workspaceName)
                    .font(.ds(17, .semibold))
                    .foregroundStyle(DS.text1)
                    .lineLimit(2)
                Text("\(WorkspaceRoles.label(lookup.role)) · for \(lookup.emailMasked)")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                // An invitation to one note: name it, so the person knows what they are joining for.
                if let note = lookup.noteTitle, !note.isEmpty {
                    Text("To see “\(note)”")
                        .font(.dsMeta)
                        .foregroundStyle(DS.text3)
                        .lineLimit(2)
                }
            }
            Spacer(minLength: 0)
        }
        .dsCard()
    }

    private func primary(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) { Text(title).lineLimit(1) }
            .buttonStyle(DSButtonStyle(kind: .primary, height: DS.control, fill: true))
    }

    private func caption(_ text: String) -> some View {
        Text(text)
            .font(.dsMeta)
            .foregroundStyle(DS.muted)
            .fixedSize(horizontal: false, vertical: true)
    }
}
