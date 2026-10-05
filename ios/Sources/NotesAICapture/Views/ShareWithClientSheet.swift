import SwiftUI

/// "Share with client…" — one link per recipient (Sprint 19).
///
/// A label so the sender knows who has which link, an optional address
/// (a label too, and Sprint 22's delivery address), and an expiry. On
/// success the system share sheet opens with the URL so it can go by
/// Mail, Messages or WhatsApp.
struct ShareWithClientSheet: View {
    @ObservedObject var model: NoteViewModel
    let webAppURL: String
    let onCreated: (URL) -> Void
    let onClose: () -> Void

    @State private var label = ""
    @State private var email = ""
    @State private var days = 90
    @State private var emailError: String?

    private static let allExpiryOptions = [30, 90, 180]
    /// Clipped to what the workspace allows (Sprint 23).
    private var expiryOptions: [Int] {
        let allowed = Self.allExpiryOptions.filter { $0 <= model.rules.maxLinkDays }
        return allowed.isEmpty ? [min(model.rules.maxLinkDays, 30)] : allowed
    }

    private var emailRequired: Bool { model.rules.verifiedRecipientsRequired }

    private var canCreate: Bool {
        (!label.trimmingCharacters(in: .whitespaces).isEmpty || !email.trimmingCharacters(in: .whitespaces).isEmpty)
            && !model.busy
            && (!emailRequired || !email.trimmingCharacters(in: .whitespaces).isEmpty)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    form
                    if let emailError {
                        DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: emailError)
                    }
                    if let error = model.actionError {
                        DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: error)
                    }
                    if !model.recipientLinks.isEmpty {
                        links
                    }
                    if emailRequired {
                        Text("Recipients must confirm an e-mailed code before they can respond — set by your workspace admin.")
                            .font(.dsMeta).foregroundStyle(DS.muted).fixedSize(horizontal: false, vertical: true)
                    }
                    Text("Each person gets their own link, so you can see who opened it and turn one off without the others. Links expire on their own.")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(DS.bg)
            .navigationTitle("Share with client")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Close", action: onClose) }
                ToolbarItem(placement: .topBarTrailing) {
                    if model.busy {
                        ProgressView().controlSize(.small)
                    } else {
                        Button("Create") { Task { await create() } }.disabled(!canCreate)
                    }
                }
            }
        }
    }

    private var form: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSLabel("Who is it for?")
            DSTextField(placeholder: "e.g. Tom @ Client", text: $label)
            DSTextField(placeholder: "Their e-mail (optional)", text: $email)
                .keyboardType(.emailAddress)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .onChange(of: email) { _, _ in emailError = nil }
            Picker("Expires", selection: $days) {
                ForEach(expiryOptions, id: \.self) { d in Text("\(d) days").tag(d) }
            }
            .pickerStyle(.segmented)
        }
        .dsCard()
    }

    private var links: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSLabel("Client links")
            ForEach(model.recipientLinks) { link in
                HStack(spacing: 10) {
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: 6) {
                            Text(link.label.isEmpty ? (link.recipientEmail ?? "Link") : link.label)
                                .font(.ds(15, .medium))
                                .foregroundStyle(DS.text1)
                            if link.ctaClickedAt != nil {
                                Circle().fill(DS.accent).frame(width: 7, height: 7)
                                    .accessibilityLabel("Clicked create your own workspace")
                            }
                        }
                        Text(link.statusLine).font(.dsMeta).foregroundStyle(DS.muted)
                    }
                    Spacer()
                    if link.canSend {
                        Button {
                            Task { await model.sendLink(link) }
                        } label: { Image(systemName: "paperplane") }
                        .buttonStyle(.plain)
                        .disabled(model.busy)
                        .accessibilityLabel(link.deliveryStatus == .failed ? "Retry" : (link.sendCount ?? 0) > 0 ? "Resend" : "Send")
                    }
                    Button {
                        if let url = model.linkURL(link, webAppURL: webAppURL) { onCreated(url) }
                    } label: { Image(systemName: "square.and.arrow.up") }
                    .buttonStyle(.plain)
                    .disabled(model.busy)
                }
                .swipeActions(edge: .trailing) {
                    Button("Turn off", role: .destructive) { Task { await model.revokeLink(link) } }
                }
                .contextMenu {
                    Button("Turn off link", role: .destructive) { Task { await model.revokeLink(link) } }
                }
            }
        }
        .dsCard()
    }

    private func create() async {
        let trimmedEmail = email.trimmingCharacters(in: .whitespaces)
        if !trimmedEmail.isEmpty, !ShareEmailSheet.looksLikeEmail(trimmedEmail) {
            emailError = "“\(trimmedEmail)” doesn’t look like an e-mail address."
            return
        }
        if let url = await model.createRecipientLink(
            label: label.trimmingCharacters(in: .whitespaces),
            email: trimmedEmail,
            expiresInDays: days,
            webAppURL: webAppURL
        ) {
            label = ""
            email = ""
            onCreated(url)
        }
    }
}
