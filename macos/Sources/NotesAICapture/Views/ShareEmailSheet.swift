import SwiftUI

/// "Send this note" — pick who gets it, add a line, press Send.
///
/// This replaces the old `mailto:` hand-off. That opened the Mac's mail
/// client with an unstyled draft the sender still had to send, and Mail
/// brings whatever it already had open to the front with it — which is
/// how sharing a link ended up showing somebody an old message with an
/// old attachment. Nothing here touches the mail client: the server
/// sends the mail, and the sheet reports what happened to each address.
struct ShareEmailSheet: View {
    let noteTitle: String
    /// Sends, and hands back one outcome per recipient (nil = the call
    /// itself failed; the reason is already on the view model's error).
    let send: ([String], String) async -> [ShareEmailOutcome]?
    let onClose: () -> Void

    @State private var recipients: [String] = []
    @State private var draft = ""
    @State private var draftError: String?
    @State private var message = ""
    @State private var sending = false
    @State private var failures: [ShareEmailOutcome] = []
    @State private var sentCount = 0

    @FocusState private var addressFocused: Bool

    /// Loose shape check — the real test is whether a relay accepts it,
    /// and this only has to keep obvious typos out of the chip list.
    static func looksLikeEmail(_ value: String) -> Bool {
        guard !value.contains(where: \.isWhitespace) else { return false }
        let parts = value.split(separator: "@", omittingEmptySubsequences: false)
        guard parts.count == 2, let local = parts.first, let domain = parts.last else { return false }
        return !local.isEmpty && domain.contains(".")
            && !domain.hasPrefix(".") && !domain.hasSuffix(".")
    }

    private var trimmedDraft: String {
        draft.trimmingCharacters(in: .whitespaces).trimmingCharacters(in: CharacterSet(charactersIn: ",;"))
    }

