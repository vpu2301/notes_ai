import SwiftUI
import UIKit

/// "Share…" — everything about who can open a note, in one place: people by role, pending
/// invitations, general access, the transcript, and the client-facing links.
struct NoteShareSheet: View {
    @ObservedObject var model: NoteViewModel
    let webAppURL: String
    /// "Share with client…": the recipient-link sheet takes over.
    let sendLink: () -> Void
    /// "Send by e-mail…": the server mails the link (members are pointed at the note).
    let sendEmail: () -> Void
    let onClose: () -> Void

    @State private var emails = ""
    @State private var role: NoteLevel = .comment
    @State private var message = ""
    /// One line per address of the last "Invite".
    @State private var results: [InviteResult] = []

    private var addresses: [String] { InviteAddresses.split(emails) }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 26) {
                    people
                    generalAccess
                    links
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(DS.bg)
            .navigationTitle("Share")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) { Button("Done", action: onClose) }
            }
        }
        .task { await model.loadSharing() }
    }

    // MARK: - People

    private var people: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSLabel("People")
            DSTextField(placeholder: "Add people by e-mail", text: $emails)
                .textInputAutocapitalization(.never)
                .keyboardType(.emailAddress)
                .autocorrectionDisabled()
                .accessibilityLabel("Add people by e-mail")
            if !addresses.isEmpty {
                DSTextField(placeholder: "Message (optional)", text: $message)
            }
            HStack(spacing: 8) {
                DSSelect(options: NoteLevel.grantable.map { .init(value: $0, label: $0.label) },
                         selection: $role)
                    .accessibilityLabel("Role: \(role.label)")
                Button("Invite") { invite() }
                    .buttonStyle(DSButtonStyle(kind: .primary, size: 15, height: 38))
                    .disabled(addresses.isEmpty || model.busy)
            }
            Text("People in your workspace get access now; others get an e-mail and sign in to see this note.")
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
            if let error = model.actionError {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
            }

            VStack(spacing: 0) {
                ForEach(model.sharing?.namedPeople ?? []) { person in
                    personRow(person)
                }
                if model.isWorkspaceVisible {
                    row(symbol: "person.2", title: "Everyone in the workspace",
                        detail: "Members can edit · viewers can comment") {
                        EmptyView()
                    }
                }
                ForEach(model.sharing?.pending ?? []) { invite in
                    row(symbol: "envelope", title: invite.emailMasked,
                        detail: "Invited · \(invite.noteRole.label.lowercased())") {
                        Button("Revoke") { Task { await model.revoke(invite) } }
                            .font(.ds(14))
                            .disabled(model.busy)
                            .accessibilityLabel("Revoke invitation for \(invite.emailMasked)")
                    }
                }
            }
        }
    }

    private func personRow(_ person: NotePerson) -> some View {
        HStack(spacing: 10) {
            DSAvatar(name: person.title, size: 32)
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 6) {
                    Text(person.title)
                        .font(.ds(15, .medium))
                        .foregroundStyle(DS.text1)
                        .lineLimit(1)
                    if person.isAuthor {
                        DSChip(text: "Author", tint: DS.text3, soft: DS.surface2)
                    } else if person.isGuest {
                        DSChip(text: "Guest", tint: DS.text3, soft: DS.surface2)
                    }
                }
                if !person.email.isEmpty, person.email != person.title {
                    Text(person.email)
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 8)
            if person.canChange {
                Menu {
                    ForEach(NoteLevel.grantable, id: \.self) { level in
                        Button {
                            Task { await model.setRole(person, level) }
                        } label: {
                            if level == person.level { Label(level.label, systemImage: "checkmark") } else { Text(level.label) }
                        }
                    }
                    Divider()
                    Button(role: .destructive) {
                        Task { await model.remove(person) }
                    } label: {
                        Label("Remove", systemImage: "person.badge.minus")
                    }
                } label: {
                    HStack(spacing: 4) {
                        Text(person.level.label)
                        Image(systemName: "chevron.down").font(.dsSymbol(10, .semibold))
                    }
                    .font(.ds(14))
                    .foregroundStyle(DS.text2)
                }
                .accessibilityLabel("Role for \(person.title): \(person.level.label)")
            } else {
                Text(person.level.label)
                    .font(.ds(14))
                    .foregroundStyle(DS.muted)
            }
        }
        .padding(.vertical, 8)
        .accessibilityElement(children: person.canChange ? .contain : .combine)
        // Remove without opening the menu (VoiceOver's rotor).
        .accessibilityActions {
            if person.canChange {
                Button("Remove \(person.title)") { Task { await model.remove(person) } }
            }
        }
    }

    private func row(symbol: String, title: String, detail: String,
                     @ViewBuilder trailing: () -> some View) -> some View {
        HStack(spacing: 10) {
            Image(systemName: symbol)
                .font(.dsSymbol(13))
                .foregroundStyle(DS.text3)
                .frame(width: 32, height: 32)
                .background(Circle().fill(DS.surface2))
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(.ds(15, .medium)).foregroundStyle(DS.text1).lineLimit(1)
                Text(detail).font(.dsMeta).foregroundStyle(DS.muted)
            }
            Spacer(minLength: 8)
            trailing()
        }
        .padding(.vertical, 8)
    }

    private func invite() {
        let list = addresses
        guard !list.isEmpty, !model.busy else { return }
        Task {
            let done = await model.invite(emails: list, role: role, message: message)
            results = done
            // The ones that did not get access stay in the field to try again.
            let failed = done.filter { !$0.ok }.map(\.email)
            emails = failed.joined(separator: ", ")
            if failed.isEmpty { message = "" }
        }
    }

    // MARK: - General access

    private var generalAccess: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSLabel("General access")
            if model.sharing?.isPersonalWorkspace == true {
                Text("Only the people above. Notes in your personal workspace are never shared with a whole workspace.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                DSSegmentedPill(
                    options: [.init(false, label: "Private"),
                              .init(true, label: "Workspace")],
                    selection: Binding(get: { model.isWorkspaceVisible },
                                       set: { on in Task { await model.setWorkspaceVisible(on) } }),
                    height: 36)
                .disabled(model.busy)
            }
            Toggle("Include transcript and audio for viewers and commenters", isOn: Binding(
                get: { model.sharing?.transcriptShared ?? false },
                set: { on in Task { await model.setTranscriptShared(on) } }))
                .toggleStyle(DSToggleStyle())
                .disabled(model.busy)
            Text("Editors always see the transcript and audio. Viewers, commenters and guests see them only while this is on.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    // MARK: - Links

    private var links: some View {
        let hasLink = model.sharing?.publicLink != nil
        return VStack(alignment: .leading, spacing: 10) {
            DSLabel("Send a link")
            if model.rules.externalLinksEnabled {
                // One link per recipient; absent when the admin switched it off.
                linkButton("Share with client…", symbol: "paperplane", action: sendLink)
            }
            linkButton("Send by e-mail…", symbol: "envelope", action: sendEmail)
            linkButton(hasLink ? "Copy public link" : "Create public link", symbol: "globe") {
                Task {
                    if let url = await model.publicLinkURL(webAppURL: webAppURL) {
                        UIPasteboard.general.string = url.absoluteString
                    }
                }
            }
            if hasLink {
                linkButton("Turn off public link", symbol: "globe.badge.chevron.backward") {
                    Task { await model.revokePublicLink() }
                }
            }
            Text("A link opens a read-only copy without an account.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
        }
    }

    private func linkButton(_ title: String, symbol: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: symbol)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .buttonStyle(DSButtonStyle(kind: .secondary, size: 15, height: 42, fill: true))
        .disabled(model.busy)
    }
}
