import SwiftUI
import UIKit

/// "Invite people" — add a colleague by e-mail (`POST /tenants/{id}/members`),
/// or share the link; a 404 (no account yet) is the link fallback, not an error.
struct InviteView: View {
    @EnvironmentObject private var app: AppState
    let onClose: () -> Void

    @State private var tenant: Tenant?
    @State private var members: [TenantMember] = []
    @State private var loading = true
    @State private var loadError: String?

    @State private var email = ""
    @State private var role = "member"
    @State private var adding = false
    @State private var added: String?
    @State private var addError: String?
    /// Address the server does not know: offer the link instead.
    @State private var noAccount: String?
    @State private var copied = false
    @State private var sharingLink = false

    private static let roles: [DSSelect<String>.Option] = [
        .init(value: "member", label: "Member", symbol: "person", hint: "Notes and meetings"),
        .init(value: "admin", label: "Admin", symbol: "person.badge.key", hint: "Can invite others"),
        .init(value: "viewer", label: "Viewer", symbol: "eye", hint: "Read only"),
    ]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text(tenant.map { "They join \($0.title)." } ?? "Add colleagues to this workspace.")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                    inviteBox
                    linkBox
                    WorkspaceRoster(members: members, loading: loading, error: loadError)
                }
                .padding(.horizontal, DS.gutter)
                .padding(.vertical, 12)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(DS.bg)
            .navigationTitle("Invite people")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) { Button("Done", action: onClose) }
            }
            .sheet(isPresented: $sharingLink) {
                ShareSheet(items: [inviteText])
                    .presentationDetents([.medium, .large])
            }
            .task { await load() }
        }
    }

    // MARK: - Add by e-mail

    private var inviteBox: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSLabel("Add by e-mail")
            DSTextField(placeholder: "name@company.com", text: $email)
                .keyboardType(.emailAddress)
                .textContentType(.emailAddress)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.done)
                .onSubmit { Task { await add() } }
            HStack(spacing: 8) {
                DSSelect(options: Self.roles, selection: $role)
                Button {
                    Task { await add() }
                } label: {
                    if adding {
                        ProgressView().controlSize(.small).frame(width: 40)
                    } else {
                        Text("Add")
                    }
                }
                .buttonStyle(DSButtonStyle(kind: .primary, height: 38))
                .disabled(adding || !canManage || trimmedEmail.isEmpty)
            }
            if let added {
                DSNotice(tone: .ok, symbol: "checkmark.circle.fill",
                         text: "\(added) is now in the workspace.")
            }
            if let noAccount {
                DSNotice(tone: .warn, symbol: "envelope",
                         text: "\(noAccount) has no account here yet. Send them the link below — they join the workspace once they sign in.")
            }
            if let addError {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: addError)
            }
            if !loading, !canManage {
                DSNotice(tone: .info, symbol: "info.circle",
                         text: "Only owners and admins can add members. You can still send the invite link.")
            }
        }
        .dsCard()
    }

    // MARK: - Invite link

    private var linkBox: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSLabel("Invite link")
            Text(inviteLink)
                .font(.dsMono(12))
                .foregroundStyle(DS.text2)
                .lineLimit(1)
                .truncationMode(.middle)
                .textSelection(.enabled)
            HStack(spacing: 8) {
                Button {
                    copyToPasteboard(inviteLink)
                    copied = true
                    Task {
                        try? await Task.sleep(for: .seconds(2))
                        copied = false
                    }
                } label: {
                    Label(copied ? "Copied" : "Copy link", systemImage: copied ? "checkmark" : "doc.on.doc")
                }
                .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 34))
                Button {
                    sharingLink = true
                } label: {
                    Label("Send…", systemImage: "square.and.arrow.up")
                }
                .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 34))
                Spacer()
            }
        }
        .dsCard()
    }

    // MARK: - Actions

    private var trimmedEmail: String { email.trimmingCharacters(in: .whitespaces) }

    private var canManage: Bool { tenant?.canManageMembers ?? false }

    private var inviteLink: String {
        app.inviteURL?.absoluteString ?? app.settings.webAppURL
    }

    private var inviteText: String {
        let workspace = tenant?.title ?? "our workspace"
        return "Sign in here and you'll be in \(workspace) on Notes AI:\n\(inviteLink)"
    }

    private func load() async {
        loading = true
        loadError = nil
        do {
            let current = try await app.api.currentTenant()
            tenant = current
            members = try await app.api.tenantMembers(tenantId: current.id)
        } catch {
            loadError = AuthCopy.message(for: error)
        }
        loading = false
    }

    private func add() async {
        guard let tenant, !trimmedEmail.isEmpty, !adding else { return }
        let address = trimmedEmail
        adding = true
        added = nil
        addError = nil
        noAccount = nil
        do {
            try await app.api.addTenantMember(tenantId: tenant.id, email: address, role: role)
            added = address
            email = ""
            members = (try? await app.api.tenantMembers(tenantId: tenant.id)) ?? members
        } catch let error as APIError {
            switch error {
            case .http(status: 404, problem: _):
                noAccount = address
            case .http(status: 409, problem: _):
                addError = "\(address) is already in this workspace."
            case .http(status: 403, problem: _):
                addError = "Only owners and admins can add members."
            default:
                addError = AuthCopy.message(for: error)
            }
        } catch {
            addError = AuthCopy.message(for: error)
        }
        adding = false
    }
}

/// "In this workspace" — who is here and what they may do.
struct WorkspaceRoster: View {
    let members: [TenantMember]
    let loading: Bool
    let error: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                DSLabel("In this workspace")
                Spacer()
                if !members.isEmpty {
                    Text("\(members.count)")
                        .font(.dsMono(11))
                        .foregroundStyle(DS.muted)
                }
            }
            if loading {
                DSSkeleton(height: 32)
                DSSkeleton(height: 32)
            } else if let error {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
            } else if members.isEmpty {
                Text("Nobody else here yet.")
                    .font(.dsBody)
                    .foregroundStyle(DS.muted)
            } else {
                VStack(spacing: 2) {
                    ForEach(members) { member in
                        MemberRow(member: member)
                    }
                }
            }
        }
        .dsCard()
    }
}

/// One member of the workspace: who they are and what they may do.
private struct MemberRow: View {
    let member: TenantMember

    var body: some View {
        HStack(spacing: 10) {
            DSAvatar(name: member.email ?? member.title, size: 30)
            VStack(alignment: .leading, spacing: 0) {
                Text(member.title)
                    .font(.ds(14, .medium))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                if let email = member.email, email != member.title {
                    Text(email)
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 8)
            if member.status != "active" {
                DSChip(text: member.status.capitalized, tint: DS.warn, soft: DS.warnSoft)
            }
            Text(member.role.capitalized)
                .font(.dsMeta)
                .foregroundStyle(DS.text3)
        }
        .padding(.horizontal, 4)
        .frame(minHeight: 40)
        .accessibilityElement(children: .combine)
    }
}
