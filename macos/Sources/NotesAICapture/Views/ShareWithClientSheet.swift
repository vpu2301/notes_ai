import AppKit
import SwiftUI

/// "Share with client…" — one link per recipient (Sprint 19).
///
/// Same rules as on iOS: a label, an optional address and an expiry. On
/// create the URL is copied to the pasteboard and an "Email…" button
/// offers a mail draft with it.
struct ShareWithClientSheet: View {
    @ObservedObject var model: NoteViewModel
    let webAppURL: String
    let onClose: () -> Void
    /// Where the sender was when they opened this ("native" | "nudge").
    var source: String = "native"

    @State private var label = ""
    @State private var email = ""
    @State private var message = ""
    @State private var days = 90
    @State private var emailError: String?
    @State private var created: URL?

    private static let allExpiryOptions = [30, 90, 180]
    /// Clipped to what the workspace allows (Sprint 23).
    private var expiryOptions: [Int] {
        let allowed = Self.allExpiryOptions.filter { $0 <= model.rules.maxLinkDays }
        return allowed.isEmpty ? [min(model.rules.maxLinkDays, 30)] : allowed
    }

    private var emailRequired: Bool { model.rules.verifiedRecipientsRequired }
    private var hasEmail: Bool { !email.trimmingCharacters(in: .whitespaces).isEmpty }

    private var canCreate: Bool {
        (!label.trimmingCharacters(in: .whitespaces).isEmpty || hasEmail)
            && !model.busy
            && (!emailRequired || hasEmail)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            DSDivider()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    form
                    if emailRequired {
                        Text("Recipients must confirm an e-mailed code before they can respond — set by your workspace admin.")
                            .font(.dsMeta).foregroundStyle(DS.muted).fixedSize(horizontal: false, vertical: true)
                    }
                    if let emailError {
                        DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: emailError)
                    }
                    if let sent = model.lastSent {
                        DSNotice(tone: sent.deliveryStatus == .sent ? .ok : .warn,
                                 symbol: sent.deliveryStatus == .sent ? "paperplane.fill" : "exclamationmark.triangle.fill",
                                 text: sent.deliveryStatus == .sent
                                    ? "Sent to \(sent.recipientEmail ?? sent.label)."
                                    : "The e-mail did not go out. You can retry or copy the link.")
                    }
                    if let error = model.actionError {
                        DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                    }
                    if let created {
                        createdRow(created)
                    }
                    if !model.recipientLinks.isEmpty {
                        links
                    }
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            DSDivider()
            footer
        }
        .frame(width: 480)
        .background(DS.bg)
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Share with client")
                .font(.dsDisplay(17, .medium))
                .foregroundStyle(DS.text1)
            Text(model.content?.title?.isEmpty == false ? model.content!.title! : "Untitled note")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
    }

    private var footer: some View {
        HStack(spacing: 10) {
            Text("Each person gets their own link; you see who opened it and can turn one off without the others.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            Button("Close", action: onClose)
                .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                .keyboardShortcut(.cancelAction)
            if hasEmail {
                Button("Create link only") { Task { await create() } }
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                    .disabled(!canCreate)
            }
            Button {
                Task { await create(send: hasEmail) }
            } label: {
                if model.busy {
                    ProgressView().controlSize(.small).frame(width: 34)
                } else {
                    // Sprint 22: with an address, the product sends the mail.
                    Label(hasEmail ? "Send e-mail" : "Create link", systemImage: hasEmail ? "envelope" : "link")
                }
            }
            .buttonStyle(DSButtonStyle(kind: .primary, height: 28))
            .disabled(!canCreate)
            .keyboardShortcut(.defaultAction)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
    }

    private var form: some View {
        VStack(alignment: .leading, spacing: 8) {
            DSLabel("Who is it for?")
            DSTextField(placeholder: "e.g. Tom @ Client", text: $label)
            DSTextField(placeholder: "Their e-mail (optional)", text: $email)
                .onChange(of: email) { _, _ in emailError = nil }
            Picker("Expires", selection: $days) {
                ForEach(expiryOptions, id: \.self) { d in Text("\(d) days").tag(d) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            if hasEmail {
                DSTextField(placeholder: "Add a personal note (optional)", text: $message)
            }
        }
    }

    private func createdRow(_ url: URL) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            DSLabel("Link copied")
            HStack(spacing: 8) {
                Text(url.absoluteString)
                    .font(.dsMono(12))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer()
                Button("Copy") { copy(url.absoluteString) }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
                Button("Email…") { emailLink(url: url, to: email) }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
            }
        }
        .dsCard()
    }

    private var links: some View {
        VStack(alignment: .leading, spacing: 8) {
            DSLabel("Client links")
            ForEach(model.recipientLinks) { link in
                HStack(spacing: 10) {
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: 6) {
                            Text(link.label.isEmpty ? (link.recipientEmail ?? "Link") : link.label)
                                .font(.ds(13, .medium))
                                .foregroundStyle(DS.text1)
                            if link.ctaClickedAt != nil {
                                Circle().fill(DS.accent).frame(width: 7, height: 7)
                                    .help("Clicked “create your own workspace”")
                            }
                        }
                        Text(link.statusLine).font(.dsMeta).foregroundStyle(DS.muted)
                    }
                    Spacer()
                    if link.canSend {
                        Button(link.deliveryStatus == .failed ? "Retry" : (link.sendCount ?? 0) > 0 ? "Resend" : "Send") {
                            Task { await model.sendLink(link) }
                        }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
                        .disabled(model.busy)
                    }
                    Button("Copy") {
                        if let url = model.linkURL(link, webAppURL: webAppURL) { copy(url.absoluteString) }
                    }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
                    Button("Turn off") { Task { await model.revokeLink(link) } }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
                        .disabled(model.busy)
                }
            }
        }
        .dsCard()
    }

    private func create(send: Bool = false) async {
        let trimmedEmail = email.trimmingCharacters(in: .whitespaces)
        if !trimmedEmail.isEmpty, !ShareEmailSheet.looksLikeEmail(trimmedEmail) {
            emailError = "“\(trimmedEmail)” doesn’t look like an e-mail address."
            return
        }
        let trimmedLabel = label.trimmingCharacters(in: .whitespaces)
        if let url = await model.createRecipientLink(
            label: trimmedLabel.isEmpty ? trimmedEmail : trimmedLabel,
            email: trimmedEmail,
            expiresInDays: days,
            webAppURL: webAppURL,
            send: send,
            message: message.trimmingCharacters(in: .whitespacesAndNewlines),
            source: source
        ) {
            if send {
                // Sent by the product: nothing to copy unless they ask.
                message = ""
            } else {
                copy(url.absoluteString)
                created = url
            }
            label = ""
            email = ""
        }
    }

    private func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    /// A mail draft with the link — the sender's own mail client, since
    /// the product does not send recipient links itself until Sprint 22.
    private func emailLink(url: URL, to address: String) {
        var parts = URLComponents()
        parts.scheme = "mailto"
        parts.path = address
        let subject = model.content?.title?.isEmpty == false ? model.content!.title! : "Meeting notes"
        parts.queryItems = [
            URLQueryItem(name: "subject", value: subject),
            URLQueryItem(name: "body", value: url.absoluteString),
        ]
        if let mailto = parts.url { NSWorkspace.shared.open(mailto) }
    }
}