    /// Everything typed so far, including the address still in the box —
    /// pressing Send with one address typed and not committed must not
    /// send to nobody.
    private var allRecipients: [String] {
        var all = recipients
        let typed = trimmedDraft
        if !typed.isEmpty, Self.looksLikeEmail(typed),
           !all.contains(where: { $0.lowercased() == typed.lowercased() }) {
            all.append(typed)
        }
        return all
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            DSDivider()
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    addressBox
                    messageBox
                    if let draftError {
                        DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: draftError)
                    }
                    if !failures.isEmpty {
                        DSNotice(tone: .warn, symbol: "envelope.badge", text: failureText)
                    }
                    if sentCount > 0, failures.isEmpty {
                        DSNotice(tone: .ok, symbol: "checkmark.circle.fill",
                                 text: sentCount == 1 ? "Sent." : "Sent to \(sentCount) people.")
                    }
                }
                .padding(20)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            DSDivider()
            footer
        }
        .frame(width: 460)
        .background(DS.bg)
        .onAppear { addressFocused = true }
    }

    // MARK: - Header / footer

    private var header: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Send this note")
                .font(.dsDisplay(17, .medium))
                .foregroundStyle(DS.text1)
            Text(noteTitle.isEmpty ? "Untitled note" : noteTitle)
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
            Text("People in your workspace get access to the note. Anyone else gets a link they can open without signing in.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 8)
            Button("Close", action: onClose)
                .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                .keyboardShortcut(.cancelAction)
            Button {
                Task { await sendNow() }
            } label: {
                if sending {
                    ProgressView().controlSize(.small).frame(width: 34)
                } else {
                    Label("Send", systemImage: "paperplane")
                }
            }
            .buttonStyle(DSButtonStyle(kind: .primary, height: 28))
            .disabled(sending || allRecipients.isEmpty)
            .keyboardShortcut(.defaultAction)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
    }

    // MARK: - Addresses

    private var addressBox: some View {
        VStack(alignment: .leading, spacing: 8) {
            DSLabel("Send to")
            if !recipients.isEmpty {
                // A wrapping row of chips. `FlowLayout` is overkill for
                // the handful of addresses this sheet accepts, so they
                // stack in a grid that wraps at the sheet's width.
                DSChipWrap(items: recipients) { address in
                    RecipientChip(address: address, disabled: sending) {
                        recipients.removeAll { $0 == address }
                    }
                }
            }
            HStack(spacing: 8) {
                DSTextField(placeholder: "name@company.com", text: $draft)
                    .focused($addressFocused)
                    .onSubmit { _ = commitDraft() }
                    .onChange(of: draft) { _, value in
                        draftError = nil
                        // A separator means the address before it is
                        // finished — the same reflex as any mail client.
                        if value.hasSuffix(",") || value.hasSuffix(";") || value.hasSuffix(" ") {
                            _ = commitDraft()
                        }
                    }
                Button("Add") { _ = commitDraft() }
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 32))
                    .disabled(sending || trimmedDraft.isEmpty)
            }
        }
        .dsCard()
    }

    private var messageBox: some View {
        VStack(alignment: .leading, spacing: 8) {
            DSLabel("Message")
            TextEditor(text: $message)
                .font(.ds(13))
                .foregroundStyle(DS.text1)
                .scrollContentBackground(.hidden)
                .padding(.horizontal, 6)
                .padding(.vertical, 6)
                .frame(height: 84)
                .background(
                    RoundedRectangle(cornerRadius: DS.radius, style: .continuous).fill(DS.surface)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                        .strokeBorder(DS.line, lineWidth: DS.hairline)
                )
                .overlay(alignment: .topLeading) {
                    if message.isEmpty {
                        Text("Add a message (optional)")
                            .font(.ds(13))
                            .foregroundStyle(DS.muted)
                            .padding(.horizontal, 11)
                            .padding(.vertical, 14)
                            .allowsHitTesting(false)
                    }
                }
                .disabled(sending)
        }
        .dsCard()
    }

    // MARK: - Behaviour

    /// Turn what is typed into a chip. False when it is not an address.
    @discardableResult
    private func commitDraft() -> Bool {
        let address = trimmedDraft
        guard !address.isEmpty else {
            draft = ""
            return true
        }
        guard Self.looksLikeEmail(address) else {
            draftError = "“\(address)” doesn’t look like an e-mail address."
            return false
        }
        draftError = nil
        draft = ""
        if !recipients.contains(where: { $0.lowercased() == address.lowercased() }) {
            recipients.append(address)
        }
        return true
    }

    private func sendNow() async {
        guard commitDraft() || !allRecipients.isEmpty else { return }
        let to = allRecipients
        guard !to.isEmpty else {
            draftError = "Add at least one e-mail address."
            return
        }
        sending = true
        failures = []
        sentCount = 0
        defer { sending = false }
        guard let results = await send(to, message.trimmingCharacters(in: .whitespacesAndNewlines)) else {
            return
        }
        sentCount = results.filter(\.sent).count
        failures = results.filter { !$0.sent }
        // Only the addresses that failed stay in the box, so pressing
        // Send again retries exactly those and not the ones that went.
        recipients = failures.map(\.email)
        draft = ""
        if failures.isEmpty { message = "" }
    }

    private var failureText: String {
        let names = failures.map(\.email).joined(separator: ", ")
        let refusedOnly = failures.allSatisfy { $0.status == "rejected" }
        return refusedOnly
            ? "\(names) did not go out — the address was refused. Check the spelling."
            : "\(names) did not go out — the mail server did not take it. Try again in a moment."
    }
}

// MARK: - Chips

/// One confirmed recipient, with the way to take it back out.
private struct RecipientChip: View {
    let address: String
    let disabled: Bool
    let remove: () -> Void

    var body: some View {
        HStack(spacing: 4) {
            Text(address)
                .font(.ds(12))
                .foregroundStyle(DS.text2)
                .lineLimit(1)
            Button(action: remove) {
                Image(systemName: "xmark")
                    .font(.ds(9, .semibold))
                    .foregroundStyle(DS.muted)
            }
            .buttonStyle(.plain)
            .disabled(disabled)
            .accessibilityLabel("Remove \(address)")
        }
        .padding(.leading, 9)
        .padding(.trailing, 6)
        .padding(.vertical, 4)
        .background(Capsule().fill(DS.surface2))
        .overlay(Capsule().strokeBorder(DS.line2, lineWidth: DS.hairline))
    }
}

/// A row of chips that wraps. Small enough to keep here rather than grow
/// a layout component for the one place that needs one.
private struct DSChipWrap<Item: Hashable, Content: View>: View {
    let items: [Item]
    @ViewBuilder let content: (Item) -> Content

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 150, maximum: 400), spacing: 6, alignment: .leading)],
                  alignment: .leading, spacing: 6) {
            ForEach(items, id: \.self) { content($0) }
        }
    }
}
