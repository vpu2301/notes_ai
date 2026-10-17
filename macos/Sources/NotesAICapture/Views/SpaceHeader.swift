import SwiftUI

/// The head of the detail column, in the window's title-bar row: which workspace this is (Personal is private,
/// a team one is shared), who is in it, and the one click to invite. The name is also the switcher.
struct SpaceHeaderBar: View {
    @EnvironmentObject private var app: AppState
    @State private var members: [TenantMember] = []
    /// Hovering the avatars shows the roster card.
    @State private var peek = false

    private static let shown = 4

    var body: some View {
        HStack(spacing: 10) {
            DSMenu(width: 248, items: workspaceItems) {
                SpaceLabel(name: name, personal: isPersonal)
            }
            .help("Switch workspace")
            .accessibilityLabel("\(isPersonal ? "Private" : "Workspace"): \(name)")
            Text(isPersonal ? "Private · only you" : "Workspace")
                .font(.ds(12))
                .foregroundStyle(DS.muted)
                .lineLimit(1)
            Spacer(minLength: 8)
            if !isPersonal, !members.isEmpty {
                Button { app.invitePresented = true } label: { people }
                    .buttonStyle(.plain)
                    .onHover { peek = $0 }
                    .popover(isPresented: $peek, arrowEdge: .bottom) { roster }
                    .accessibilityLabel("\(members.count) \(members.count == 1 ? "person" : "people") in \(name)")
            }
            if !isPersonal, app.activeWorkspace?.canManageMembers == true {
                Button {
                    app.invitePresented = true
                } label: {
                    Label("Invite", systemImage: "person.badge.plus")
                }
                .buttonStyle(InviteButtonStyle())
                .help("Invite people to \(name)")
            }
        }
        .padding(.leading, 20)
        .padding(.trailing, 16)
        .frame(height: DS.titlebarInset + 2)
        .task(id: app.tenantId) { await loadMembers() }
        // The invite sheet is also where members are removed: the row follows it.
        .onChange(of: app.invitePresented) { _, shown in
            if !shown { Task { await loadMembers() } }
        }
    }

    /// The roster's avatars, overlapping; the rest as "+N".
    private var people: some View {
        HStack(spacing: -6) {
            ForEach(members.prefix(Self.shown)) { member in
                DSAvatar(name: member.title, size: 22)
                    .overlay(Circle().strokeBorder(DS.bg, lineWidth: 1.5))
            }
            if members.count > Self.shown {
                Text("+\(members.count - Self.shown)")
                    .font(.ds(10.5, .medium))
                    .foregroundStyle(DS.muted)
                    .padding(.leading, 10)
            }
        }
        .padding(.horizontal, 6)
        .frame(height: 28)
        .contentShape(Capsule())
    }

    /// Everyone in the workspace by name, as the hover card under the avatars.
    private var roster: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("\(members.count) \(members.count == 1 ? "person" : "people") in \(name)")
                .font(.ds(11.5))
                .foregroundStyle(DS.muted)
                .padding(.horizontal, 8)
                .padding(.bottom, 4)
            ForEach(members) { member in
                HStack(spacing: 10) {
                    DSAvatar(name: member.title, size: 24)
                    Text(member.title)
                        .font(.ds(13))
                        .foregroundStyle(DS.text1)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Spacer(minLength: 8)
                    Text(member.role.replacingOccurrences(of: "_", with: " ").capitalized)
                        .font(.ds(11.5))
                        .foregroundStyle(DS.muted)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 5)
            }
        }
        .padding(.vertical, 10)
        .padding(.horizontal, 6)
        .frame(width: 260, alignment: .leading)
    }

    private var name: String {
        let name = app.activeWorkspaceName
        return name.isEmpty ? "Notes AI" : name
    }

    /// Known from sign-in before `/tenants` answers.
    private var isPersonal: Bool {
        if let active = app.activeWorkspace { return active.isPersonal }
        guard let tenantId = app.tenantId else { return false }
        return app.memberships.first { $0.tenantId == tenantId }?.kind == "personal"
    }

    /// A guest cannot read the roster, and Personal has nobody else in it: no request either way.
    private func loadMembers() async {
        guard let tenantId = app.tenantId, !isPersonal, !app.capabilities.isGuest else {
            members = []
            return
        }
        let loaded = (try? await app.api.tenantMembers(tenantId: tenantId)) ?? []
        members = loaded.filter { $0.status == "active" }
    }

    private func workspaceItems() -> [DSMenuItem] {
        var items: [DSMenuItem] = [.header("Workspace")]
        for workspace in app.workspaces {
            items.append(.item(
                workspace.switcherTitle,
                symbol: workspace.isPersonal ? "house" : "building.2",
                hint: workspace.isGuest ? nil : workspace.myRole?.capitalized,
                disabled: app.switchingTo != nil || workspace.id == app.tenantId,
                checked: workspace.id == app.tenantId
            ) {
                Task { await app.switchWorkspace(to: workspace.id) }
            })
        }
        items.append(.separator)
        items.append(.item("New workspace…", symbol: "plus") { app.newWorkspacePresented = true })
        return items
    }
}

/// The name with its mark (`.sb-ws-mark`): a house for Personal, the first letter for a team.
private struct SpaceLabel: View {
    let name: String
    let personal: Bool
    @State private var hover = false

    var body: some View {
        HStack(spacing: 7) {
            Group {
                if personal {
                    Image(systemName: "house.fill")
                        .font(.dsIcon(9, .semibold))
                } else {
                    Text(String(name.trimmingCharacters(in: .whitespaces).prefix(1)).uppercased())
                        .font(.ds(9, .semibold))
                }
            }
            .foregroundStyle(DS.accentText)
            .frame(width: 20, height: 20)
            .background(Circle().fill(DS.accentSoft))
            Text(name)
                .font(.ds(13.5, .medium))
                .foregroundStyle(DS.text1)
                .lineLimit(1)
            Image(systemName: "chevron.down")
                .font(.dsIcon(9, .semibold))
                .foregroundStyle(DS.muted)
        }
        .padding(.leading, 4)
        .padding(.trailing, 8)
        .frame(height: 28)
        .background(
            RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous)
                .fill(hover ? DS.surface2 : .clear)
        )
        .contentShape(RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous))
        .onHover { hover = $0 }
    }
}

/// Invite: a soft moss pill, the one call to action in the bar; fills on hover.
private struct InviteButtonStyle: ButtonStyle {
    @State private var hover = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.ds(12.5, .medium))
            .foregroundStyle(hover ? DS.accentInk : DS.accentText)
            .padding(.leading, 11)
            .padding(.trailing, 14)
            .frame(height: 28)
            .background(Capsule().fill(hover ? DS.accentFill : DS.accentSoft))
            .opacity(configuration.isPressed ? 0.85 : 1)
            .contentShape(Capsule())
            .onHover { hover = $0 }
            .animation(.easeOut(duration: 0.12), value: hover)
    }
}
