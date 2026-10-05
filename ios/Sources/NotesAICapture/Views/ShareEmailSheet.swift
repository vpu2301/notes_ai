import SwiftUI

/// "Send this note" — the server sends the mail; the sheet reports per address.
struct ShareEmailSheet: View {
    let noteTitle: String
    /// Sends; one outcome per recipient, or nil when the call itself failed.
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

    /// Loose shape check, only to keep obvious typos out of the chip list.
    static func looksLikeEmail(_ value: String) -> Bool {
        guard !value.contains(where: \.isWhitespace) else { return false }
        let parts = value.split(separator: "@", omittingEmptySubsequences: false)
        guard parts.count == 2, let local = parts.first, let domain = parts.last else { return false }
        return !local.isEmpty && domain.contains(".")
            && !domain.hasPrefix(".") && !domain.hasSuffix(".")
    }

    private var trimmedDraft: String {
        draft.trimmingCharacters(in: .whitespaces)
            .trimmingCharacters(in: CharacterSet(charactersIn: ",;"))
    }

    /// Everything typed so far, including the uncommitted address in the box.
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
        NavigationStack {
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
                    Text("People in your workspace get access to the note. Anyone else gets a link they can open without signing in.")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .background(DS.bg)
            .navigationTitle("Send this note")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Close", action: onClose)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    if sending {
                        ProgressView().controlSize(.small)
                    } else {
                        Button("Send") { Task { await sendNow() } }
                            .disabled(allRecipients.isEmpty)
                    }
                }
            }
        }
        .onAppear { addressFocused = true }
    }

    // MARK: - Addresses

    private var addressBox: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSLabel("Send to")
            if !recipients.isEmpty {
                DSChipWrap(items: recipients) { address in
                    RecipientChip(address: address, disabled: sending) {
                        recipients.removeAll { $0 == address }
                    }
                }
            }
            DSTextField(placeholder: "name@company.com", text: $draft)
                .keyboardType(.emailAddress)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.next)
                .focused($addressFocused)
                .onSubmit {
                    // Return adds the address and keeps the box ready.
                    _ = commitDraft()
                    addressFocused = true
                }
                .onChange(of: draft) { _, value in
                    draftError = nil
                    if value.hasSuffix(",") || value.hasSuffix(";") || value.hasSuffix(" ") {
                        _ = commitDraft()
                    }
                }
                .disabled(sending)
        }
        .dsCard()
    }

    private var messageBox: some View {
        VStack(alignment: .leading, spacing: 10) {
            DSLabel("Message")
            TextEditor(text: $message)
                .font(.ds(16))
                .foregroundStyle(DS.text1)
                .scrollContentBackground(.hidden)
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
                .frame(height: 108)
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
                            .font(.ds(16))
                            .foregroundStyle(DS.muted)
                            .padding(.horizontal, 13)
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
        let to = allRecipients
        guard !to.isEmpty else {
            _ = commitDraft()
            draftError = draftError ?? "Add at least one e-mail address."
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
        // Only the failed addresses stay in the box for a retry.
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
        HStack(spacing: 6) {
            Text(address)
                .font(.ds(14))
                .foregroundStyle(DS.text2)
                .lineLimit(1)
            Button(action: remove) {
                Image(systemName: "xmark")
                    .font(.ds(11, .semibold))
                    .foregroundStyle(DS.muted)
            }
            .buttonStyle(.plain)
            .disabled(disabled)
            .accessibilityLabel("Remove \(address)")
        }
        .padding(.leading, 11)
        .padding(.trailing, 8)
        .padding(.vertical, 6)
        .background(Capsule().fill(DS.surface2))
        .overlay(Capsule().strokeBorder(DS.line2, lineWidth: DS.hairline))
    }
}

/// A row of chips that wraps.
private struct DSChipWrap<Item: Hashable, Content: View>: View {
    let items: [Item]
    @ViewBuilder let content: (Item) -> Content

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 170, maximum: 400), spacing: 8, alignment: .leading)],
                  alignment: .leading, spacing: 8) {
            ForEach(items, id: \.self) { content($0) }
        }
    }
}
