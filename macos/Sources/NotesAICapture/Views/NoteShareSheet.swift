import AppKit
import SwiftUI

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
    @State private var outcome: String?
    /// The public link's own sheet, opened when the link is made.
    @State private var publicOpen = false

    private var addresses: [String] {
        emails.split(whereSeparator: { " ,;\n".contains($0) })
            .map { String($0).trimmingCharacters(in: .whitespaces) }
            .filter { $0.contains("@") }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            DSDivider()
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    people
                    generalAccess
                    links
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            DSDivider()
            HStack {
                Spacer()
                Button("Done", action: onClose)
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                    .keyboardShortcut(.cancelAction)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
        }
        .frame(width: 500, height: 600)
        .background(DS.bg)
        .task { await model.loadSharing() }
        .sheet(isPresented: $publicOpen) {
            PublicLinkSheet(
                noteTitle: model.content?.title ?? "",
                link: model.sharing?.publicLink,
                url: model.publicURL(webAppURL: webAppURL),
                busy: model.busy,
                error: model.actionError,
                renew: { await model.renewPublicLink(expiresInDays: $0) },
                turnOff: {
                    await model.revokePublicLink()
                    return model.sharing?.publicLink == nil
                },
                onClose: { publicOpen = false })
        }
    }

    private var noteTitle: String {
        let title = model.content?.title?.trimmingCharacters(in: .whitespaces) ?? ""
        return title.isEmpty ? "Untitled note" : title
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Share")
                .font(.dsDisplay(17, .medium))
                .foregroundStyle(DS.text1)
            Text(noteTitle)
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
    }

    // MARK: - People

    private var people: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSLabel("People")
            HStack(spacing: 8) {
                DSTextField(placeholder: "Add people by e-mail", text: $emails)
                    .onSubmit { invite() }
                    .onChange(of: emails) { _, _ in outcome = nil }
                DSSelect(options: NoteLevel.grantable.map { .init(value: $0, label: $0.label) },
                         selection: $role, width: 132, height: 32)
                Button("Invite") { invite() }
                    .buttonStyle(DSButtonStyle(kind: .primary, height: 32))
                    .disabled(addresses.isEmpty || model.busy)
            }
            if !addresses.isEmpty {
                DSTextField(placeholder: "Message (optional)", text: $message)
            }
            Text("People in your workspace get access now; others get an e-mail and sign in to see this note.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
            if let outcome {
                DSNotice(tone: .ok, symbol: "checkmark.circle.fill", text: outcome)
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
                            .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 24))
                            .disabled(model.busy)
                    }
                }
            }
        }
    }

    private func personRow(_ person: NotePerson) -> some View {
        HStack(spacing: 10) {
            DSAvatar(name: person.title, size: 28, collaborator: true)
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 6) {
                    Text(person.title)
                        .font(.ds(13, .medium))
                        .foregroundStyle(DS.text1)
                        .lineLimit(1)
                    if person.isGuest {
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
                DSMenu(width: 180, items: { roleItems(person) }) {
                    HStack(spacing: 4) {
                        Text(person.level.label)
                        Image(systemName: "chevron.down").font(.dsIcon(9, .semibold))
                    }
                    .font(.ds(12.5))
                    .foregroundStyle(DS.text2)
                    .padding(.horizontal, 8)
                    .frame(height: 26)
                    .contentShape(Rectangle())
                }
            } else {
                Text(person.isAuthor ? "Author" : person.level.label)
                    .font(.ds(12.5))
                    .foregroundStyle(DS.muted)
            }
        }
        .padding(.vertical, 6)
    }

    private func roleItems(_ person: NotePerson) -> [DSMenuItem] {
        var items = NoteLevel.grantable.map { level in
            DSMenuItem.item(level.label, checked: level == person.level) {
                Task { await model.setRole(person, level) }
            }
        }
        items.append(.separator)
        items.append(.item("Remove", symbol: "person.badge.minus", danger: true) {
            Task { await model.remove(person) }
        })
        return items
    }

    private func row(symbol: String, title: String, detail: String,
                     @ViewBuilder trailing: () -> some View) -> some View {
        HStack(spacing: 10) {
            Image(systemName: symbol)
                .font(.dsIcon(12))
                .foregroundStyle(DS.text3)
                .frame(width: 28, height: 28)
                .background(Circle().fill(DS.surface2))
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(.ds(13, .medium)).foregroundStyle(DS.text1).lineLimit(1)
                Text(detail).font(.dsMeta).foregroundStyle(DS.muted)
            }
            Spacer(minLength: 8)
            trailing()
        }
        .padding(.vertical, 6)
    }

    private func invite() {
        let list = addresses
        guard !list.isEmpty, !model.busy else { return }
        Task {
            guard let done = await model.invite(emails: list, role: role, message: message) else { return }
            emails = ""
            message = ""
            var parts: [String] = []
            if done.granted > 0 { parts.append("\(done.granted) can open it now") }
            if done.invited > 0 { parts.append("\(done.invited) invited by e-mail") }
            outcome = parts.joined(separator: " · ")
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
                    options: [.init(false, label: "Only people above", symbol: "lock"),
                              .init(true, label: "Everyone in the workspace", symbol: "person.2")],
                    selection: Binding(get: { model.isWorkspaceVisible },
                                       set: { on in Task { await model.setWorkspaceVisible(on) } }),
                    height: 30)
                .disabled(model.busy)
            }
            Toggle("Include transcript for viewers and commenters", isOn: Binding(
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
            HStack(spacing: 8) {
                Button {
                    sendLink()
                } label: {
                    Label("Share with client…", systemImage: "paperplane")
                }
                .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                Button {
                    sendEmail()
                } label: {
                    Label("Send by e-mail…", systemImage: "envelope")
                }
                .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
            }
            HStack(spacing: 8) {
                Button {
                    Task {
                        // Making the link opens its sheet; an existing one is just copied.
                        let made = !hasLink
                        guard let url = await model.publicLinkURL(webAppURL: webAppURL) else { return }
                        if made {
                            publicOpen = true
                        } else {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(url.absoluteString, forType: .string)
                        }
                    }
                } label: {
                    Label(hasLink ? "Copy public link" : "Create public link", systemImage: "globe")
                }
                .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                .disabled(model.busy)
                if hasLink {
                    Button("Turn off") { Task { await model.revokePublicLink() } }
                        .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 28))
                        .disabled(model.busy)
                }
            }
            Text("A link opens a read-only copy without an account.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
        }
    }
}
