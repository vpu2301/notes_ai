import SwiftUI

/// Signing in, in as few steps as the server allows.
///
/// The default way in is an address and a code from the mail: no password
/// to remember, no password to lose, and one path that both signs up and
/// signs in (the server deliberately never says which of the two just
/// happened). A password screen is one link away for accounts that have
/// one, and the second factor and the welcome step appear only when the
/// server says they are owed.
///
/// During the dual-issuer period (ADR-0047) both ways in are real, so both
/// are here. A new account gets a code and a native session; an account
/// that predates the period keeps its Keycloak password — and keeps the
/// Face ID button that signs in with the one saved on this phone, because
/// taking that away in the release that adds email codes would be a
/// regression for every existing user and a benefit to none of them. The
/// server can also say so itself: `409 use_password` moves this screen to
/// the password form for an address that has one.
struct SignInView: View {
    @EnvironmentObject private var app: AppState

    private enum Step: Equatable {
        case email
        case code(challengeId: String)
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
    /// The server card, shown when the addresses cannot work (localhost on
    /// a phone) or the last attempt could not connect.
    @State private var showServer = false
    @State private var host = ""
    /// Set when the server has no password endpoint (native mode before
    /// IDX-A4): the link stops being offered rather than failing again.
    @State private var passwordUnavailable = false
    /// Keep the password in the Keychain behind Face ID for next time.
    /// Only ever written for a Keycloak session — a native one has no
    /// password, and `SessionKind.canSavePassword` is the check.
    @State private var rememberPassword = Biometrics.name != nil
    @State private var hasSavedPassword = CredentialStore.hasSaved
    /// The saved-password sign-in is offered once per appearance, not on
    /// every redraw of the password step.
    @State private var biometricTried = false
    /// Set when `/auth/login` answered `403 email_not_verified`: the
    /// address whose confirmation link can be sent again. Cleared as soon
    /// as anything else is tried, so the button never offers to resend
    /// for an address the person has since changed.
    @State private var unverified: String?
    @State private var resending = false
    @FocusState private var focus: Field?

    private enum Field { case email, password, recovery, name, server }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            DSWordmark(size: 19)
            heading
            content
            if let message = errorMessage {
                // An unconfirmed address is not a wrong password: the
                // account is fine and the only thing missing is a click in
                // an inbox, so this reads as information with a way
                // forward rather than as a refusal.
                DSNotice(tone: unverified == nil ? .danger : .info,
                         symbol: unverified == nil ? "exclamationmark.triangle.fill" : "envelope.badge",
                         text: message)
                if let address = unverified {
                    linkButton(resending ? "Sending…" : "Resend the confirmation email") {
                        guard !resending else { return }
                        resending = true
                        Task {
                            let said = await app.resendVerification(to: address)
                            resending = false
                            errorMessage = said
                        }
                    }
                }
            } else if let notice {
                // An envelope for "we mailed you a code"; a key for "this
                // account signs in with a password" — the same slot, two
                // different pieces of news.
                DSNotice(tone: .info,
                         symbol: step == .password ? "key.fill" : "envelope.fill",
                         text: notice)
            }
            if showServer { serverCard }
            footer
        }
        .onAppear {
            if email.isEmpty { email = app.email }
            host = app.settings.commonHost ?? ""
            if isPhysicalDevice, app.settings.pointsAtLocalhost { showServer = true }
            // Why the app is showing this screen, if it did not start here.
            if errorMessage == nil { errorMessage = app.signedOutNotice }
            hasSavedPassword = CredentialStore.hasSaved
        }
        .onChange(of: stepId) { _, id in
            // Whatever the step change was, the offer to resend a
            // confirmation belongs to the attempt that provoked it.
            unverified = nil
            // A saved password: offer the face as soon as the password
            // step is reached, once, and never over an address the phone
            // cannot reach anyway — a Face ID prompt in front of a
            // connection error explains nothing.
            guard id == "password", hasSavedPassword, !biometricTried,
                  Biometrics.name != nil, password.isEmpty,
                  !(isPhysicalDevice && app.settings.pointsAtLocalhost)
            else { return }
            biometricTried = true
            Task { await signInWithSavedPassword() }
        }
        .onChange(of: app.signedOutNotice) { _, new in
            if let new { errorMessage = new }
        }
        .onChange(of: app.settings) { _, settings in
            host = settings.commonHost ?? host
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

    private var heading: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.dsDisplay(26, .medium))
                .foregroundStyle(DS.text1)
            Text(subtitle)
                .font(.ds(14))
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var title: String {
        switch step {
        case .email: return "Welcome"
        case .code: return "Check your mail"
        case .password: return "Your password"
        case .mfa: return "One more step"
        case .welcome: return "Nice to meet you"
        }
    }

