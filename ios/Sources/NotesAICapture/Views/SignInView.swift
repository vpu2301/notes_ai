import SwiftUI

struct SignInView: View {
    @EnvironmentObject private var app: AppState

    @State private var email = ""
    @State private var password = ""
    @State private var otp = ""
    @State private var needsOTP = false
    @State private var isBusy = false
    @State private var errorMessage: String?
    /// The server field shown on the card itself when the addresses cannot
    /// work (localhost on a phone) or the last attempt could not connect.
    @State private var showServer = false
    @State private var host = ""
    /// Keep the password in the Keychain behind Face ID for next time.
    @State private var rememberMe = CredentialStore.biometryName != nil
    @State private var hasSaved = CredentialStore.hasSaved
    @State private var biometricTried = false
    @FocusState private var focus: Field?

    private let biometry = CredentialStore.biometryName

    private enum Field { case email, password, otp, server }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            DSWordmark(size: 19)
            VStack(alignment: .leading, spacing: 4) {
                Text("Welcome back")
                    .font(.dsDisplay(26, .medium))
                    .foregroundStyle(DS.text1)
                Text("Sign in to turn this phone into a meeting-capture device.")
                    .font(.ds(14))
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 6) {
                    DSLabel("Email")
                    DSTextField(placeholder: "you@company.com", text: $email)
                        .textContentType(.username)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .focused($focus, equals: .email)
                        .submitLabel(.next)
                        .onSubmit { focus = .password }
                }
                VStack(alignment: .leading, spacing: 6) {
                    DSLabel("Password")
                    HStack(spacing: 8) {
                        DSTextField(placeholder: "••••••••", text: $password, secure: true)
                            .textContentType(.password)
                            .focused($focus, equals: .password)
                            .submitLabel(needsOTP ? .next : .go)
                            .onSubmit { if needsOTP { focus = .otp } else { submit() } }
                        if hasSaved, let biometry {
                            Button {
                                Task { await signInWithBiometrics() }
                            } label: {
                                Image(systemName: CredentialStore.biometrySymbol)
                                    .font(.system(size: 20, weight: .medium))
                            }
                            .buttonStyle(DSButtonStyle(kind: .secondary, height: DS.control))
                            .frame(width: DS.control)
                            .disabled(isBusy)
                            .accessibilityLabel("Sign in with \(biometry)")
                        }
                    }
                }
                if let biometry, !hasSaved {
                    Toggle("Save password for \(biometry)", isOn: $rememberMe)
                        .toggleStyle(DSToggleStyle())
                }
                if needsOTP {
                    VStack(alignment: .leading, spacing: 6) {
                        DSLabel("One-time code")
                        DSTextField(placeholder: "123 456", text: $otp, mono: true)
                            .textContentType(.oneTimeCode)
                            .keyboardType(.numberPad)
                            .focused($focus, equals: .otp)
                            .submitLabel(.go)
                            .onSubmit(submit)
                    }
                }
            }

            if let errorMessage {
                DSNotice(tone: needsOTP ? .info : .danger,
                         symbol: needsOTP ? "key.fill" : "exclamationmark.triangle.fill",
                         text: errorMessage)
            }

            if showServer {
                VStack(alignment: .leading, spacing: 6) {
                    DSLabel("Server (your Mac's Wi‑Fi address)")
                    HStack(spacing: 8) {
                        DSTextField(placeholder: "192.168.1.20 or my-mac.local", text: $host, mono: true)
                            .keyboardType(.URL)
                            .focused($focus, equals: .server)
                            .submitLabel(.done)
                            .onSubmit(applyHost)
                        Button("Use") { applyHost() }
                            .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: DS.control))
                            .disabled(BackendSettings.forHost(host) == nil || host == app.settings.commonHost)
                    }
                    if let problem = BackendSettings.hostProblem(host) {
                        Text(problem)
                            .font(.dsMeta)
                            .foregroundStyle(DS.dangerText)
                            .fixedSize(horizontal: false, vertical: true)
                    } else {
                        Text("On the Mac: System Settings › Wi‑Fi › Details › IP address.")
                            .font(.dsMeta)
                            .foregroundStyle(DS.muted)
                    }
                }
            }

            if hasSaved, let biometry, password.isEmpty {
                Button {
                    Task { await signInWithBiometrics() }
                } label: {
                    if isBusy {
                        ProgressView().tint(DS.inkText)
                    } else {
                        Label("Sign in with \(biometry)", systemImage: CredentialStore.biometrySymbol)
                    }
                }
                .buttonStyle(DSButtonStyle(kind: .primary, height: DS.control, fill: true))
                .disabled(isBusy)
            } else {
                Button(action: submit) {
                    if isBusy {
                        ProgressView().tint(DS.inkText)
                    } else {
                        Text("Sign in")
                    }
                }
                .buttonStyle(DSButtonStyle(kind: .primary, height: DS.control, fill: true))
                .disabled(isBusy || email.isEmpty || password.isEmpty)
            }

            HStack {
                Text(authHost)
                    .font(.dsMono(11.5))
                    .foregroundStyle(DS.muted)
                Spacer()
                Button("Server…") { app.settingsPresented = true }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 28))
                    .foregroundStyle(DS.muted)
            }
        }
        .onAppear {
            if email.isEmpty { email = app.email }
            host = app.settings.commonHost ?? ""
            if isPhysicalDevice, app.settings.pointsAtLocalhost { showServer = true }
            hasSaved = CredentialStore.hasSaved
            // A saved password: offer Face ID straight away, once.
            if hasSaved, biometry != nil, !biometricTried, !app.settings.pointsAtLocalhost || !isPhysicalDevice {
                biometricTried = true
                Task { await signInWithBiometrics() }
            }
        }
        .onChange(of: app.settings) { _, settings in
            host = settings.commonHost ?? host
        }
    }

    private func applyHost() {
        guard let settings = BackendSettings.forHost(host) else { return }
        app.settings = settings
        errorMessage = nil
        focus = password.isEmpty ? .password : nil
    }

    private var authHost: String {
        URL(string: app.settings.authBaseURL)?.host() ?? app.settings.authBaseURL
    }

    /// "Could not connect to the server." says nothing about why. On a
    /// phone the usual reason is that the addresses still say localhost.
    static func describe(_ error: URLError, settings: BackendSettings) -> String {
        let host = URL(string: settings.authBaseURL)?.host() ?? settings.authBaseURL
        switch error.code {
        case .cannotConnectToHost, .cannotFindHost, .timedOut, .networkConnectionLost, .dnsLookupFailed:
            if isPhysicalDevice, settings.pointsAtLocalhost {
                return "Can't reach \(host) — on a phone, localhost is the phone itself. Enter your Mac's Wi‑Fi address below (the stack must be published with PUBLISH_HOST=0.0.0.0)."
            }
            return "Can't reach \(host). Is the Notes AI server running, published on the network (PUBLISH_HOST=0.0.0.0), and is the phone on the same Wi‑Fi?"
        case .notConnectedToInternet:
            return "This phone is offline."
        case .appTransportSecurityRequiresSecureConnection:
            return "\(host) is plain http, which this build does not allow."
        default:
            return error.localizedDescription
        }
    }

    /// Face ID → the saved password → the normal sign-in. Silent when the
    /// user cancels the prompt; a rejected password is forgotten so the
    /// form is back to typing.
    private func signInWithBiometrics() async {
        guard !isBusy, let biometry else { return }
        errorMessage = nil
        do {
            guard let saved = try await CredentialStore.load(reason: "Sign in to Notes AI") else { return }
            email = saved.email
            password = saved.password
            await signIn(remember: false, fromKeychain: true)
        } catch {
            errorMessage = "\(biometry) is not available: \(error.localizedDescription)"
        }
    }

    private func submit() {
        guard !isBusy, !email.isEmpty, !password.isEmpty else { return }
        focus = nil
        Task { await signIn(remember: rememberMe && !hasSaved, fromKeychain: false) }
    }

    private func signIn(remember: Bool, fromKeychain: Bool) async {
        isBusy = true
        errorMessage = nil
        defer { isBusy = false }
        do {
            try await app.signIn(email: email, password: password,
                                 otp: needsOTP ? otp : nil)
            if remember, biometry != nil {
                try? CredentialStore.save(email: email, password: password)
            }
            password = ""
            otp = ""
        } catch let error as APIError where error.isMFARequired {
            needsOTP = true
            errorMessage = "Enter the one-time code from your authenticator."
            focus = .otp
        } catch let error as APIError {
            if fromKeychain, case .http(let status, _) = error, status == 401 {
                // The password changed since it was saved.
                CredentialStore.delete()
                hasSaved = false
                password = ""
                errorMessage = "The saved password no longer works — sign in with the new one."
            } else {
                errorMessage = error.localizedDescription
            }
        } catch let error as URLError {
            errorMessage = Self.describe(error, settings: app.settings)
            showServer = true
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
