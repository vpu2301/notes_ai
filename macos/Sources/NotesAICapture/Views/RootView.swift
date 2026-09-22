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
        .frame(width: 340)
        .background(DS.bg)
    }

    private var header: some View {
        HStack(spacing: 8) {
            DSWordmark(size: 14.5)
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
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
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
                    MeetingTypePicker(height: 24)
                    NewMeetingButton(fill: true, height: 38)
                } else {
                    ActiveCaptureCard(compact: true)
                        .dsCard(padding: 12)
                    // Sprint 34: mark a moment without opening the window —
                    // the lowest-friction way there is to say "this bit".
                    if capture.isRecording { QuickNoteField() }
                }
                if app.recents.isEmpty {
                    MeetingsEmptyState(compact: true)
                } else {
                    // No ScrollView: inside a MenuBarExtra window it collapses to
                    // zero height, and six rows fit without one.
                    MeetingList(compact: true, limit: 6)
                    HStack {
                        Spacer()
                        OpenMainWindowButton {
                            Text("All meetings")
                        }
                        .buttonStyle(DSButtonStyle(kind: .ghost, size: 12, height: 24))
                        .foregroundStyle(DS.accentText)
                    }
                }
            }
            .padding(12)
            .task {
                await app.refreshRecents()
                await app.refreshWorkspaces()
            }
        }
    }
}

/// "Quick note…" in the menu-bar popover.
///
/// One line, Return, gone. It appends to the same `user_notes` the capture
/// window is typing into and is stamped with the moment it was written, so
/// a thought marked from the menu bar anchors to the same passage as one
/// typed in the window. Nothing else in the app is this close to hand
/// during a call, which is exactly when the note is worth the most.
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
