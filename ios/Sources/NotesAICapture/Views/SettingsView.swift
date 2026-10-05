import SwiftUI

/// Settings: capture options, theme, connectors, account, backends.
struct SettingsView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel
    @State private var path: [AppState.SettingsTab] = []
    @State private var host = ""
    @State private var hostApplied = false

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    general
                    appearance
                    if app.authState == .signedIn {
                        vocabulary
                        connectorsRow
                        dataRow
                        account
                    }
                    // Last: the server is set once and left alone.
                    advanced
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
                case .dataAI:
                    DataAndAIView()
                case .account:
                    AccountView()
                case .general:
                    EmptyView()
                }
            }
        }
        .tint(DS.accentText)
        .onAppear {
            if app.settingsTab == .connectors { path = [.connectors] }
            if app.settingsTab == .account { path = [.account] }
            if app.settingsTab == .dataAI { path = [.dataAI] }
            app.refreshPending()
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
            VStack(alignment: .leading, spacing: 8) {
                Text("People")
                    .font(.ds(15))
                    .foregroundStyle(capture.diarize ? DS.text1 : DS.muted)
                PeoplePicker()
                Text("How many people usually speak. Auto and 6+ let each recording decide.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
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

    private var vocabulary: some View {
        group("Names and terms") {
            GlossaryView()
        }
    }

    private var connectorsRow: some View {
        NavigationLink(value: AppState.SettingsTab.connectors) {
            HStack(spacing: 12) {
                Image(systemName: "puzzlepiece.extension")
                    .font(.dsSymbol(14, .medium))
                    .foregroundStyle(DS.accentText)
                    .frame(width: 32, height: 32)
                    .background(RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous).fill(DS.accentSoft))
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
                    .font(.dsSymbol(12, .semibold))
                    .foregroundStyle(DS.muted)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .dsCard(padding: 14)
    }

    /// Who processes this workspace's meetings. Read-only here; changed on the web.
    private var dataRow: some View {
        NavigationLink(value: AppState.SettingsTab.dataAI) {
            HStack(spacing: 12) {
                Image(systemName: "lock.shield")
                    .font(.dsSymbol(14, .medium))
                    .foregroundStyle(DS.accentText)
                    .frame(width: 32, height: 32)
                    .background(RoundedRectangle(cornerRadius: DS.radiusSm, style: .continuous).fill(DS.accentSoft))
                VStack(alignment: .leading, spacing: 2) {
                    Text("Data & AI")
                        .font(.ds(15, .medium))
                        .foregroundStyle(DS.text1)
                    Text("Who processes your meetings, and what it costs")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.dsSymbol(12, .semibold))
                    .foregroundStyle(DS.muted)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .dsCard(padding: 14)
    }

    /// Account, workspaces and sessions are a page of their own.
    private var account: some View {
        NavigationLink(value: AppState.SettingsTab.account) {
            HStack(spacing: 12) {
                DSAvatar(name: displayName, size: 32)
                VStack(alignment: .leading, spacing: 2) {
                    Text(displayName)
                        .font(.ds(15, .medium))
                        .foregroundStyle(DS.text1)
                        .lineLimit(1)
                    Text(subtitle)
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                        .lineLimit(1)
                }
                Spacer()
                if app.pending.isEmpty {
                    Image(systemName: "chevron.right")
                        .font(.dsSymbol(12, .semibold))
                        .foregroundStyle(DS.muted)
                } else {
                    DSChip(text: "\(app.pending.count) waiting", tint: DS.warn, soft: DS.warnSoft)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .dsCard(padding: 14)
    }

    private var displayName: String {
        let name = app.identity?.displayName ?? ""
        if !name.isEmpty { return name }
        return app.email.isEmpty ? "Not signed in" : app.email
    }

    /// The workspace comes first; the address is only confirmation.
    private var subtitle: String {
        var parts: [String] = []
        if let workspace = app.activeWorkspace { parts.append(workspace.title) }
        if !app.email.isEmpty, app.identity?.displayName.isEmpty == false { parts.append(app.email) }
        if parts.isEmpty { parts.append(authHost) }
        return parts.joined(separator: " · ")
    }

    private var advanced: some View {
        group("Advanced") {
            VStack(alignment: .leading, spacing: 8) {
                Text("Server")
                    .font(.ds(15))
                    .foregroundStyle(DS.text1)
                Text("The address of the Notes AI server this phone talks to — a name or an IP address.")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 8) {
                    DSTextField(placeholder: "notes.example.com", text: $host, mono: true)
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
                             text: "The address points at this phone itself. Enter the server's address above.")
                }
            }
            DSDivider()
            VStack(alignment: .leading, spacing: 10) {
                Text("Service addresses")
                    .font(.ds(15))
                    .foregroundStyle(DS.text1)
                labeledField("Sign-in", text: $app.settings.authBaseURL)
                labeledField("Transcription", text: $app.settings.asrBaseURL)
                labeledField("Notes", text: $app.settings.noteBaseURL)
                labeledField("Notifications", text: $app.settings.notificationBaseURL)
                labeledField("Web app", text: $app.settings.webAppURL)
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
