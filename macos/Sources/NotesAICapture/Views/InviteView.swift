import AppKit
import SwiftUI

/// "Invite people" — add a colleague to the workspace by e-mail, or send
/// them the link if they have no account here yet. Opened from the
/// sidebar's invite icon (and the account menu).
///
/// The server resolves an address to an account that already exists in the
/// tenant (`POST /tenants/{id}/members`); anyone else has to sign up first,
/// so a 404 turns into the mail/copy-link fallback rather than an error.
struct InviteView: View {
    @EnvironmentObject private var app: AppState
    var onClose: (() -> Void)? = nil

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

    private static let roles: [DSSelect<String>.Option] = [
        .init(value: "member", label: "Member", symbol: "person", hint: "Notes and meetings"),
        .init(value: "admin", label: "Admin", symbol: "person.badge.key", hint: "Can invite others"),
        .init(value: "viewer", label: "Viewer", symbol: "eye", hint: "Read only"),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            DSDivider()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    inviteBox
                    linkBox
                    roster
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .background(DS.bg)
        .task { await load() }
    }

    // MARK: - Header

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Invite people")
                    .font(.dsDisplay(18, .medium))
                    .foregroundStyle(DS.text1)
                Text(tenant.map { "They join \($0.title)." } ?? "Add colleagues to this workspace.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
            }
            Spacer()
            if let onClose {
                Button("Done", action: onClose)
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 26))
                    .keyboardShortcut(.cancelAction)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
    }

    // MARK: - Add by e-mail

    private var inviteBox: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSLabel("Add by e-mail")
            HStack(spacing: 8) {
                DSTextField(placeholder: "name@company.com", text: $email)
                DSSelect(options: Self.roles, selection: $role, width: 132)
                Button {
                    Task { await add() }
                } label: {
                    if adding {
                        ProgressView().controlSize(.small).frame(width: 30)
                    } else {
                        Text("Add")
                    }
                }
                .buttonStyle(DSButtonStyle(kind: .primary, height: 32))
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
                .font(.dsMono(11.5))
                .foregroundStyle(DS.text2)
                .lineLimit(1)
                .truncationMode(.middle)
                .textSelection(.enabled)
            HStack(spacing: 8) {
                Button {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(inviteLink, forType: .string)
                    copied = true
                    Task {
                        try? await Task.sleep(for: .seconds(2))
                        copied = false
                    }
                } label: {
                    Label(copied ? "Copied" : "Copy link", systemImage: copied ? "checkmark" : "doc.on.doc")
                }
                .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                Button {
                    emailInvite(to: noAccount ?? trimmedEmail)
                } label: {
                    Label("Email invite…", systemImage: "envelope")
                }
                .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                Spacer()
            }
        }
        .dsCard()
    }

    // MARK: - Roster

    @ViewBuilder
    private var roster: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                DSLabel("In this workspace")
                Spacer()
                if !members.isEmpty {
                    Text("\(members.count)")
                        .font(.dsMono(10.5))
                        .foregroundStyle(DS.muted)
                }
            }
            if loading {
                DSSkeleton(height: 32)
                DSSkeleton(height: 32)
            } else if let loadError {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: loadError)
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

    // MARK: - Actions

    private var trimmedEmail: String { email.trimmingCharacters(in: .whitespaces) }

    private var canManage: Bool { tenant?.canManageMembers ?? false }

    private var inviteLink: String {
        app.inviteURL?.absoluteString ?? app.settings.webAppURL
    }

    private func load() async {
        loading = true
        loadError = nil
        do {
            let current = try await app.api.currentTenant()
            tenant = current
            members = try await app.api.tenantMembers(tenantId: current.id)
        } catch {
            loadError = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
        loading = false
    }

    private func add() async {
        guard let tenant, !trimmedEmail.isEmpty else { return }
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
                addError = error.errorDescription
            }
        } catch {
            addError = error.localizedDescription
        }
        adding = false
    }

    private func emailInvite(to: String) {
        let workspace = tenant?.title ?? "our workspace"
        var parts = URLComponents()
        parts.scheme = "mailto"
        parts.path = to
        parts.queryItems = [
            .init(name: "subject", value: "Join \(workspace) on Notes AI"),
            .init(name: "body",
                  value: "Sign in here and you'll be in \(workspace):\n\n\(inviteLink)\n"),
        ]
        if let url = parts.url { NSWorkspace.shared.open(url) }
    }
}

/// One member of the workspace: who they are and what they may do.
private struct MemberRow: View {
    let member: TenantMember

    var body: some View {
        HStack(spacing: 9) {
            DSAvatar(name: member.email ?? member.title, size: 26)
            VStack(alignment: .leading, spacing: 0) {
                Text(member.title)
                    .font(.ds(12.5, .medium))
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
                DSChip(text: member.status, tint: DS.warn, soft: DS.warnSoft)
            }
            Text(member.role.capitalized)
                .font(.dsMeta)
                .foregroundStyle(DS.text3)
        }
        .padding(.horizontal, 8)
        .frame(height: 40)
    }
}
