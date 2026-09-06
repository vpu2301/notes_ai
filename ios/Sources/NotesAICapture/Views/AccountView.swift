import SwiftUI

/// Settings › Account: who you are, where you are signed in, and what this
/// phone is holding on your behalf.
///
/// Everything on this page is about a thing that can be taken away — a
/// name, a membership, a session, a recording — so every row says what
/// will actually happen before it happens. The two destructive ones (sign
/// out with recordings waiting, remove another account's data) ask twice.
struct AccountView: View {
    @EnvironmentObject private var app: AppState

    @State private var name = ""
    @State private var savingName = false
    @State private var nameError: String?
    @State private var sessions: [DeviceSession] = []
    @State private var sessionsLoading = false
    @State private var sessionsError: String?
    @State private var revoking: Set<String> = []
    @State private var confirmRevokeOthers = false
    @State private var confirmSignOut = false
    @State private var isSigningOut = false
    @State private var confirmRemoveOthers = false
    @State private var gateBusy = false
    @State private var gateError: String?
    /// Whether this phone holds a saved password (Keycloak sessions only,
    /// during the dual-issuer period). Read once, then owned by the row.
    @State private var savedPassword = CredentialStore.hasSaved

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                profile
                workspaces
                security
                sessionsCard
                if !app.oldPending.isEmpty {
                    PendingUploadsSection(captures: app.oldPending, stale: true)
                }
                data
                signOut
            }
            .padding(.horizontal, DS.gutter)
            .padding(.vertical, 12)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(DS.bg)
        .navigationTitle("Account")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            name = app.identity?.displayName ?? ""
            await app.refreshWorkspaces()
            await loadSessions()
        }
    }

    // MARK: - Profile

    private var profile: some View {
        group("You") {
            HStack(spacing: 12) {
                DSAvatar(name: displayName, size: 44)
                VStack(alignment: .leading, spacing: 1) {
                    Text(displayName)
                        .font(.ds(16, .medium))
                        .foregroundStyle(DS.text1)
                        .lineLimit(1)
                    Text(app.email.isEmpty ? "Not signed in" : app.email)
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            DSDivider()
            VStack(alignment: .leading, spacing: 6) {
                DSLabel("Your name")
                HStack(spacing: 8) {
                    DSTextField(placeholder: "Olena Kovalenko", text: $name)
                        .textContentType(.name)
                        .submitLabel(.done)
                        .onSubmit { Task { await saveName() } }
                    Button {
                        Task { await saveName() }
                    } label: {
                        if savingName {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("Save")
                        }
                    }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: DS.control))
                    .disabled(savingName || !nameChanged)
                }
                Text("What colleagues see on notes you write.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                if let nameError {
                    DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: nameError)
                }
            }
        }
    }

    private var displayName: String {
        let stored = app.identity?.displayName ?? ""
        if !stored.isEmpty { return stored }
        return app.email.isEmpty ? "Not signed in" : app.email
    }

    private var nameChanged: Bool {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty && trimmed != (app.identity?.displayName ?? "")
    }

    private func saveName() async {
        guard nameChanged, !savingName else { return }
        savingName = true
        nameError = nil
        defer { savingName = false }
        await app.setDisplayName(name)
        if app.identity?.displayName != name.trimmingCharacters(in: .whitespacesAndNewlines) {
            nameError = "That name could not be saved. Try again in a moment."
        }
    }

    // MARK: - Workspaces

    private var workspaces: some View {
        group("Workspaces") {
            if app.workspaces.isEmpty {
                Text("No workspaces yet. Ask a colleague to add you to theirs.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
            }
            ForEach(Array(app.workspaces.enumerated()), id: \.element.id) { index, workspace in
                if index > 0 { DSDivider() }
                workspaceRow(workspace)
            }
            Text("Notes, spaces and meetings belong to one workspace at a time. Recordings waiting to upload keep the workspace they were made for.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func workspaceRow(_ workspace: Workspace) -> some View {
        let isActive = workspace.id == app.tenantId
        return HStack(spacing: 10) {
            VStack(alignment: .leading, spacing: 1) {
                Text(workspace.title)
                    .font(.ds(15, .medium))
                    .foregroundStyle(DS.text1)
                    .lineLimit(1)
                Text(workspace.roleLabel)
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
            }
            Spacer(minLength: 0)
            if app.switchingTo == workspace.id {
                ProgressView().controlSize(.small)
            } else if isActive {
                DSChip(text: "Open", tint: DS.accentText, soft: DS.accentSoft)
            } else {
                Button("Switch") { Task { await app.switchWorkspace(to: workspace) } }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 32))
                    // Native sessions only, during the dual-issuer period:
                    // auth-service cannot re-mint a Keycloak token for
                    // another tenant (ADR-0047).
                    .disabled(app.switchingTo != nil || !app.canSwitchWorkspace)
            }
        }
    }

    // MARK: - Security (the saved password, and the web app for the rest)

    private var security: some View {
        group("Security") {
            if app.sessionKind?.canSavePassword == true, Biometrics.name != nil,
               savedPassword {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 8) {
                        Text("Password saved for \(Biometrics.name ?? "Face ID")")
                            .font(.ds(15))
                            .foregroundStyle(DS.text1)
                        Spacer()
                        Button("Forget") {
                            CredentialStore.delete()
                            savedPassword = false
                        }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 32))
                    }
                    Text("This phone can sign you in again with \(Biometrics.name ?? "the passcode") instead of the password. Forgetting it means typing the password next time.")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .fixedSize(horizontal: false, vertical: true)
                }
                DSDivider()
            }
            // The biometric gate is built and tested (IDX-I1) but not
            // offered in this batch: during the dual-issuer period a phone
            // may hold a Keycloak session, which has no native refresh
            // token to seal, and a toggle that works for half the user
            // base is worse than one that is not there yet. I1-05 turns
            // `AppState.gateOffered` on once every session is native.
            if AppState.gateOffered, app.canGate, Biometrics.isAvailable {
                VStack(alignment: .leading, spacing: 8) {
                    Toggle(Biometrics.gateTitle, isOn: gateBinding)
                        .toggleStyle(DSToggleStyle())
                        .disabled(gateBusy)
                    Text(app.gateOn
                         ? "The session key is encrypted with a key only \(Biometrics.name ?? "your passcode") can release. Re-enrolling \(Biometrics.name ?? "the passcode") signs this phone out."
                         : "Off: the app opens straight into your notes, and the session key is protected by the phone's own encryption.")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .fixedSize(horizontal: false, vertical: true)
                    if let gateError {
                        DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: gateError)
                    }
                }
                DSDivider()
            }
            Button {
                app.openSecuritySettings()
            } label: {
                HStack(spacing: 8) {
                    Text("Manage security on the web")
                        .font(.ds(15))
                        .foregroundStyle(DS.accentText)
                    Spacer()
                    Image(systemName: "arrow.up.right.square")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(DS.muted)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            Text("Passwords, two-factor sign-in and account deletion live in the web app — they are rare, and they are safer where there is a keyboard.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var gateBinding: Binding<Bool> {
        Binding(get: { app.gateOn }, set: { wanted in
            guard !gateBusy else { return }
            gateBusy = true
            gateError = nil
            Task {
                gateError = await app.setGate(enabled: wanted)
                gateBusy = false
            }
        })
    }

    // MARK: - Sessions

    private var sessionsCard: some View {
        group("Where you are signed in") {
            if sessionsLoading, sessions.isEmpty {
                DSSkeleton(height: 44)
            }
            ForEach(Array(sessions.enumerated()), id: \.element.id) { index, session in
                if index > 0 { DSDivider() }
                sessionRow(session)
            }
            if let sessionsError {
                DSNotice(tone: .danger, symbol: "exclamationmark.triangle.fill", text: sessionsError)
            }
            if sessions.count > 1 {
                DSDivider()
                Button("Sign out everywhere else") { confirmRevokeOthers = true }
                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 36))
                    .foregroundStyle(DS.dangerText)
            }
        }
        .confirmationDialog("Sign out everywhere else?", isPresented: $confirmRevokeOthers,
                            titleVisibility: .visible) {
            Button("Sign out other devices", role: .destructive) {
                Task { await revokeOthers() }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Every other phone, Mac and browser signed in as you is signed out. This phone stays signed in. You will be asked to confirm it is you.")
        }
    }

    private func sessionRow(_ session: DeviceSession) -> some View {
        HStack(spacing: 10) {
            Image(systemName: session.symbol)
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(session.current ? DS.accentText : DS.muted)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 6) {
                    Text(session.title)
                        .font(.ds(15, .medium))
                        .foregroundStyle(DS.text1)
                    if session.current {
                        DSChip(text: "This phone", tint: DS.accentText, soft: DS.accentSoft)
                    }
                }
                Text(sessionSubtitle(session))
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
            if revoking.contains(session.sid) {
                ProgressView().controlSize(.small)
            } else if !session.current {
                Button("End") { Task { await revoke(session) } }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 14, height: 32))
                    .foregroundStyle(DS.dangerText)
            }
        }
    }

    private func sessionSubtitle(_ session: DeviceSession) -> String {
        var parts = ["Last used \(relativeTime(session.lastUsedAt))"]
        if !session.ipLast.isEmpty { parts.append(session.ipLast) }
        return parts.joined(separator: " · ")
    }

    private func loadSessions() async {
        sessionsLoading = true
        defer { sessionsLoading = false }
        do {
            sessions = try await app.api.sessions()
            sessionsError = nil
        } catch {
            // A session list that cannot be fetched is worth saying so
            // about: this is the screen people come to when they think
            // somebody else is signed in as them.
            sessionsError = AuthCopy.message(for: error)
        }
    }

    private func revoke(_ session: DeviceSession) async {
        revoking.insert(session.sid)
        defer { revoking.remove(session.sid) }
        do {
            try await app.api.revokeSession(id: session.sid)
            sessions.removeAll { $0.sid == session.sid }
        } catch {
            sessionsError = AuthCopy.message(for: error)
        }
    }

    private func revokeOthers() async {
        do {
            // `403 reauth_required` comes back from the server here and is
            // answered by the step-up sheet inside `APIClient`, which then
            // retries this request once. Nothing to do about it here.
            _ = try await app.api.revokeOtherSessions()
            await loadSessions()
        } catch {
            sessionsError = AuthCopy.message(for: error)
        }
    }

    // MARK: - What this phone is holding

    private var data: some View {
        group("On this phone") {
            row("Recordings waiting", value: "\(app.pending.count)")
            row("Meetings remembered here", value: "\(app.recents.count)")
            if !app.otherScopes.isEmpty {
                DSDivider()
                VStack(alignment: .leading, spacing: 8) {
                    Text("Other accounts and workspaces have left \(app.otherScopes.count) \(app.otherScopes.count == 1 ? "list" : "lists") of meetings on this phone. Removing them does not touch anything on the server, and does not touch recordings waiting to upload.")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .fixedSize(horizontal: false, vertical: true)
                    Button("Remove local data for other accounts") { confirmRemoveOthers = true }
                        .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 36))
                        .foregroundStyle(DS.dangerText)
                }
            }
        }
        .confirmationDialog("Remove other accounts' data?", isPresented: $confirmRemoveOthers,
                            titleVisibility: .visible) {
            Button("Remove", role: .destructive) { app.removeLocalData(for: app.otherScopes) }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The meeting lists other accounts and workspaces left on this phone are deleted. Notes on the server are untouched, and so is every recording still waiting to upload.")
        }
    }

    // MARK: - Sign out

    private var signOut: some View {
        VStack(alignment: .leading, spacing: 8) {
            Button {
                // A recording that has not been uploaded belongs to the
                // session that is about to end: say so before it does,
                // rather than after.
                if app.pending.isEmpty {
                    Task { await performSignOut() }
                } else {
                    confirmSignOut = true
                }
            } label: {
                if isSigningOut {
                    ProgressView().tint(DS.inkText)
                } else {
                    Text("Sign out")
                }
            }
            .buttonStyle(DSButtonStyle(kind: .primary, height: DS.control, fill: true))
            .disabled(isSigningOut)
            Text("The session key is removed from this phone's Keychain. Recordings waiting to upload stay, and are sent when you sign in again.")
                .font(.dsMeta)
                .foregroundStyle(DS.muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .confirmationDialog("Sign out with recordings waiting?", isPresented: $confirmSignOut,
                            titleVisibility: .visible) {
            Button("Sign out anyway") { Task { await performSignOut() } }
            Button("Stay signed in", role: .cancel) {}
        } message: {
            Text("\(app.pending.count) \(app.pending.count == 1 ? "recording has" : "recordings have") not been uploaded. They are kept on this phone and can be sent when you sign in again — but nothing uploads while you are signed out.")
        }
    }

    private func performSignOut() async {
        isSigningOut = true
        await app.signOut()
        isSigningOut = false
    }

    // MARK: - Pieces

    private func group(_ title: String, @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            DSLabel(title)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dsCard()
    }

    private func row(_ label: String, value: String) -> some View {
        HStack {
            Text(label)
                .font(.ds(15))
                .foregroundStyle(DS.text1)
            Spacer()
            Text(value)
                .font(.dsMono(14))
                .foregroundStyle(DS.muted)
        }
    }
}
