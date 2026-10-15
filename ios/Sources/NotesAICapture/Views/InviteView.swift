import SwiftUI

/// "Invite people" — invite by e-mail with a role (`POST /tenants/{id}/invitations`), see who is
/// still pending, and manage who is in. Nothing is granted until the invited address accepts.
struct InviteView: View {
    @EnvironmentObject private var app: AppState
    let onClose: () -> Void

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
    /// One line per address of the last send: what happened to each.
    @State private var results: [InviteResult] = []
    /// The pending row an action is running on, and what the last one said.
    @State private var busy: String?
    @State private var rowError: String?

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
                    if canManage, !pending.isEmpty { pendingBox }
                    WorkspaceRoster(members: members, loading: loading, error: loadError, seats: seats,
                                    manage: canManage ? manage : nil)
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
            .task { await load() }
        }
        // Inviting and managing people asks for recent proof; the root's sheet cannot present over this one.
        .sheet(item: $app.reauth) { prompt in
            ReauthSheet(prompt: prompt)
        }
    }

    // MARK: - Invite by e-mail

    private var inviteBox: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSLabel("Invite by e-mail")
            if tenant?.isPersonal == true {
                DSNotice(tone: .info, symbol: "house",
                         text: "Personal is just for you. Create a workspace from the workspace menu to invite people.")
            } else {
                // Several addresses may be pasted at once: commas, semicolons, spaces or new lines.
                TextField("name@company.com", text: $email, axis: .vertical)
                    .lineLimit(1...4)
                    .textFieldStyle(.plain)
                    .font(.ds(16))
                    .foregroundStyle(DS.text1)
                    .keyboardType(.emailAddress)
                    .textContentType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
                    .frame(minHeight: DS.control)
                    .background(RoundedRectangle(cornerRadius: DS.radius, style: .continuous).fill(DS.surface))
                    .overlay(RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                        .strokeBorder(DS.line, lineWidth: DS.hairline))
                    .accessibilityLabel("E-mail addresses")
                DSTextField(placeholder: "Add a note (optional)", text: $message)
                HStack(spacing: 8) {
                    DSSelect(options: Self.roles, selection: $role)
                    Button {
                        Task { await send() }
                    } label: {
                        if sending {
                            ProgressView().controlSize(.small).frame(width: 40)
                        } else {
                            Text("Invite")
                        }
                    }
                    .buttonStyle(DSButtonStyle(kind: .primary, height: 38))
                    .disabled(sending || !canManage || addresses.isEmpty)
                }
                Text("They'll get an e-mail from Notes AI. Nothing is shared until they accept.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
                if !results.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(results) { result in
                            HStack(alignment: .firstTextBaseline, spacing: 6) {
                                Image(systemName: result.ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                                    .font(.dsSymbol(12, .semibold))
                                    .foregroundStyle(result.ok ? DS.ok : DS.warn)
                                Text("\(result.email) — \(result.text)")
                                    .font(.dsMeta)
                                    .foregroundStyle(DS.text1)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                            .accessibilityElement(children: .combine)
                        }
                    }
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
                    .font(.dsMono(11))
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
        HStack(spacing: 10) {
            DSAvatar(name: invite.email, size: 30)
            VStack(alignment: .leading, spacing: 0) {
                Text(invite.email)
                    .font(.ds(14, .medium))
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
                DSMenu {
                    [
                        .item("Resend", symbol: "arrow.clockwise") { Task { await resend(invite) } },
                        .item("Revoke", symbol: "xmark.circle", danger: true) { Task { await revoke(invite) } },
                    ]
                }
                .accessibilityLabel("Invitation actions for \(invite.email)")
            }
        }
        .padding(.horizontal, 4)
        .frame(minHeight: 40)
        // The row lives in a card, not a List, so there is no swipe; VoiceOver gets both actions on the row.
        .accessibilityElement(children: .combine)
        .accessibilityAction(named: "Resend") { Task { await resend(invite) } }
        .accessibilityAction(named: "Revoke") { Task { await revoke(invite) } }
    }

    private func pendingLine(_ invite: Invitation) -> String {
        let role = WorkspaceRoles.label(invite.role)
        if invite.notSent { return "\(role) · Not sent — Resend" }
        let times = invite.sentCount == 1 ? "Sent" : "Sent \(invite.sentCount)×"
        return "\(role) · \(times) · expires \(formatDateTime(invite.expiresAt))"
    }

    // MARK: - Actions

    /// Every address typed or pasted, once each, in order.
    private var addresses: [String] { InviteAddresses.split(email) }

    private var canManage: Bool { tenant?.canManageMembers ?? false }

    private var manage: WorkspaceRoster.Manage {
        WorkspaceRoster.Manage(
            selfId: app.identity?.id,
            isOwner: tenant?.myRole == "owner",
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

    /// One invitation per address, one at a time: the first may ask for recent proof, the rest ride on it.
    /// Addresses that failed stay in the field; nothing typed is lost.
    private func send() async {
        let list = addresses
        guard let tenant, !list.isEmpty, !sending, canManage else { return }
        sending = true
        results = []
        defer { sending = false }
        let note = message.trimmingCharacters(in: .whitespacesAndNewlines)
        var lines: [InviteResult] = []
        var failed: [String] = []
        for address in list {
            do {
                // `403 reauth_required` is answered inside `APIClient` (step-up + one retry).
                let invite = try await app.api.invite(tenantId: tenant.id, email: address, role: role, message: note)
                pending.removeAll { $0.id == invite.id }
                pending.insert(invite, at: 0)
                lines.append(invite.notSent
                    ? InviteResult(email: address, ok: false, text: "Saved, but the e-mail didn't go out. Resend it from Pending.")
                    : InviteResult(email: address, ok: true, text: "Sent"))
            } catch {
                // Already in: nothing to do, nothing to retry.
                if AuthCopy.code(of: error) != "already_member" { failed.append(address) }
                lines.append(InviteResult(email: address, ok: AuthCopy.code(of: error) == "already_member",
                                          text: AuthCopy.message(for: error)))
            }
        }
        results = lines
        email = failed.joined(separator: "\n")
        if failed.isEmpty { message = "" }
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

/// "In this workspace" — who is here and what they may do; owners and admins also change roles and remove people.
struct WorkspaceRoster: View {
    /// What a manager may do to a row; each returns what went wrong, or nil.
    struct Manage {
        /// The signed-in person's row gets no actions (leaving is in Account).
        let selfId: String?
        /// Owners' rows, and the owner role itself, are an owner's to change (`owner_only`).
        let isOwner: Bool
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
                        MemberRow(member: member, busy: busy == member.userSub, actions: actions(for: member))
                    }
                }
            }
            if let actionError {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: actionError)
            }
        }
        .dsCard()
        .confirmationDialog("Remove \(removing?.title ?? "")?",
                            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
                            titleVisibility: .visible) {
            Button("Remove", role: .destructive) {
                if let member = removing { run(member) { await $0.remove(member) } }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("They lose access to this workspace's notes and meetings. You can invite them again later.")
        }
    }

    /// "4 of 3 free seats" (display only; nothing is blocked on it), else the head count.
    private var seatLine: String? {
        if let seats, let limit = seats.limit { return "\(seats.active) of \(limit) free seats" }
        return members.isEmpty ? nil : "\(members.count)"
    }

    private func actions(for member: TenantMember) -> [DSMenuItem]? {
        guard let manage, member.userSub != manage.selfId, member.leftAt == nil,
              member.status == "active", member.role != "owner" || manage.isOwner else { return nil }
        let roles = (manage.isOwner ? ["owner"] : []) + WorkspaceRoles.invitable
        var items: [DSMenuItem] = roles
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
            if let leftAt = member.leftAt {
                DSChip(text: "Left \(relativeTime(leftAt))", tint: DS.muted, soft: DS.surface2)
            } else if member.status != "active" {
                DSChip(text: member.status.capitalized, tint: DS.warn, soft: DS.warnSoft)
            }
            Text(WorkspaceRoles.label(member.role))
                .font(.dsMeta)
                .foregroundStyle(DS.text3)
            if busy {
                ProgressView().controlSize(.small)
            } else if let actions {
                DSMenu { actions }
                    .accessibilityLabel("Role and access for \(member.title)")
            }
        }
        .padding(.horizontal, 4)
        .frame(minHeight: 40)
        // Combined when there is no menu to reach.
        .accessibilityElement(children: actions == nil ? .combine : .contain)
    }
}

/// What one address got from "Invite".
struct InviteResult: Identifiable, Equatable {
    let email: String
    let ok: Bool
    let text: String

    var id: String { email }
}

/// Addresses out of a pasted block: split on commas, semicolons, spaces and new lines; one each.
enum InviteAddresses {
    static func split(_ text: String) -> [String] {
        var seen = Set<String>()
        return text.split(whereSeparator: { ",;\n\t ".contains($0) })
            .map { String($0).trimmingCharacters(in: CharacterSet(charactersIn: "<>\"'")) }
            .filter { $0.contains("@") && seen.insert($0.lowercased()).inserted }
    }
}
