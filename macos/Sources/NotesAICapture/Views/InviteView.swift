import AppKit
import SwiftUI

/// "Invite people" — invite by e-mail with a role (`POST /tenants/{id}/invitations`), see who is
/// still pending, and manage who is in. Nothing is granted until the invited address accepts.
struct InviteView: View {
    @EnvironmentObject private var app: AppState
    var onClose: (() -> Void)? = nil

    @State private var tenant: Tenant?
    @State private var members: [TenantMember] = []
    @State private var seats: SeatMeter?
    @State private var pending: [Invitation] = []
    @State private var loading = true
    @State private var loadError: String?

    @State private var email = ""
    @State private var role = "member"
    @State private var message = ""
    @State private var sending = false
    @State private var sent: Invitation?
    @State private var sendError: String?
    /// The pending row an action is running on, and what the last one said.
    @State private var busy: String?
    @State private var rowError: String?

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
                    if canManage, !pending.isEmpty { pendingBox }
                    WorkspaceRoster(members: members, loading: loading, error: loadError, seats: seats,
                                    manage: canManage ? manage : nil)
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .background(DS.bg)
        .task { await load() }
        // Inviting and managing people asks for recent proof; the window's sheet cannot present over this one.
        .sheet(item: $app.reauth) { prompt in
            ReauthSheet(prompt: prompt)
        }
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

    // MARK: - Invite by e-mail

    private var inviteBox: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSLabel("Invite by e-mail")
            if tenant?.isPersonal == true {
                DSNotice(tone: .info, symbol: "house",
                         text: "Personal is just for you. Create a workspace from the account menu to invite people.")
            } else {
                HStack(spacing: 8) {
                    DSTextField(placeholder: "name@company.com", text: $email)
                        .onSubmit { Task { await send() } }
                    DSSelect(options: Self.roles, selection: $role, width: 132)
                    Button {
                        Task { await send() }
                    } label: {
                        if sending {
                            ProgressView().controlSize(.small).frame(width: 36)
                        } else {
                            Text("Invite")
                        }
                    }
                    .buttonStyle(DSButtonStyle(kind: .primary, height: 32))
                    .disabled(sending || !canManage || trimmedEmail.isEmpty)
                }
                DSTextField(placeholder: "Add a note (optional)", text: $message)
                Text("They'll get an e-mail from Notes AI; nothing is shared until they accept.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                if let sent {
                    if sent.notSent {
                        DSNotice(tone: .warn, symbol: "envelope.badge",
                                 text: "Invitation saved for \(sent.email), but the e-mail could not be sent. Resend it below.")
                    } else {
                        DSNotice(tone: .ok, symbol: "checkmark.circle.fill",
                                 text: "Invitation sent to \(sent.email).")
                    }
                }
                if let sendError {
                    DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: sendError)
                }
                if !loading, !canManage {
                    DSNotice(tone: .info, symbol: "info.circle",
                             text: "Only owners and admins can invite people.")
                }
            }
        }
        .dsCard()
    }

    // MARK: - Pending

    private var pendingBox: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                DSLabel("Pending")
                Spacer()
                Text("\(pending.count)")
                    .font(.dsMono(10.5))
                    .foregroundStyle(DS.muted)
            }
            VStack(spacing: 2) {
                ForEach(pending) { invite in
                    pendingRow(invite)
                }
            }
            if let rowError {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: rowError)
            }
        }
        .dsCard()
    }

    private func pendingRow(_ invite: Invitation) -> some View {
        HStack(spacing: 9) {
            DSAvatar(name: invite.email, size: 26)
            VStack(alignment: .leading, spacing: 0) {
                Text(invite.email)
                    .font(.ds(12.5, .medium))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                Text(pendingLine(invite))
                    .font(.dsMeta)
                    .foregroundStyle(invite.notSent ? DS.warn : DS.muted)
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
            if busy == invite.id {
                ProgressView().controlSize(.small)
            } else {
                Button("Resend") { Task { await resend(invite) } }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 24))
                Button("Revoke") { Task { await revoke(invite) } }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 24))
                    .foregroundStyle(DS.danger)
            }
        }
        .padding(.horizontal, 8)
        .frame(height: 40)
    }

    private func pendingLine(_ invite: Invitation) -> String {
        let role = WorkspaceRoles.label(invite.role)
        if invite.notSent { return "\(role) · Not sent — Resend" }
        let times = invite.sentCount == 1 ? "Sent" : "Sent \(invite.sentCount)×"
        return "\(role) · \(times) · expires \(formatDateTime(invite.expiresAt))"
    }

    // MARK: - Actions

    private var trimmedEmail: String { email.trimmingCharacters(in: .whitespaces) }

    private var canManage: Bool { tenant?.canManageMembers ?? false }

    private var manage: WorkspaceRoster.Manage {
        WorkspaceRoster.Manage(
            selfId: app.identity?.id,
            setRole: { member, role in
                guard let tenant else { return nil }
                do {
                    try await app.api.setMemberRole(tenantId: tenant.id, userSub: member.userSub, role: role)
                } catch {
                    return AuthCopy.message(for: error)
                }
                await reloadPeople()
                return nil
            },
            remove: { member in
                guard let tenant else { return nil }
                do {
                    try await app.api.removeMember(tenantId: tenant.id, userSub: member.userSub)
                } catch {
                    return AuthCopy.message(for: error)
                }
                await reloadPeople()
                return nil
            })
    }

    private func load() async {
        loading = true
        loadError = nil
        do {
            let current = try await app.api.currentTenant()
            tenant = current
            await reloadPeople()
        } catch {
            loadError = AuthCopy.message(for: error)
        }
        loading = false
    }

    /// Roster, seat meter and (for managers) the pending list.
    private func reloadPeople() async {
        guard let tenant else { return }
        do {
            let roster = try await app.api.roster(tenantId: tenant.id)
            members = roster.items
            seats = roster.seatMeter
            loadError = nil
        } catch {
            loadError = AuthCopy.message(for: error)
        }
        if tenant.canManageMembers, !tenant.isPersonal {
            pending = (try? await app.api.invitations(tenantId: tenant.id)) ?? pending
        }
    }

    private func send() async {
        guard let tenant, !trimmedEmail.isEmpty, !sending, canManage else { return }
        sending = true
        sent = nil
        sendError = nil
        defer { sending = false }
        do {
            // `403 reauth_required` is answered inside `APIClient` (step-up + one retry).
            let invite = try await app.api.invite(tenantId: tenant.id, email: trimmedEmail, role: role,
                                                  message: message.trimmingCharacters(in: .whitespacesAndNewlines))
            sent = invite
            email = ""
            message = ""
            pending.removeAll { $0.id == invite.id }
            pending.insert(invite, at: 0)
        } catch {
            sendError = AuthCopy.message(for: error)
        }
    }

    private func resend(_ invite: Invitation) async {
        guard let tenant else { return }
        busy = invite.id
        rowError = nil
        defer { busy = nil }
        do {
            let fresh = try await app.api.resendInvitation(tenantId: tenant.id, id: invite.id)
            if let index = pending.firstIndex(where: { $0.id == invite.id }) { pending[index] = fresh }
        } catch {
            rowError = AuthCopy.message(for: error)
        }
    }

    private func revoke(_ invite: Invitation) async {
        guard let tenant else { return }
        busy = invite.id
        rowError = nil
        defer { busy = nil }
        do {
            try await app.api.revokeInvitation(tenantId: tenant.id, id: invite.id)
            pending.removeAll { $0.id == invite.id }
        } catch {
            rowError = AuthCopy.message(for: error)
        }
    }
}

