import SwiftUI

/// Everything that is not the one-button flow: capture options, theme,
/// backends, account. Shown as a sheet from the avatar menu.
struct SettingsView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel
    var onClose: (() -> Void)? = nil
    @State private var isSigningOut = false
    @State private var showBackends = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 14) {
                Text("Settings")
                    .font(.dsDisplay(18, .medium))
                    .foregroundStyle(DS.text1)
                DSSegmentedPill(
                    options: [
                        .init(AppState.SettingsTab.general, label: "General"),
                        .init(AppState.SettingsTab.connectors, label: "Connectors"),
                    ],
                    selection: $app.settingsTab)
                Spacer()
                if let onClose {
                    Button("Done", action: onClose)
                        .buttonStyle(DSButtonStyle(kind: .secondary, height: 26))
                        .keyboardShortcut(.cancelAction)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 14)
            DSDivider()

            ScrollView {
                if app.settingsTab == .connectors {
                    ConnectorsView(calendar: app.calendar, store: app.connectors)
                        .padding(20)
                } else {
                    general
                }
            }
        }
        .background(DS.bg)
    }

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
                        row("Theme") {
                            DSSelect(
                                options: ThemePref.allCases.map { .init(value: $0, label: $0.title, symbol: $0.symbol) },
                                selection: $app.themePref, width: 150)
                        }
                    }

                    group("Account") {
                        HStack(spacing: 10) {
                            DSAvatar(name: app.email.isEmpty ? "?" : app.email, size: 30)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(app.email.isEmpty ? "Not signed in" : app.email)
                                    .font(.ds(13, .medium))
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
                    }

                    group("Advanced") {
                        Button {
                            withAnimation(.easeOut(duration: 0.15)) { showBackends.toggle() }
                        } label: {
                            HStack(spacing: 6) {
                                Image(systemName: "chevron.right")
                                    .font(.system(size: 10, weight: .semibold))
                                    .rotationEffect(.degrees(showBackends ? 90 : 0))
                                Text("Server addresses")
                                    .font(.ds(13))
                                Spacer()
                            }
                            .foregroundStyle(DS.text2)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        if showBackends {
                            labeledField("Auth", text: $app.settings.authBaseURL)
                            labeledField("ASR", text: $app.settings.asrBaseURL)
                            labeledField("Notes", text: $app.settings.noteBaseURL)
                            labeledField("Web", text: $app.settings.webAppURL)
                        }
                    }

                    HStack {
                        Spacer()
                        Button("Quit Notes AI Capture") { NSApp.terminate(nil) }
                            .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 26))
                            .foregroundStyle(DS.muted)
                        Spacer()
                    }
                }
                .padding(20)
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
