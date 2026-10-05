import SwiftUI

/// The menu-bar popover: one button, the live card, the last few meetings.
struct RootView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel

    var body: some View {
        VStack(spacing: 0) {
            header
            DSDivider()
            content
        }
        .frame(width: 320)
        .background(DS.bg)
    }

    private var header: some View {
        HStack(spacing: 8) {
            DSWordmark(size: 12)
            Spacer()
            if app.authState == .signedIn {
                DSMenu(width: 224) {
                    [
                        .item("Open window", symbol: "macwindow", hint: "⌘⇧N") {
                            NotificationCenter.default.post(name: .openMainWindow, object: nil)
                        },
                        .item("Settings…", symbol: "gearshape", hint: "⌘,") {
                            app.settingsTab = .general
                            app.settingsPresented = true
                            NotificationCenter.default.post(name: .openMainWindow, object: nil)
                        },
                        .item("Connectors…", symbol: "puzzlepiece.extension") { app.showConnectors() },
                        .item("Open web app", symbol: "safari") { app.openWebApp() },
                        .separator,
                        .item("Sign out", symbol: "rectangle.portrait.and.arrow.right", danger: true) {
                            app.requestSignOut()
                        },
                        .item("Quit Notes AI Capture", symbol: "power", hint: "⌘Q") { NSApp.terminate(nil) },
                    ]
                }
            } else {
                Button("Quit") { NSApp.terminate(nil) }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 24))
                    .foregroundStyle(DS.muted)
            }
        }
        .padding(.leading, 14)
        .padding(.trailing, 8)
        .padding(.vertical, 6)
    }

    @ViewBuilder
    private var content: some View {
        switch app.authState {
        case .restoring:
            VStack(spacing: 10) {
                ProgressView().controlSize(.small)
                Text("Connecting…")
                    .font(.dsMeta)
                    .foregroundStyle(DS.muted)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 44)
        case .signedOut:
            SignInView(compact: true)
                .padding(16)
        case .signedIn:
            VStack(alignment: .leading, spacing: 12) {
                if app.reconnecting {
                    ReconnectingBanner()
                        .padding(.horizontal, -12)
                        .padding(.top, -12)
                }
                if case .idle = capture.phase {
                    // The six kinds don't fit across the popover as a pill; a menu keeps it one row.
                    HStack(spacing: 6) {
                        NewMeetingButton(fill: true, height: 32)
                        MeetingTypeMenu()
                    }
                } else {
                    ActiveCaptureCard(compact: true)
                        .dsCard(padding: 12)
                    // Mark a moment without opening the window.
                    if capture.isRecording { QuickNoteField() }
                }
                if app.recents.isEmpty {
                    MeetingsEmptyState(compact: true)
                } else {
                    // No ScrollView: inside a MenuBarExtra window it collapses to zero height.
                    MeetingList(compact: true, limit: 4)
                    OpenMainWindowButton {
                        Text("All meetings")
                    }
                    .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 24))
                    .foregroundStyle(DS.muted)
                }
            }
            .padding(10)
            .task {
                await app.refreshRecents()
                await app.refreshWorkspaces()
            }
        }
    }
}

/// "Quick note…" in the menu-bar popover: one line, Return, gone. Appends to the same `user_notes` the window types into, stamped with the moment written.
struct QuickNoteField: View {
    @EnvironmentObject private var capture: CaptureViewModel
    @State private var line = ""
    @FocusState private var focused: Bool

    var body: some View {
        HStack(spacing: 6) {
            TextField("Quick note…", text: $line)
                .textFieldStyle(.plain)
                .font(.ds(13))
                .focused($focused)
                .onSubmit(add)
                .accessibilityLabel("Quick note")
                .accessibilityHint("Adds a timed line to the meeting note")
            Button(action: add) {
                Image(systemName: "return")
                    .font(.system(size: 11, weight: .semibold))
            }
            .buttonStyle(.plain)
            .foregroundStyle(line.isEmpty ? DS.muted : DS.accentText)
            .disabled(line.isEmpty)
            .help("Add this line to the meeting note")
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(
            RoundedRectangle(cornerRadius: DS.radiusLg, style: .continuous).fill(DS.surface2)
        )
    }

    private func add() {
        let text = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        capture.appendQuickNote(text)
        line = ""
        focused = true
    }
}
