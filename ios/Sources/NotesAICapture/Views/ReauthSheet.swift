import SwiftUI

/// "Confirm it is really you" — the step-up sheet.
///
/// An access token proves someone signed in on this phone at some point in
/// the last thirty days. The endpoints behind this sheet — turning off a
/// second factor, moving the sign-in address, deleting the account, ending
/// every other session — can take the account away from its owner, and an
/// unlocked phone is an access token. So the server asks again, and this
/// is where the answer is typed.
///
/// The plumbing lands in IDX-I1; the endpoints that use it are IDX-I2's.
struct ReauthSheet: View {
    @EnvironmentObject private var app: AppState
    let prompt: ReauthPrompt

    @State private var code = ""
    @State private var method: String = ""
    @State private var isBusy = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text(explanation)
                        .font(.ds(14))
                        .foregroundStyle(DS.muted)
                        .fixedSize(horizontal: false, vertical: true)

                    if method == "recovery_code" {
                        VStack(alignment: .leading, spacing: 6) {
                            DSLabel("Recovery code")
                            DSTextField(placeholder: "XXXX-XXXX", text: $code, mono: true)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                        }
                    } else {
                        DSCodeField(code: $code) { _ in Task { await confirm() } }
                    }

                    if let errorMessage {
                        DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill",
                                 text: errorMessage)
                    }

                    Button {
                        Task { await confirm() }
                    } label: {
                        if isBusy {
                            ProgressView().tint(DS.inkText)
                        } else {
                            Text("Confirm")
                        }
                    }
                    .buttonStyle(DSButtonStyle(kind: .primary, height: DS.control, fill: true))
                    .disabled(isBusy || code.count < 4)

                    if prompt.offersRecoveryCode {
                        Button(method == "recovery_code" ? "Use my authenticator" : "Use a recovery code") {
                            code = ""
                            errorMessage = nil
                            method = method == "recovery_code" ? "totp" : "recovery_code"
                        }
                        .buttonStyle(.plain)
                        .font(.ds(14))
                        .foregroundStyle(DS.accentText)
                    }
                }
                .padding(.horizontal, DS.gutter)
                .padding(.vertical, 16)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(DS.bg)
            .navigationTitle("Confirm it is you")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { prompt.answer(false) }
                }
            }
        }
        .presentationDetents([.medium])
        .tint(DS.accentText)
        .interactiveDismissDisabled()
        .onAppear { method = prompt.methods.first ?? "email_code" }
    }

    private var explanation: String {
        switch method {
        case "totp":
            return "Enter the current code from your authenticator app."
        case "recovery_code":
            return "Enter one of the recovery codes you saved."
        default:
            return "We sent a code to \(app.email). Enter it to continue."
        }
    }

    private func confirm() async {
        guard !isBusy, !code.isEmpty else { return }
        isBusy = true
        errorMessage = nil
        defer { isBusy = false }
        do {
            try await app.api.reauth(method: method,
                                     code: code.trimmingCharacters(in: .whitespaces),
                                     challengeId: prompt.challengeId)
            prompt.answer(true)
        } catch {
            code = ""
            errorMessage = AuthCopy.message(for: error)
        }
    }
}

// MARK: - Reconnecting

/// Shown when the app came up with a session it could not check.
///
/// The alternative — signing the person out because the server did not
/// answer at boot — makes a flaky connection look like a security event,
/// and is the one thing IDX-I1 says never to do. On a phone it would also
/// be the common case, not the rare one.
struct ReconnectingBanner: View {
    @EnvironmentObject private var app: AppState

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "wifi.exclamationmark")
                .font(.ds(13, .semibold))
                .foregroundStyle(DS.warn)
            Text("Reconnecting… you are signed in, but the server has not answered yet.")
                .font(.ds(13))
                .foregroundStyle(DS.text2)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            Button("Try now") { Task { await app.reconnect() } }
                .buttonStyle(DSButtonStyle(kind: .secondary, size: 13, height: 28))
        }
        .padding(.horizontal, DS.gutter)
        .padding(.vertical, 8)
        .background(DS.warnSoft)
    }
}
