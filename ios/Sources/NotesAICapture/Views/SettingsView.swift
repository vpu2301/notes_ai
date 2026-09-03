import SwiftUI

/// Everything that is not the one-button flow: capture options, theme,
/// connectors, account, backends. A sheet with cards; Connectors is a page
/// of its own inside it.
struct SettingsView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel
    @State private var path: [AppState.SettingsTab] = []
    @State private var isSigningOut = false
    @State private var host = ""
    @State private var hostApplied = false
    @State private var savedPassword = CredentialStore.hasSaved

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    // Signed out, the server is what you came for.
                    if app.authState != .signedIn { advanced }
                    general
                    appearance
                    if app.authState == .signedIn {
                        connectorsRow
                        account
                        advanced
                    }
                }
                .padding(.horizontal, DS.gutter)
                .padding(.vertical, 12)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(DS.bg)
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { app.settingsPresented = false }
                        .font(.ds(15, .semibold))
                }
            }
            .navigationDestination(for: AppState.SettingsTab.self) { tab in
                switch tab {
                case .connectors:
                    ConnectorsView(calendar: app.calendar, google: app.googleCalendar, store: app.connectors)
                case .general:
                    EmptyView()
                }
            }
        }
        .tint(DS.accentText)
        .onAppear {
            if app.settingsTab == .connectors { path = [.connectors] }
        }
        .onDisappear { app.settingsTab = .general }
    }

    // MARK: - Sections

    private var general: some View {
        group("Meetings") {
            VStack(alignment: .leading, spacing: 8) {
                Text("Language")
                    .font(.ds(15))
                    .foregroundStyle(DS.text1)
                DSSegmentedPill(
                    options: [
                        .init(CaptureViewModel.autoLanguage, label: "Auto",
                              help: "Detect from the recording"),
                        .init("en", label: "EN", help: "English"),
                        .init("uk", label: "UK", help: "Українська"),
                        .init("de", label: "DE", help: "Deutsch"),
                    ],
                    selection: $capture.language)
                Text("Auto lets each recording decide; the transcript and the note come out in the language spoken.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            DSDivider()
            Toggle("Separate speakers", isOn: $capture.diarize)
                .toggleStyle(DSToggleStyle())
        }
    }

    private var appearance: some View {
        group("Appearance") {
            row("Theme") {
                DSSelect(
                    options: ThemePref.allCases.map { .init(value: $0, label: $0.title, symbol: $0.symbol) },
                    selection: $app.themePref, width: 170)
            }
        }
    }

    private var connectorsRow: some View {
        NavigationLink(value: AppState.SettingsTab.connectors) {
            HStack(spacing: 12) {
                Image(systemName: "puzzlepiece.extension")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(DS.accentText)
                    .frame(width: 32, height: 32)
                    .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(DS.accentSoft))
                VStack(alignment: .leading, spacing: 2) {
                    Text("Connectors")
                        .font(.ds(15, .medium))
                        .foregroundStyle(DS.text1)
                    Text("Calendars, HubSpot, Notion and other MCP servers")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(DS.muted)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .dsCard(padding: 14)
    }

    private var account: some View {
        group("Signed in as") {
            HStack(spacing: 10) {
                DSAvatar(name: app.email.isEmpty ? "?" : app.email, size: 34)
                VStack(alignment: .leading, spacing: 1) {
                    Text(app.email.isEmpty ? "Not signed in" : app.email)
                        .font(.ds(15, .medium))
                        .foregroundStyle(DS.text1)
                        .lineLimit(1)
                    Text(authHost)
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .lineLimit(1)
                }
                Spacer()
                Button {
                    isSigningOut = true
                    Task {
                        await app.signOut()
                        isSigningOut = false
                    }
                } label: {
                    if isSigningOut {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("Sign out")
                    }
                }
                .buttonStyle(DSButtonStyle(kind: .secondary, size: 14, height: 34))
                .disabled(isSigningOut)
            }
            if let biometry = CredentialStore.biometryName {
                DSDivider()
                HStack(spacing: 10) {
                    Image(systemName: CredentialStore.biometrySymbol)
                        .font(.system(size: 16, weight: .medium))
                        .foregroundStyle(DS.accentText)
                        .frame(width: 24)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(savedPassword ? "Sign in with \(biometry)" : "\(biometry) sign-in is off")
                            .font(.ds(15, .medium))
                            .foregroundStyle(DS.text1)
                        Text(savedPassword
                             ? "The password is kept in this phone's Keychain, behind \(biometry)."
                             : "Turn on “Save password for \(biometry)” the next time you sign in.")
                            .font(.dsMeta)
                            .foregroundStyle(DS.muted)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer()
                    if savedPassword {
                        Button("Forget") {
                            CredentialStore.delete()
                            savedPassword = false
                        }
                        .buttonStyle(DSButtonStyle(kind: .ghost, size: 14, height: 34))
                        .foregroundStyle(DS.dangerText)
                    }
                }
            }
        }
        .onAppear { savedPassword = CredentialStore.hasSaved }
    }

    private var advanced: some View {
        VStack(alignment: .leading, spacing: 18) {
            group("Server") {
                Text(isPhysicalDevice
                     ? "The computer running Notes AI, by its address on your Wi‑Fi. Find it in System Settings › Wi‑Fi › Details on the Mac, and publish the stack with PUBLISH_HOST=0.0.0.0 in its .env."
                     : "The computer running Notes AI. On the simulator, localhost is the Mac.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 8) {
                    DSTextField(placeholder: "192.168.1.20", text: $host, mono: true)
                        .keyboardType(.URL)
                        .submitLabel(.done)
                        .onSubmit(applyHost)
                    Button(hostApplied ? "Applied" : "Use") { applyHost() }
                        .buttonStyle(DSButtonStyle(kind: .primary, size: 14, height: DS.control))
                        .disabled(BackendSettings.forHost(host) == nil || hostApplied)
                }
                if let problem = BackendSettings.hostProblem(host) {
                    Text(problem)
                        .font(.dsMeta)
                        .foregroundStyle(DS.dangerText)
                        .fixedSize(horizontal: false, vertical: true)
                } else if isPhysicalDevice, app.settings.pointsAtLocalhost {
                    DSNotice(tone: .warn, symbol: "wifi.exclamationmark",
                             text: "localhost is this phone, not your Mac — enter the Mac's Wi‑Fi address above.")
                }
            }
            group("Server addresses") {
                labeledField("Auth", text: $app.settings.authBaseURL)
                labeledField("ASR", text: $app.settings.asrBaseURL)
                labeledField("Notes", text: $app.settings.noteBaseURL)
                labeledField("Web", text: $app.settings.webAppURL)
            }
        }
        .onAppear { host = app.settings.commonHost ?? "" }
        .onChange(of: host) { _, _ in hostApplied = false }
    }

    private func applyHost() {
        guard let settings = BackendSettings.forHost(host) else { return }
        app.settings = settings
        hostApplied = true
    }

    private var authHost: String {
        URL(string: app.settings.authBaseURL)?.host() ?? app.settings.authBaseURL
    }

    private func group(_ title: String, @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            DSLabel(title)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .dsCard()
    }

    private func row(_ label: String, @ViewBuilder control: () -> some View) -> some View {
        HStack {
            Text(label)
                .font(.ds(15))
                .foregroundStyle(DS.text1)
            Spacer()
            control()
        }
    }

    private func labeledField(_ label: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label)
                .font(.ds(13, .medium))
                .foregroundStyle(DS.text3)
            DSTextField(placeholder: label, text: text, mono: true)
                .keyboardType(.URL)
        }
    }
}
