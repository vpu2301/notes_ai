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

        // Full-size window, opened on demand from the popover (or ⌘⇧N). Never opened at launch.
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
            CommandGroup(after: .sidebar) {
                Button(app.sidebarCollapsed ? "Expand Sidebar" : "Collapse Sidebar") {
                    app.toggleSidebar()
                }
                .keyboardShortcut("s", modifiers: [.command, .control])
            }
            CommandGroup(after: .appInfo) {
                Button("Invite People…") { app.showInvite() }
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

/// Menu-bar-only until the main window is shown; then a regular app (Dock icon, ⌘-Tab), reverting when the window closes.
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        // `notesai://` links clicked outside the app. SwiftUI's `onOpenURL` needs a scene on screen; the Apple Event is delivered regardless.
        NSAppleEventManager.shared().setEventHandler(
            self,
            andSelector: #selector(handleURLEvent(_:withReply:)),
            forEventClass: AEEventClass(kInternetEventClass),
            andEventID: AEEventID(kAEGetURL))
        // `swift run` has no Info.plist (no LSUIElement), so enforce it here too; also keeps the Window scene from opening at launch.
        NSApp.setActivationPolicy(.accessory)
        // An aggregate device a crashed run left behind. Only lists devices — no permission asked.
        if #available(macOS 14.2, *) {
            DispatchQueue.global(qos: .utility).async { SystemAudioTap.removeOrphanAggregateDevices() }
        }
        // `--args --window` starts straight into the full window.
        if CommandLine.arguments.contains("--window") {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                NotificationCenter.default.post(name: .openMainWindow, object: nil)
            }
        }
    }

    @objc private func handleURLEvent(_ event: NSAppleEventDescriptor,
                                      withReply reply: NSAppleEventDescriptor) {
        guard let string = event.paramDescriptor(forKeyword: keyDirectObject)?.stringValue,
              let url = URL(string: string)
        else { return }
        NotificationCenter.default.post(name: .openAppURL, object: url)
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
    /// Ask the (always-alive) menu-bar label to open the main window where no `openWindow` environment exists.
    static let openMainWindow = Notification.Name("NotesAICapture.openMainWindow")
    /// A `notesai://` URL arrived from outside the app; the object is the URL.
    static let openAppURL = Notification.Name("NotesAICapture.openAppURL")
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
        icon
            // The desktop disc lives exactly as long as the recording.
            .onChange(of: capture.isRecording, initial: true) { _, recording in
                if recording { RecordingBubble.shared.show(capture: capture) } else { RecordingBubble.shared.hide() }
            }
            .onReceive(NotificationCenter.default.publisher(for: .openMainWindow)) { _ in
                NSApp.setActivationPolicy(.regular)
                openWindow(id: MainWindow.id)
                NSApp.activate(ignoringOtherApps: true)
            }
    }

    /// While call audio is recorded too, the record symbol carries a small headphones badge.
    @ViewBuilder
    private var icon: some View {
        if capture.isRecording, capture.recorder.captureMode.recordsSystemAudio,
           let badged = Self.callAudioBadge {
            Image(nsImage: badged)
                .accessibilityLabel("Recording with call audio")
        } else {
            Image(systemName: symbolName)
        }
    }

    /// "record.circle.fill" with "headphones" drawn small at its lower right, as one template image.
    private static let callAudioBadge: NSImage? = {
        let config = NSImage.SymbolConfiguration(pointSize: 14, weight: .regular)
        guard let base = NSImage(systemSymbolName: "record.circle.fill", accessibilityDescription: nil)?
                .withSymbolConfiguration(config),
              let badge = NSImage(systemSymbolName: "headphones", accessibilityDescription: nil)?
                .withSymbolConfiguration(NSImage.SymbolConfiguration(pointSize: 8, weight: .bold))
        else { return nil }
        let size = NSSize(width: base.size.width + 6, height: base.size.height)
        let image = NSImage(size: size, flipped: false) { _ in
            base.draw(in: NSRect(x: 0, y: size.height - base.size.height,
                                 width: base.size.width, height: base.size.height))
            badge.draw(in: NSRect(x: size.width - badge.size.width, y: 0,
                                  width: badge.size.width, height: badge.size.height))
            return true
        }
        image.isTemplate = true
        image.accessibilityDescription = "Recording with call audio"
        return image
    }()

    private var symbolName: String {
        if capture.isRecording { return "record.circle.fill" }
        if capture.phase.isBusy { return "waveform.circle.fill" }
        return "waveform.circle"
    }
}
