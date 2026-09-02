import SwiftUI

struct SettingsView: View {
    @EnvironmentObject private var app: AppState
    @State private var isSigningOut = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            section("Backends") {
                labeledField("Auth", text: $app.settings.authBaseURL)
                labeledField("ASR", text: $app.settings.asrBaseURL)
                labeledField("Notes", text: $app.settings.noteBaseURL)
            }

            section("Web app") {
                labeledField("URL", text: $app.settings.webAppURL)
            }

            Divider()

            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Signed in as")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                    Text(app.email.isEmpty ? "—" : app.email)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer()
                Button(role: .destructive) {
                    isSigningOut = true
                    Task {
                        await app.signOut()
                        isSigningOut = false
                    }
                } label: {
                    if isSigningOut {
                        ProgressView().controlSize(.small)
                    } else {
                        Text("Sign Out")
                    }
                }
                .controlSize(.small)
                .disabled(isSigningOut)
            }

            HStack {
                Spacer()
                Button("Quit Notes AI Capture") { NSApp.terminate(nil) }
                    .buttonStyle(.plain)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                Spacer()
            }
        }
        .padding(16)
    }

    private func section(_ title: String, @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title.uppercased())
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.tertiary)
            content()
        }
    }

    private func labeledField(_ label: String, text: Binding<String>) -> some View {
        HStack(spacing: 8) {
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
                .frame(width: 44, alignment: .leading)
            TextField(label, text: text)
                .textFieldStyle(.roundedBorder)
                .font(.caption)
                .labelsHidden()
        }
    }
}
