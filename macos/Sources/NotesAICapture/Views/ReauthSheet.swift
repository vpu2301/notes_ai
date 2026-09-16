import SwiftUI

/// "Confirm it is really you" — the step-up sheet.
///
/// An access token proves someone signed in on this Mac at some point in
/// the last thirty days. The endpoints behind this sheet — turning off a
/// second factor, moving the sign-in address, deleting the account, ending
/// every other session — can take the account away from its owner, and an
/// unlocked laptop is an access token. So the server asks again, and this
/// is where the answer is typed.
///
/// The plumbing lands in IDX-M1; the endpoints that use it are IDX-M2's.
struct ReauthSheet: View {
    @EnvironmentObject private var app: AppState
    let prompt: ReauthPrompt

    @State private var code = ""
    @State private var method: String = ""
    @State private var isBusy = false
    @State private var errorMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 3) {
                Text("Confirm it is you")
                    .font(.dsDisplay(18, .medium))
                    .foregroundStyle(DS.text1)
                Text(explanation)
                    .font(.ds(12.5))
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            if method == "recovery_code" {
                VStack(alignment: .leading, spacing: 6) {
                    DSLabel("Recovery code")
                    DSTextField(placeholder: "XXXX-XXXX", text: $code, mono: true)
                }
            } else {
                DSCodeField(code: $code) { _ in Task { await confirm() } }
            }

            if let errorMessage {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: errorMessage)
            }

            if prompt.offersRecoveryCode {
                Button(method == "recovery_code" ? "Use my authenticator" : "Use a recovery code") {
                    code = ""
                    errorMessage = nil
                    method = method == "recovery_code" ? "totp" : "recovery_code"
                }
                .buttonStyle(.plain)
                .font(.ds(12))
                .foregroundStyle(DS.accentText)
            }

            HStack {
                Button("Cancel") { prompt.answer(false) }
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 30))
                    .keyboardShortcut(.cancelAction)
                Spacer()
                Button {
                    Task { await confirm() }
                } label: {
                    if isBusy {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("Confirm")
                    }
                }
                .buttonStyle(DSButtonStyle(kind: .primary, height: 30))
                .keyboardShortcut(.defaultAction)
                .disabled(isBusy || code.count < 4)
            }
        }
        .padding(22)
        .frame(width: 380)
        .background(DS.bg)
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
/// and is the one thing IDX-M1 says never to do.
struct ReconnectingBanner: View {
    @EnvironmentObject private var app: AppState

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "wifi.exclamationmark")
                .font(.ds(12, .semibold))
                .foregroundStyle(DS.warn)
            Text("Reconnecting… this Mac is signed in, but the server has not answered yet.")
                .font(.ds(12))
                .foregroundStyle(DS.text2)
            Spacer(minLength: 0)
            Button("Try now") { Task { await app.reconnect() } }
                .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 24))
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 8)
        .background(DS.warnSoft)
    }
}
