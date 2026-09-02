import SwiftUI

struct SignInView: View {
    @EnvironmentObject private var app: AppState
    var compact = false

    @State private var email = ""
    @State private var password = ""
    @State private var otp = ""
    @State private var needsOTP = false
    @State private var isBusy = false
    @State private var errorMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if !compact {
                DSWordmark(size: 18)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text(compact ? "Sign in" : "Welcome back")
                    .font(.dsDisplay(compact ? 17 : 24, .medium))
                    .foregroundStyle(DS.text1)
                Text("Sign in to turn this Mac into a meeting-capture device.")
                    .font(.ds(12.5))
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            VStack(alignment: .leading, spacing: 10) {
                VStack(alignment: .leading, spacing: 6) {
                    DSLabel("Email")
                    DSTextField(placeholder: "you@company.com", text: $email)
                        .textContentType(.username)
                }
                VStack(alignment: .leading, spacing: 6) {
                    DSLabel("Password")
                    DSTextField(placeholder: "••••••••", text: $password, secure: true)
                        .textContentType(.password)
                }
                if needsOTP {
                    VStack(alignment: .leading, spacing: 6) {
                        DSLabel("One-time code")
                        DSTextField(placeholder: "123 456", text: $otp, mono: true)
                            .textContentType(.oneTimeCode)
                    }
                }
            }
            .onSubmit(submit)

            if let errorMessage {
                DSNotice(tone: needsOTP ? .info : .danger,
                         symbol: needsOTP ? "key.fill" : "exclamationmark.triangle.fill",
                         text: errorMessage)
            }

            Button(action: submit) {
                if isBusy {
                    ProgressView().controlSize(.small)
                } else {
                    Text("Sign in")
                }
            }
            .buttonStyle(DSButtonStyle(kind: .primary, height: 34, fill: true))
            .keyboardShortcut(.defaultAction)
            .disabled(isBusy || email.isEmpty || password.isEmpty)

            HStack {
                Text(authHost)
                    .font(.dsMono(10.5))
                    .foregroundStyle(DS.muted)
                Spacer()
                Button("Quit") { NSApp.terminate(nil) }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 11.5, height: 22))
                    .foregroundStyle(DS.muted)
            }
        }
        .onAppear {
            if email.isEmpty { email = app.email }
        }
    }

    private var authHost: String {
        URL(string: app.settings.authBaseURL)?.host() ?? app.settings.authBaseURL
    }

    private func submit() {
        guard !isBusy, !email.isEmpty, !password.isEmpty else { return }
        isBusy = true
        errorMessage = nil
        Task {
            defer { isBusy = false }
            do {
                try await app.signIn(email: email, password: password,
                                     otp: needsOTP ? otp : nil)
                password = ""
                otp = ""
            } catch let error as APIError where error.isMFARequired {
                needsOTP = true
                errorMessage = "Enter the one-time code from your authenticator."
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}