/// "In this workspace" — who is here; owners and admins also change roles and remove people.
struct WorkspaceRoster: View {
    /// What a manager may do to a row; each returns what went wrong, or nil.
    struct Manage {
        /// The signed-in person's row gets no actions (leaving is in Settings › Account).
        let selfId: String?
        let setRole: (TenantMember, String) async -> String?
        let remove: (TenantMember) async -> String?
    }

    let members: [TenantMember]
    let loading: Bool
    let error: String?
    var seats: SeatMeter? = nil
    var manage: Manage? = nil

    @State private var busy: String?
    @State private var actionError: String?
    @State private var removing: TenantMember?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                DSLabel("In this workspace")
                Spacer()
                if let seatLine {
                    Text(seatLine)
                        .font(.dsMono(10.5))
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
                        MemberRow(member: member, busy: busy == member.userSub, actions: actions(for: member))
                    }
                }
            }
            if let actionError {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: actionError)
            }
        }
        .dsCard()
        .alert("Remove \(removing?.title ?? "")?",
               isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } })) {
            Button("Remove", role: .destructive) {
                if let member = removing { run(member) { await $0.remove(member) } }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("They lose access to this workspace's notes and meetings. You can invite them again later.")
        }
    }

    /// "4 of 3 seats" (display only), else the head count.
    private var seatLine: String? {
        if let seats, let limit = seats.limit { return "\(seats.active) of \(limit) seats" }
        return members.isEmpty ? nil : "\(members.count)"
    }

    private func actions(for member: TenantMember) -> [DSMenuItem]? {
        guard let manage, member.userSub != manage.selfId, member.leftAt == nil,
              member.status == "active" else { return nil }
        var items: [DSMenuItem] = WorkspaceRoles.invitable
            .filter { $0 != member.role }
            .map { role in
                .item("Make \(WorkspaceRoles.label(role).lowercased())", symbol: "person.badge.key") {
                    run(member) { await $0.setRole(member, role) }
                }
            }
        items.append(.separator)
        items.append(.item("Remove from workspace", symbol: "person.badge.minus", danger: true) {
            removing = member
        })
        return items
    }

    private func run(_ member: TenantMember, _ work: @escaping (Manage) async -> String?) {
        guard let manage else { return }
        busy = member.userSub
        actionError = nil
        Task {
            actionError = await work(manage)
            busy = nil
        }
    }
}

/// One member of the workspace: who they are and what they may do.
private struct MemberRow: View {
    let member: TenantMember
    var busy = false
    var actions: [DSMenuItem]?

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
            if let leftAt = member.leftAt {
                DSChip(text: "Left \(relativeTime(leftAt))", tint: DS.muted, soft: DS.surface2)
            } else if member.status != "active" {
                DSChip(text: member.status, tint: DS.warn, soft: DS.warnSoft)
            }
            Text(WorkspaceRoles.label(member.role))
                .font(.dsMeta)
                .foregroundStyle(DS.text3)
            if busy {
                ProgressView().controlSize(.small)
            } else if let actions {
                DSMenu(width: 200) { actions }
            }
        }
        .padding(.horizontal, 8)
        .frame(height: 40)
    }
}
