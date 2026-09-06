import SwiftUI

/// Everything that is not the one-button flow: capture options, theme,
/// backends, account. Shown as a sheet from the avatar menu — a sidebar of
/// sections on the left, the selected section on the right.
struct SettingsView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel
    var onClose: (() -> Void)? = nil
    @State private var isSigningOut = false
    @State private var nameDraft = ""
    @State private var savingName = false
    @State private var removingIdentity: String?

    private static let sidebarWidth: CGFloat = 200

    var body: some View {
        HStack(spacing: 0) {
            sidebar
                .frame(width: Self.sidebarWidth)
                .frame(maxHeight: .infinity)
                .background(DS.sidebar)
            Rectangle().fill(DS.line).frame(width: DS.hairline).frame(maxHeight: .infinity)
            VStack(alignment: .leading, spacing: 0) {
                HStack {
                    Text(title(for: app.settingsTab))
                        .font(.dsDisplay(18, .medium))
                        .foregroundStyle(DS.text1)
                    Spacer()
                    if let onClose {
                        Button("Done", action: onClose)
                            .buttonStyle(DSButtonStyle(kind: .secondary, height: 26))
                            .keyboardShortcut(.cancelAction)
                    }
                }
                .padding(.horizontal, 24)
                .padding(.vertical, 14)
                DSDivider()

                ScrollView {
                    Group {
                        switch app.settingsTab {
                        case .general:
                            general
                        case .connectors:
                            ConnectorsView(calendar: app.calendar, google: app.googleCalendar, store: app.connectors)
                        case .account:
                            account
                        case .advanced:
                            advanced
                        }
                    }
                    .padding(24)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(DS.bg)
        }
        .alert("Remove local data?",
               isPresented: Binding(get: { removingIdentity != nil },
                                    set: { if !$0 { removingIdentity = nil } })) {
            Button("Remove", role: .destructive) {
                if let removingIdentity { app.removeLocalData(identityId: removingIdentity) }
                removingIdentity = nil
            }
            Button("Cancel", role: .cancel) { removingIdentity = nil }
        } message: {
            Text("This deletes that account's meetings list and any recordings kept for it on this Mac. Recordings that were never uploaded cannot be recovered.")
        }
    }

    // MARK: - Sidebar

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Settings")
                .font(.dsDisplay(15, .medium))
                .foregroundStyle(DS.text1)
                .padding(.horizontal, 10)
                .padding(.top, 18)
                .padding(.bottom, 12)
            navRow("General", symbol: "slider.horizontal.3", tab: .general)
            navRow("Connectors", symbol: "link", tab: .connectors)
            navRow("Account", symbol: "person.crop.circle", tab: .account)
            navRow("Advanced", symbol: "wrench.and.screwdriver", tab: .advanced)
            Spacer()
            Button("Quit Notes AI Capture") { NSApp.terminate(nil) }
                .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 26))
                .foregroundStyle(DS.muted)
                .padding(.bottom, 8)
        }
        .padding(.horizontal, 10)
    }

    private func navRow(_ label: String, symbol: String, tab: AppState.SettingsTab) -> some View {
        let on = app.settingsTab == tab
        return Button {
            app.settingsTab = tab
        } label: {
            HStack(spacing: 8) {
                Image(systemName: symbol)
                    .font(.system(size: 12, weight: .medium))
                    .frame(width: 16)
                Text(label)
                    .font(.ds(13, .medium))
                Spacer()
            }
            .foregroundStyle(on ? DS.text1 : DS.text3)
            .padding(.horizontal, 10)
            .frame(height: 30)
            .background(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .fill(on ? DS.sidebarOn : .clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: DS.radius, style: .continuous)
                    .strokeBorder(DS.line, lineWidth: on ? DS.hairline : 0)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private func title(for tab: AppState.SettingsTab) -> String {
        switch tab {
        case .general: return "General"
        case .connectors: return "Connectors"
        case .account: return "Account"
        case .advanced: return "Advanced"
        }
    }

    // MARK: - Sections

    private var general: some View {
        VStack(alignment: .leading, spacing: 20) {
            group("Meetings") {
                row("Language") {
                    DSSegmentedPill(
                        options: [
                            .init(CaptureViewModel.autoLanguage, label: "Auto",
                                  help: "Detect from the recording"),
                            .init("en", label: "EN", help: "English"),
                            .init("uk", label: "UK", help: "Українська"),
                            .init("de", label: "DE", help: "Deutsch"),
                        ],
                        selection: $capture.language)
                }
                row("Separate speakers") {
                    Toggle("", isOn: $capture.diarize)
                        .toggleStyle(DSToggleStyle())
                        .labelsHidden()
                }
            }

            group("Appearance") {
                row("Theme") {
                    DSSelect(
                        options: ThemePref.allCases.map { .init(value: $0, label: $0.title, symbol: $0.symbol) },
                        selection: $app.themePref, width: 150)
                }
            }
        }
    }

    private var account: some View {
        VStack(alignment: .leading, spacing: 20) {
            group("Signed in as") {
                HStack(spacing: 10) {
                    DSAvatar(name: displayName, size: 30)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(displayName)
                            .font(.ds(13, .medium))
                            .foregroundStyle(DS.text1)
                            .lineLimit(1)
                        Text(app.identity == nil ? authHost : "\(app.email) · \(authHost)")
                            .font(.dsMeta)
                            .foregroundStyle(DS.muted)
                            .lineLimit(1)
                    }
                    Spacer()
                    Button {
                        guard app.pendingCount == 0 else {
                            onClose?()
                            app.requestSignOut()
                            return
                        }
                        isSigningOut = true
                        Task {
                            await app.signOut()
                            isSigningOut = false
                            onClose?()
                        }
                    } label: {
                        if isSigningOut {
                            ProgressView().controlSize(.small)
                        } else {
                            Text("Sign out")
                        }
                    }
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                    .disabled(isSigningOut)
                }
                Text("The sign-in for this Mac is kept in its login Keychain and never leaves it. Signing out removes it.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            group("Your name") {
                HStack(spacing: 10) {
                    DSTextField(placeholder: "Your name", text: $nameDraft)
                    Button(savingName ? "Saving…" : "Save") {
                        savingName = true
                        Task {
                            await app.setDisplayName(nameDraft)
                            savingName = false
                        }
                    }
                    .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                    .disabled(savingName || nameDraft.trimmingCharacters(in: .whitespaces).isEmpty
                              || nameDraft == app.identity?.displayName)
                }
            }
            .onAppear { if nameDraft.isEmpty { nameDraft = app.identity?.displayName ?? "" } }

            workspacesGroup
            securityGroup

            if pendingCount > 0 {
                group("Recordings waiting") {
                    HStack(spacing: 10) {
                        Image(systemName: "waveform.badge.exclamationmark")
                            .foregroundStyle(DS.warn)
                        VStack(alignment: .leading, spacing: 1) {
                            Text("\(pendingCount) recording\(pendingCount == 1 ? "" : "s") kept on this Mac")
                                .font(.ds(13, .medium))
                                .foregroundStyle(DS.text1)
                            Text("These could not be uploaded — the session had ended, or the server was unreachable. They are kept until they can be sent.")
                                .font(.dsMeta)
                                .foregroundStyle(DS.muted)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer()
                        Button("Show in Finder") {
                            NSWorkspace.shared.activateFileViewerSelecting(
                                PendingCaptures.all().map(\.audioURL))
                        }
                        .buttonStyle(DSButtonStyle(kind: .secondary, height: 28))
                    }
                }
            }
        }
    }

    // ── Workspaces, sessions and local data (IDX-M2) ─────────────────

    private var workspacesGroup: some View {
        group("Workspaces") {
            VStack(alignment: .leading, spacing: 8) {
                WorkspaceList(onSwitch: { onClose?() })
                Text("Notes, spaces and meetings belong to a workspace. Switching changes what this Mac shows and what new meetings are filed under.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var securityGroup: some View {
        group("Security") {
            VStack(alignment: .leading, spacing: 10) {
                SessionsList()
                DSDivider()
                HStack {
                    Text("Password, two-factor and email changes")
                        .font(.ds(12.5))
                        .foregroundStyle(DS.text2)
                    Spacer()
                    Button("Manage on the web") { app.openSecuritySettings() }
                        .buttonStyle(DSButtonStyle(kind: .secondary, height: 26))
                }
            }
        }
    }

    private var localDataGroup: some View {
        let others = app.otherLocalIdentities
        return Group {
            if !others.isEmpty {
                group("Other accounts on this Mac") {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(others, id: \.id) { other in
                            HStack(spacing: 10) {
                                DSAvatar(name: other.email.isEmpty ? "?" : other.email, size: 24)
                                Text(other.email.isEmpty ? other.id : other.email)
                                    .font(.ds(13))
                                    .foregroundStyle(DS.text1)
                                    .lineLimit(1)
                                Spacer()
                                Button("Remove local data") { removingIdentity = other.id }
                                    .buttonStyle(DSButtonStyle(kind: .secondary, size: 12, height: 24))
                            }
                        }
                        Text("Their meetings list and any recordings kept for them stay on this Mac until removed here. Nothing on the server is touched.")
                            .font(.dsMeta)
                            .foregroundStyle(DS.muted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
    }

    private var displayName: String {
        let name = app.identity?.displayName ?? ""
        if !name.isEmpty { return name }
        return app.email.isEmpty ? "Not signed in" : app.email
    }

    /// Read once per appearance of the sheet: this is a directory listing,
    /// not something to poll.
    private var pendingCount: Int { PendingCaptures.count() }

    private var advanced: some View {
        VStack(alignment: .leading, spacing: 20) {
            localDataGroup
            group("Server addresses") {
                labeledField("Auth", text: $app.settings.authBaseURL)
                labeledField("ASR", text: $app.settings.asrBaseURL)
                labeledField("Notes", text: $app.settings.noteBaseURL)
                labeledField("Web", text: $app.settings.webAppURL)
            }
        }
    }

    private var authHost: String {
        URL(string: app.settings.authBaseURL)?.host() ?? app.settings.authBaseURL
    }

    private func group(_ title: String, @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            DSLabel(title)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dsCard()
    }

    private func row(_ label: String, @ViewBuilder control: () -> some View) -> some View {
        HStack {
            Text(label)
                .font(.ds(13))
                .foregroundStyle(DS.text1)
            Spacer()
            control()
        }
    }

    private func labeledField(_ label: String, text: Binding<String>) -> some View {
        HStack(spacing: 10) {
            Text(label)
                .font(.ds(12.5))
                .foregroundStyle(DS.text3)
                .frame(width: 44, alignment: .leading)
            DSTextField(placeholder: label, text: text, mono: true)
        }
    }
}
