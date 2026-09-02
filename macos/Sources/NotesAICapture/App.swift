import SwiftUI

@main
struct NotesAICaptureApp: App {
    @StateObject private var app = AppState()

    var body: some Scene {
        MenuBarExtra {
            RootView()
                .environmentObject(app)
                .environmentObject(app.capture)
        } label: {
            MenuBarLabel()
                .environmentObject(app.capture)
        }
        .menuBarExtraStyle(.window)
    }
}

/// Menu-bar icon that reflects the capture state.
struct MenuBarLabel: View {
    @EnvironmentObject private var capture: CaptureViewModel

    var body: some View {
        Image(systemName: symbolName)
    }

    private var symbolName: String {
        if capture.isRecording { return "record.circle.fill" }
        if capture.phase.isBusy { return "waveform.circle.fill" }
        return "waveform.circle"
    }
}
