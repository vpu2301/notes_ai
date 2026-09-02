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
                            Task { await app.signOut() }
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
                if case .idle = capture.phase {
                    NewMeetingButton(fill: true, height: 38)
                } else {
                    ActiveCaptureCard(compact: true)
                        .dsCard(padding: 12)
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
            .task { await app.refreshRecents() }
        }
    }
}