    private var subtitle: String {
        switch step {
        case .email:
            return "Sign in to turn this phone into a meeting-capture device."
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
            VStack(alignment: .leading, spacing: 12) {
                field("Email") {
                    DSTextField(placeholder: "you@company.com", text: $email)
                        .textContentType(.username)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .focused($focus, equals: .email)
                        .submitLabel(.go)
                        .onSubmit { Task { await sendCode() } }
                }
                primaryButton("Continue", disabled: !email.contains("@")) { await sendCode() }
                if !passwordUnavailable {
                    linkButton(hasSavedPassword ? "Use my saved password" : "Use a password instead") {
                        errorMessage = nil
                        notice = nil
                        step = .password
                    }
                }
                HStack(spacing: 4) {
                    Text("Don't have an account?")
                        .font(.ds(13))
                        .foregroundStyle(DS.muted)
                    // Out to the web app: signup is a form with terms, a
                    // workspace name and an address to confirm, and it
                    // lives where there is a keyboard (BE-0 / IOS-0).
                    linkButton("Create one") { app.openSignup() }
                }
            }

        case .code(let challengeId):
            VStack(alignment: .leading, spacing: 12) {
                DSCodeField(code: $code) { entered in
                    Task { await verify(code: entered, challengeId: challengeId) }
                }
                primaryButton("Sign in", disabled: code.count < 6) {
                    await verify(code: code, challengeId: challengeId)
                }
                HStack(spacing: 16) {
                    if resendIn > 0 {
                        Text("Send again in \(resendIn)s")
                            .font(.ds(13))
                            .foregroundStyle(DS.muted)
                    } else {
                        linkButton("Send another code") { Task { await sendCode() } }
                    }
                    linkButton("Different address") {
                        code = ""
                        errorMessage = nil
                        notice = nil
                        step = .email
                    }
                }
            }

        case .password:
            VStack(alignment: .leading, spacing: 12) {
                field("Email") {
                    DSTextField(placeholder: "you@company.com", text: $email)
                        .textContentType(.username)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .submitLabel(.next)
                        .onSubmit { focus = .password }
                }
                field("Password") {
                    HStack(spacing: 8) {
                        DSTextField(placeholder: "••••••••", text: $password, secure: true)
                            .textContentType(.password)
                            .focused($focus, equals: .password)
                            .submitLabel(.go)
                            .onSubmit { Task { await signInWithPassword() } }
                        if hasSavedPassword, let biometry = Biometrics.name {
                            Button { Task { await signInWithSavedPassword() } } label: {
                                Image(systemName: Biometrics.symbol)
                                    .font(.system(size: 20, weight: .medium))
                            }
                            .buttonStyle(DSButtonStyle(kind: .secondary, height: DS.control))
                            .frame(width: DS.control)
                            .disabled(isBusy)
                            .accessibilityLabel("Sign in with \(biometry)")
                        }
                    }
                }
                if let biometry = Biometrics.name, !hasSavedPassword {
                    Toggle("Save password for \(biometry)", isOn: $rememberPassword)
                        .toggleStyle(DSToggleStyle())
                }
                primaryButton("Sign in", disabled: email.isEmpty || password.isEmpty) {
                    await signInWithPassword()
                }
                HStack(spacing: 16) {
                    linkButton("Email me a code instead") {
                        password = ""
                        errorMessage = nil
                        step = .email
                    }
                    linkButton("Forgot?") { app.openPasswordReset() }
                }
            }

        case .mfa(let challengeId, let methods):
            VStack(alignment: .leading, spacing: 12) {
                if usingRecoveryCode {
                    field("Recovery code") {
                        DSTextField(placeholder: "XXXX-XXXX", text: $recoveryCode, mono: true)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .focused($focus, equals: .recovery)
                            .submitLabel(.go)
                            .onSubmit {
                                Task { await verifyMFA(challengeId: challengeId, code: secondFactor) }
                            }
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
                    linkButton(usingRecoveryCode ? "Use my authenticator" : "Use a recovery code") {
                        errorMessage = nil
                        code = ""
                        recoveryCode = ""
                        usingRecoveryCode.toggle()
                    }
                }
            }

        case .welcome:
            VStack(alignment: .leading, spacing: 12) {
                field("Your name") {
                    DSTextField(placeholder: "Olena Kovalenko", text: $displayName)
                        .textContentType(.name)
                        .focused($focus, equals: .name)
                        .submitLabel(.done)
                        .onSubmit { Task { await name() } }
                }
                primaryButton("Continue", disabled: false) { await name() }
                linkButton("Skip") { finish() }
            }
        }
    }

    private var secondFactor: String {
        usingRecoveryCode ? recoveryCode.trimmingCharacters(in: .whitespaces) : code
    }

    // MARK: - Which server this is

    private var serverCard: some View {
        VStack(alignment: .leading, spacing: 6) {
            DSLabel("Server (your Mac's Wi‑Fi address)")
            HStack(spacing: 8) {
                DSTextField(placeholder: "192.168.1.20 or my-mac.local", text: $host, mono: true)
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
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

    private var footer: some View {
        HStack {
            Text(authHost)
                .font(.dsMono(11.5))
                .foregroundStyle(DS.muted)
            Spacer()
            Button(showServer ? "Hide server" : "Server…") {
                withAnimation(.easeOut(duration: 0.15)) { showServer.toggle() }
            }
            .buttonStyle(DSButtonStyle(kind: .ghost, size: 13, height: 28))
            .foregroundStyle(DS.muted)
        }
    }

    private func applyHost() {
        guard let settings = BackendSettings.forHost(host) else { return }
        app.settings = settings
        errorMessage = nil
        focus = nil
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
            // A release build talks https only (IDX-I1 F): a session token
            // over plain http in a shipped app is not acceptable.
            return "\(host) is plain http, which this build does not allow. Use an https address."
        default:
            return error.localizedDescription
        }
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
            focus = nil
            Task { await action() }
        } label: {
            if isBusy {
                ProgressView().tint(DS.inkText)
            } else {
                Text(title)
            }
        }
        .buttonStyle(DSButtonStyle(kind: .primary, height: DS.control, fill: true))
        .disabled(isBusy || disabled)
    }

    private func linkButton(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(.ds(14))
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
        unverified = nil
        defer { isBusy = false }
        do {
            let challenge = try await app.startEmailCode(email: address)
            email = address
            code = ""
            notice = "Enter the code we mailed you."
            resendIn = challenge.resendAfter
            step = .code(challengeId: challenge.challengeId)
        } catch {
            notice = nil
            report(error)
        }
    }

    private func verify(code entered: String, challengeId: String) async {
        guard !isBusy, entered.count >= 6 else { return }
        isBusy = true
        errorMessage = nil
        notice = nil
        defer { isBusy = false }
        do {
            let next = try await app.signIn(withCode: entered, challengeId: challengeId, email: email)
            advance(to: next)
        } catch let error as APIError where error.isUsePassword {
            code = ""
            usePassword(saying: AuthCopy.message(for: error))
        } catch {
            code = ""
            report(error)
        }
    }

    /// The server has said this address signs in with a password. Not an
    /// error to recover from — a different door, already unlocked, so the
    /// address is kept and only the step changes.
    ///
    /// Only `/auth/email/verify` can say this, never `/auth/email/start`:
    /// the start endpoint answers 202 for every address by construction
    /// (`docs/api/error-codes.md`), and a redirection there would tell an
    /// unauthenticated caller which addresses exist. By the time this is
    /// reached the person has proved they hold the mailbox.
    private func usePassword(saying message: String) {
        passwordUnavailable = false
        errorMessage = nil
        notice = message
        step = .password
        focus = .password
    }

    /// Face ID → the password saved on this phone → the normal sign-in.
    /// Silent when the person cancels the prompt; a password the server no
    /// longer accepts is forgotten, so the form is back to typing.
    private func signInWithSavedPassword() async {
        guard !isBusy, let biometry = Biometrics.name else { return }
        errorMessage = nil
        do {
            guard let saved = try await CredentialStore.load(reason: "Sign in to Notes AI") else { return }
            email = saved.email
            password = saved.password
            await signInWithPassword(fromKeychain: true)
        } catch {
            errorMessage = "\(biometry) is not available: \(error.localizedDescription)"
        }
    }

    private func signInWithPassword(fromKeychain: Bool = false) async {
        guard !isBusy, !email.isEmpty, !password.isEmpty else { return }
        isBusy = true
        errorMessage = nil
        unverified = nil
        defer { isBusy = false }
        do {
            let next = try await app.signIn(email: email, password: password, otp: nil)
            // Only after the server has accepted it, and only for the kind
            // of session that has a password at all: a native sign-in that
            // somehow arrived here must not leave one on the phone.
            if rememberPassword, !hasSavedPassword, Biometrics.name != nil,
               app.sessionKind?.canSavePassword == true {
                try? CredentialStore.save(email: email, password: password)
                hasSavedPassword = true
            }
            password = ""
            advance(to: next)
        } catch let error as APIError where error.isEmailNotVerified {
            // A BE-0 account that has not followed the link in its mail.
            // Checked before the saved-password branch too: this is a 403,
            // not a 401, but keeping the two together makes the ordering
            // rule visible — nothing that is *not* a rejected password may
            // be allowed to delete a saved one.
            unverified = email
            password = ""
            errorMessage = AuthCopy.message(for: error)
        } catch let error as APIError where error.isMFARequired {
            // Checked BEFORE the saved-password branch below: Keycloak
            // asks for the second factor with a 401 too, and reading that
            // as "the saved password is wrong" would delete a password
            // that is perfectly good.
            errorMessage = AuthCopy.message(for: error)
            step = .mfa(challengeId: "", methods: ["totp"])
        } catch let error as APIError where fromKeychain && error.status == 401 {
            // The password changed since it was saved. Forget it rather
            // than offering a face that unlocks a rejected password.
            CredentialStore.delete()
            hasSavedPassword = false
            password = ""
            errorMessage = "The saved password no longer works — sign in with the new one."
            focus = .password
        } catch let error as APIError where error.isNotFound {
            // This deployment has no password endpoint (native mode before
            // IDX-A4). Say so once and take the person back to the code.
            passwordUnavailable = true
            password = ""
            step = .email
            errorMessage = "This server signs in with a code sent by email."
        } catch {
            report(error)
        }
    }

    private func verifyMFA(challengeId: String, code entered: String) async {
        guard !isBusy, !entered.isEmpty else { return }
        isBusy = true
        errorMessage = nil
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
            report(error)
        }
    }

    private func name() async {
        await app.setDisplayName(displayName)
        finish()
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
        biometricTried = false
        unverified = nil
        step = .email
    }

    /// A connection failure is a different problem from a rejected code,
    /// and on a phone it is usually the server address — so say which, and
    /// open the field that fixes it.
    private func report(_ error: Error) {
        if let urlError = error as? URLError {
            errorMessage = Self.describe(urlError, settings: app.settings)
            showServer = true
        } else {
            errorMessage = AuthCopy.message(for: error)
        }
    }
}

// MARK: - Locked

/// The gate, when the person cancelled the prompt.
///
/// There is a session on this phone; it is simply unreadable until a face
/// or a passcode says so. The two ways out are the two honest ones: try
/// again, or give the session up.
struct LockedView: View {
    @EnvironmentObject private var app: AppState

