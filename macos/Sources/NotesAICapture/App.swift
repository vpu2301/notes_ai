import AppKit
import SwiftUI

@main
struct NotesAICaptureApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
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

        // Full-size window for managing captures; opened on demand from the
        // popover (or ⌘⇧N while the app is frontmost). Never opened at launch.
        Window("Notes AI Capture", id: MainWindow.id) {
            MainWindowView()
                .environmentObject(app)
                .environmentObject(app.capture)
        }
        .defaultSize(width: 1040, height: 680)
        .windowResizability(.contentMinSize)
        .windowStyle(.hiddenTitleBar)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New Meeting") { app.capture.startNew() }
                    .keyboardShortcut("n", modifiers: .command)
                OpenMainWindowButton(title: "Open Window")
                    .keyboardShortcut("n", modifiers: [.command, .shift])
                Button("Open Note in Web App") {
                    if let noteId = app.selectedNoteId { app.openNoteInBrowser(noteId) }
                }
                .keyboardShortcut("o", modifiers: [.command, .shift])
                .disabled(app.selectedNoteId == nil)
            }
            CommandGroup(replacing: .appSettings) {
                Button("Settings…") {
                    app.settingsTab = .general
                    app.settingsPresented = true
                    NotificationCenter.default.post(name: .openMainWindow, object: nil)
                }
                .keyboardShortcut(",", modifiers: .command)
            }
        }
    }
}

enum MainWindow {
    static let id = "main"
}

/// The app is menu-bar-only until the main window is shown, at which point
/// it becomes a regular app (Dock icon, ⌘-Tab, menu bar) and reverts once
/// the window closes.
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // `swift run` has no Info.plist (no LSUIElement), so enforce it here
        // too — this also keeps the Window scene from opening at launch.
        NSApp.setActivationPolicy(.accessory)
        // `open "Notes AI Capture.app" --args --window` starts straight into
        // the full window.
        if CommandLine.arguments.contains("--window") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                NotificationCenter.default.post(name: .openMainWindow, object: nil)
            }
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        // Clicking the Dock icon with no window showing reopens the window.
        if !hasVisibleWindows {
            NotificationCenter.default.post(name: .openMainWindow, object: nil)
        }
        return true
    }
}

extension Notification.Name {
    /// Ask the (always-alive) menu-bar label to open the main window; used
    /// where no SwiftUI `openWindow` environment is available.
    static let openMainWindow = Notification.Name("NotesAICapture.openMainWindow")
}

/// Opens (or focuses) the main window and brings the app forward.
struct OpenMainWindowButton<Label: View>: View {
    @Environment(\.openWindow) private var openWindow
    private let label: () -> Label

    init(@ViewBuilder label: @escaping () -> Label) {
        self.label = label
    }

    var body: some View {
        Button(action: open, label: label)
    }

    private func open() {
        NSApp.setActivationPolicy(.regular)
        openWindow(id: MainWindow.id)
        NSApp.activate(ignoringOtherApps: true)
    }
}

extension OpenMainWindowButton where Label == Text {
    init(title: String) {
        self.init { Text(title) }
    }
}

/// Menu-bar icon that reflects the capture state.
struct MenuBarLabel: View {
    @EnvironmentObject private var capture: CaptureViewModel
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Image(systemName: symbolName)
            .onReceive(NotificationCenter.default.publisher(for: .openMainWindow)) { _ in
                NSApp.setActivationPolicy(.regular)
                openWindow(id: MainWindow.id)
                NSApp.activate(ignoringOtherApps: true)
            }
    }

    private var symbolName: String {
        if capture.isRecording { return "record.circle.fill" }
        if capture.phase.isBusy { return "waveform.circle.fill" }
        return "waveform.circle"
    }
}
