import SwiftUI

@main
struct NotesAICaptureApp: App {
    @StateObject private var app = AppState()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(app)
                .environmentObject(app.capture)
        }
    }
}
