import SwiftUI

struct SignInView: View {
    @EnvironmentObject private var app: AppState

    @State private var email = ""
    @State private var password = ""
    @State private var otp = ""
    @State private var needsOTP = false
    @State private var isBusy = false
    @State private var errorMessage: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Sign in to turn this Mac into a meeting-capture device.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            VStack(spacing: 8) {
                TextField("Email", text: $email)
                    .textContentType(.username)
                SecureField("Password", text: $password)
                    .textContentType(.password)
                if needsOTP {
                    TextField("One-time code", text: $otp)
                        .textContentType(.oneTimeCode)
                }
            }
            .textFieldStyle(.roundedBorder)
            .onSubmit(submit)

            if let errorMessage {
                Label(errorMessage, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Button(action: submit) {
                HStack {
                    Spacer()
                    if isBusy {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Text("Sign In")
                            .fontWeight(.semibold)
                    }
                    Spacer()
                }
            }
            .keyboardShortcut(.defaultAction)
            .controlSize(.large)
            .disabled(isBusy || email.isEmpty || password.isEmpty)

            HStack {
                Text(authHost)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                Spacer()
                Button("Quit") { NSApp.terminate(nil) }
                    .buttonStyle(.plain)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(16)
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