    var body: some View {
        VStack(spacing: 18) {
            Spacer()
            Image(systemName: Biometrics.symbol)
                .font(.system(size: 44, weight: .light))
                .foregroundStyle(DS.accentText)
            VStack(spacing: 6) {
                Text("Notes AI is locked")
                    .font(.dsDisplay(22, .medium))
                    .foregroundStyle(DS.text1)
                Text(app.email.isEmpty
                     ? "Unlock to open your notes."
                     : "Unlock to open \(app.email)'s notes.")
                    .font(.ds(14))
                    .foregroundStyle(DS.muted)
                    .multilineTextAlignment(.center)
            }
            Button {
                Task { await app.unlock() }
            } label: {
                if app.unlocking {
                    ProgressView().tint(DS.inkText)
                } else {
                    Label("Unlock", systemImage: Biometrics.symbol)
                }
            }
            .buttonStyle(DSButtonStyle(kind: .primary, height: DS.control, fill: true))
            .disabled(app.unlocking)
            Button("Sign out") { Task { await app.signOut() } }
                .buttonStyle(DSButtonStyle(kind: .ghost, size: 14, height: 34))
                .foregroundStyle(DS.muted)
            Spacer()
        }
        .padding(.horizontal, 32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(ZStack { DSWash(); DSDots() })
    }
}
