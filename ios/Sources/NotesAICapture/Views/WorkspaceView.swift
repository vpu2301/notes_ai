import SwiftUI

/// Which workspace this phone is in, and how to change it.
///
/// One identity can be in several — an agency and each of its clients, a
/// consultant and their own company. Everything the app shows is scoped to
/// one of them at a time, so the name has to be visible without going
/// looking for it: a meeting recorded into the wrong workspace is a
/// disclosure, not a filing error.
struct WorkspaceChip: View {
    @EnvironmentObject private var app: AppState
    @State private var picking = false

    var body: some View {
        if let active = app.activeWorkspace, app.workspaces.count > 1 {
            Button { picking = true } label: {
                HStack(spacing: 5) {
                    Image(systemName: "building.2")
                        .font(.system(size: 11, weight: .semibold))
                    Text(active.title)
                        .font(.ds(12.5, .semibold))
                        .lineLimit(1)
                    Image(systemName: "chevron.up.chevron.down")
                        .font(.system(size: 9, weight: .semibold))
                }
                .foregroundStyle(DS.accentText)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(Capsule().fill(DS.accentSoft))
            }
            .buttonStyle(.plain)
            .sheet(isPresented: $picking) { WorkspacePicker() }
        }
    }
}

/// The switcher itself.
struct WorkspacePicker: View {
    @EnvironmentObject private var app: AppState
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Notes, spaces and meetings belong to one workspace. Switching changes everything this app shows.")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .fixedSize(horizontal: false, vertical: true)
                    VStack(spacing: 0) {
                        ForEach(Array(app.workspaces.enumerated()), id: \.element.id) { index, workspace in
                            if index > 0 { DSDivider() }
                            row(workspace)
                        }
                    }
                    .dsCard(padding: 0)
                    if !app.canSwitchWorkspace, app.workspaces.count > 1 {
                        // ADR-0047 records this as the one capability the
                        // dual-issuer period splits by token origin, so
                        // the reason is named rather than left as a row
                        // that does nothing when tapped.
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
        .task { await app.refreshWorkspaces(force: true) }
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
                    Text(workspace.title)
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
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(DS.accentText)
                }
            }
            .padding(14)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(app.switchingTo != nil || (!isActive && !app.canSwitchWorkspace))
    }
}
