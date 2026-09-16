import SwiftUI

/// Signing in, in as few steps as the server allows.
///
/// The default way in is an address and a code from the mail: no password
/// to remember, no password to lose, and one path that both signs up and
/// signs in (the server deliberately never says which of the two just
/// happened). A password screen is one link away for accounts that have
/// one, and the second factor and the welcome step appear only when the
/// server says they are owed.
struct SignInView: View {
    @EnvironmentObject private var app: AppState
    var compact = false

    private enum Step: Equatable {
        case email
        case code(challengeId: String, resendAfter: Int)
        case password
        case mfa(challengeId: String, methods: [String])
        case welcome
    }

    @State private var step: Step = .email
    @State private var email = ""
    @State private var password = ""
    @State private var code = ""
    @State private var recoveryCode = ""
    @State private var usingRecoveryCode = false
    @State private var displayName = ""
    @State private var isBusy = false
    @State private var errorMessage: String?
    @State private var notice: String?
    /// Seconds until "Send again" becomes available.
    @State private var resendIn = 0
    @State private var showServer = false
    /// Set when the server has no password endpoint (native mode before
    /// IDX-A4): the link stops being offered rather than failing again.
    @State private var passwordUnavailable = false
    /// MAC-0: the account exists but its address is unconfirmed
    /// (`403 email_not_verified`). Nothing on this screen can finish the
    /// sign-in — only the code in the mail can — so the one thing offered
    /// is another copy of that mail.
    @State private var needsVerification = false
    @State private var resendBusy = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if !compact {
                DSWordmark(size: 18)
            }
            heading
            content
            if let message = errorMessage {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: message)
            } else if let notice {
                DSNotice(tone: .info, symbol: "envelope.fill", text: notice)
            }
            // Outside the branch above on purpose: a successful resend
            // replaces the error with a confirmation, and the button has
            // to survive that swap in case the second mail is slow too.
            if needsVerification { resendRow }
            if showsSignupPrompt { signupPrompt }
            footer
        }
        .onAppear {
            if email.isEmpty { email = app.email }
            // Why the app is showing this screen, if it did not start here.
            if errorMessage == nil { errorMessage = app.signedOutNotice }
        }
        .onChange(of: app.signedOutNotice) { _, new in
            if let new { errorMessage = new }
        }
        .task(id: resendTick) {
            guard resendIn > 0 else { return }
            try? await Task.sleep(for: .seconds(1))
            if resendIn > 0 { resendIn -= 1 }
        }
    }

    /// Changes every second while the resend countdown runs, so the task
    /// above re-fires; a plain `.task` would run once and stop.
    private var resendTick: String { "\(resendIn)-\(stepId)" }

    private var stepId: String {
        switch step {
        case .email: return "email"
        case .code: return "code"
        case .password: return "password"
        case .mfa: return "mfa"
        case .welcome: return "welcome"
        }
    }

    // MARK: - Heading

    @ViewBuilder
    private var heading: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.dsDisplay(compact ? 17 : 24, .medium))
                .foregroundStyle(DS.text1)
            Text(subtitle)
                .font(.ds(12.5))
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var title: String {
        switch step {
        case .email: return compact ? "Sign in" : "Welcome"
        // Deliberately not "Create account": the server answers the same way
        // for a known and an unknown address, so the screen cannot promise
        // one of the two before the code comes back.
        case .code: return "Check your mail"
        case .password: return "Your password"
        case .mfa: return "One more step"
        case .welcome: return "Nice to meet you"
        }
    }

    private var subtitle: String {
        switch step {
        case .email:
            return "Sign in or create an account — we mail you a six-digit code, "
                + "no password to pick. This Mac then becomes a capture device."
        case .code:
            return "We sent a six-digit code to \(email). It is good for ten minutes."
        case .password:
            return "Sign in with the password for \(email)."
        case .mfa(_, let methods):
            return methods.contains("totp")
                ? "Enter the code from your authenticator app."
                : "Enter one of your recovery codes."
        case .welcome:
            return "What should your colleagues call you? You can change this later."
        }
    }

    // MARK: - Steps

    @ViewBuilder
    private var content: some View {
        switch step {
        case .email:
            VStack(alignment: .leading, spacing: 10) {
                field("Email") {
                    DSTextField(placeholder: "you@company.com", text: $email)
                        .textContentType(.username)
                }
                primaryButton("Continue", disabled: !email.contains("@")) { await sendCode() }
                if !passwordUnavailable {
                    linkButton("Use a password instead") {
                        errorMessage = nil
                        step = .password
                    }
                }
            }
            .onSubmit { Task { await sendCode() } }

        case .code(let challengeId, _):
            VStack(alignment: .leading, spacing: 10) {
                DSCodeField(code: $code) { entered in
                    Task { await verify(code: entered, challengeId: challengeId) }
                }
                primaryButton("Sign in", disabled: code.count < 6) {
                    await verify(code: code, challengeId: challengeId)
                }
                HStack(spacing: 12) {
                    if resendIn > 0 {
                        Text("Send again in \(resendIn)s")
                            .font(.ds(12))
                            .foregroundStyle(DS.muted)
                    } else {
                        linkButton("Send another code") { Task { await sendCode() } }
                    }
                    linkButton("Use a different address") {
                        code = ""
                        errorMessage = nil
                        notice = nil
                        step = .email
                    }
                }
            }

        case .password:
            VStack(alignment: .leading, spacing: 10) {
                field("Email") {
                    DSTextField(placeholder: "you@company.com", text: $email)
                        .textContentType(.username)
                }
                field("Password") {
                    DSTextField(placeholder: "••••••••", text: $password, secure: true)
                        .textContentType(.password)
                }
                primaryButton("Sign in", disabled: email.isEmpty || password.isEmpty) {
                    await signInWithPassword()
                }
                HStack(spacing: 12) {
                    linkButton("Email me a code instead") {
                        password = ""
                        errorMessage = nil
                        step = .email
                    }
                    linkButton("Forgot?") { app.openPasswordReset() }
                }
            }
            .onSubmit { Task { await signInWithPassword() } }

        case .mfa(let challengeId, let methods):
            VStack(alignment: .leading, spacing: 10) {
                if usingRecoveryCode {
                    field("Recovery code") {
                        DSTextField(placeholder: "XXXX-XXXX", text: $recoveryCode, mono: true)
                    }
                } else {
                    DSCodeField(code: $code) { entered in
                        Task { await verifyMFA(challengeId: challengeId, code: entered) }
                    }
                }
                primaryButton("Continue", disabled: secondFactor.count < 4) {
                    await verifyMFA(challengeId: challengeId, code: secondFactor)
                }
                if methods.contains("recovery_code") {
                    linkButton(usingRecoveryCode
                               ? "Use my authenticator"
                               : "Use a recovery code") {
                        errorMessage = nil
                        code = ""
                        recoveryCode = ""
                        usingRecoveryCode.toggle()
                    }
                }
            }

        case .welcome:
            VStack(alignment: .leading, spacing: 10) {
                field("Your name") {
                    DSTextField(placeholder: "Olena Kovalenko", text: $displayName)
                        .textContentType(.name)
                }
                primaryButton("Continue", disabled: false) {
                    await app.setDisplayName(displayName)
                    finish()
                }
                linkButton("Skip") { finish() }
            }
            .onSubmit {
                Task {
                    await app.setDisplayName(displayName)
                    finish()
                }
            }
        }
    }

    private var secondFactor: String {
        usingRecoveryCode ? recoveryCode.trimmingCharacters(in: .whitespaces) : code
    }

    // MARK: - Signup (MAC-0)

    /// Only where a person could be starting out. Offering "create an
    /// account" beside a code field, a second factor or the welcome step
    /// would be offering it to somebody who plainly already has one.
    private var showsSignupPrompt: Bool {
        switch step {
        case .email, .password: return true
        case .code, .mfa, .welcome: return false
        }
    }

    private var signupPrompt: some View {
        HStack(spacing: 5) {
            Text("Don't have an account?")
                .font(.ds(12))
                .foregroundStyle(DS.muted)
            linkButton("Create one") { app.openSignup() }
        }
    }

    /// The way out of an unconfirmed account. `email` is whatever the
    /// person typed, which is the address the server just refused — the
    /// resend cannot drift onto a different one.
    private var resendRow: some View {
        HStack(spacing: 10) {
            Button("Resend") {
                Task { await resendVerification() }
            }
            .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 26))
            .disabled(resendBusy || isBusy)
            if resendBusy {
                ProgressView().controlSize(.small)
            }
            Text("to \(email)")
                .font(.ds(11.5))
                .foregroundStyle(DS.text3)
                .lineLimit(1)
                .truncationMode(.middle)
        }
    }

    // MARK: - Footer (which server this is)

    private var footer: some View {
        VStack(alignment: .leading, spacing: 8) {
            if showServer {
                VStack(alignment: .leading, spacing: 6) {
                    serverField("Auth", text: $app.settings.authBaseURL)
                    serverField("ASR", text: $app.settings.asrBaseURL)
                    serverField("Notes", text: $app.settings.noteBaseURL)
                    serverField("Web", text: $app.settings.webAppURL)
                }
                .padding(.top, 2)
            }
            HStack {
                Button {
                    withAnimation(.easeOut(duration: 0.15)) { showServer.toggle() }
                } label: {
                    Text(showServer ? "Hide server" : authHost)
                        .font(.dsMono(10.5))
                }
                .buttonStyle(.plain)
                .foregroundStyle(DS.muted)
                .help("The backend this Mac talks to")
                Spacer()
                Button("Quit") { NSApp.terminate(nil) }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 11.5, height: 22))
                    .foregroundStyle(DS.muted)
            }
        }
    }

    private func serverField(_ label: String, text: Binding<String>) -> some View {
        HStack(spacing: 8) {
            Text(label)
                .font(.ds(11.5))
                .foregroundStyle(DS.text3)
                .frame(width: 40, alignment: .leading)
            DSTextField(placeholder: label, text: text, mono: true)
        }
    }

    private var authHost: String {
        URL(string: app.settings.authBaseURL)?.host() ?? app.settings.authBaseURL
    }

    // MARK: - Pieces

    private func field(_ label: String, @ViewBuilder control: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            DSLabel(label)
            control()
        }
    }

    private func primaryButton(_ title: String, disabled: Bool,
                               action: @escaping () async -> Void) -> some View {
        Button {
            Task { await action() }
        } label: {
            if isBusy {
                ProgressView().controlSize(.small)
            } else {
                Text(title)
            }
        }
        .buttonStyle(DSButtonStyle(kind: .primary, height: 34, fill: true))
        .keyboardShortcut(.defaultAction)
        .disabled(isBusy || disabled)
    }

    private func linkButton(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(.ds(12))
        }
        .buttonStyle(.plain)
        .foregroundStyle(DS.accentText)
        .disabled(isBusy)
    }

    // MARK: - Actions

    private func sendCode() async {
        let address = email.trimmingCharacters(in: .whitespaces)
        guard !isBusy, address.contains("@") else { return }
        isBusy = true
        errorMessage = nil
        needsVerification = false
        defer { isBusy = false }
        do {
            let challenge = try await app.startEmailCode(email: address)
            email = address
            code = ""
            notice = "Enter the code we mailed you."
            resendIn = challenge.resendAfter
            step = .code(challengeId: challenge.challengeId, resendAfter: challenge.resendAfter)
        } catch let error as APIError where error.code == "use_password" {
            // The address is known and has a password; the server will not
            // mail it a code. Show the password form already filled in
            // rather than an error about a form the person cannot see.
            email = address
            notice = nil
            passwordUnavailable = false
            step = .password
            errorMessage = AuthCopy.message(for: error)
        } catch {
            notice = nil
            show(error)
        }
    }

    private func verify(code entered: String, challengeId: String) async {
        guard !isBusy, entered.count >= 6 else { return }
        isBusy = true
        errorMessage = nil
        notice = nil
        needsVerification = false
        defer { isBusy = false }
        do {
            let step = try await app.signIn(withCode: entered, challengeId: challengeId, email: email)
            advance(to: step)
        } catch {
            code = ""
            show(error)
        }
    }

    private func signInWithPassword() async {
        guard !isBusy, !email.isEmpty, !password.isEmpty else { return }
        isBusy = true
        errorMessage = nil
        needsVerification = false
        defer { isBusy = false }
        do {
            let next = try await app.signIn(email: email, password: password, otp: nil)
            password = ""
            advance(to: next)
        } catch let error as APIError where error.isNotFound {
            // This deployment has no password endpoint (native mode before
            // IDX-A4). Say so once and take the person back to the code.
            passwordUnavailable = true
            password = ""
            step = .email
            errorMessage = "This server signs in with a code sent by email."
        } catch let error as APIError where error.isMFARequired {
            // The Keycloak-era login asks for the one-time code in a 401
            // rather than in the body.
            errorMessage = AuthCopy.message(for: error)
            step = .mfa(challengeId: "", methods: ["totp"])
        } catch {
            show(error)
        }
    }

    private func verifyMFA(challengeId: String, code entered: String) async {
        guard !isBusy, !entered.isEmpty else { return }
        isBusy = true
        errorMessage = nil
        needsVerification = false
        defer { isBusy = false }
        do {
            if challengeId.isEmpty {
                // Keycloak's login takes the second factor as `otp` on the
                // same request rather than on a challenge of its own.
                let next = try await app.signIn(email: email, password: password, otp: entered)
                advance(to: next)
            } else {
                let next = try await app.completeMFA(
                    challengeId: challengeId,
                    method: usingRecoveryCode ? "recovery_code" : "totp",
                    code: entered,
                    email: email)
                advance(to: next)
            }
        } catch {
            code = ""
            recoveryCode = ""
            show(error)
        }
    }

    /// One place that decides what a failure means for this screen, so
    /// that every way in offers the same way out of an unconfirmed
    /// account rather than four screens disagreeing about it.
    private func show(_ error: Error) {
        errorMessage = AuthCopy.message(for: error)
        needsVerification = (error as? APIError)?.code == "email_not_verified"
    }

    private func resendVerification() async {
        let address = email.trimmingCharacters(in: .whitespaces)
        guard !resendBusy, !address.isEmpty else { return }
        resendBusy = true
        defer { resendBusy = false }
        do {
            try await app.resendSignupVerification(email: address)
            // Keep `needsVerification`: the account is still unconfirmed
            // until the person acts on the mail, and a second copy may yet
            // be wanted. Only the sentence changes.
            errorMessage = nil
            notice = "We sent another code to \(address). Confirm it, then sign in."
        } catch {
            notice = nil
            errorMessage = AuthCopy.message(for: error)
        }
    }

    private func advance(to next: AppState.SignInStep) {
        switch next {
        case .signedIn:
            finish()
        case .mfaRequired(let challengeId, let methods):
            code = ""
            usingRecoveryCode = !methods.contains("totp")
            step = .mfa(challengeId: challengeId, methods: methods)
        case .welcome:
            displayName = app.identity?.displayName ?? ""
            step = .welcome
        }
    }

    private func finish() {
        password = ""
        code = ""
        recoveryCode = ""
        needsVerification = false
        step = .email
    }
}
