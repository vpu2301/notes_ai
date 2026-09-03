import SwiftUI

/// The root: connecting → sign-in → the app. Applies the theme choice and
/// refreshes the lists whenever the app comes back to the front.
struct RootView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Group {
            switch app.authState {
            case .restoring:
                VStack(spacing: 10) {
                    ProgressView().controlSize(.small)
                    Text("Connecting…")
                        .font(.dsMeta)
                        .foregroundStyle(DS.muted)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(ZStack { DSWash(); DSDots() })
            case .signedOut:
                ScrollView {
                    SignInView()
                        .dsCard(padding: 22, radius: DS.radiusXl)
                        .padding(.horizontal, DS.gutter)
                        .padding(.top, 48)
                        .padding(.bottom, 32)
                }
                .scrollDismissesKeyboard(.interactively)
                .background(ZStack { DSWash(); DSDots() })
                .sheet(isPresented: $app.settingsPresented) {
                    SettingsView()
                }
            case .signedIn:
                MainView()
            }
        }
        .preferredColorScheme(app.themePref.colorScheme)
        .tint(DS.accentText)
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active, app.authState == .signedIn else { return }
            app.calendar.recheckAccess()
            Task {
                await app.refreshRecents()
                await app.refreshNotes()
                await app.googleCalendar.refresh()
            }
        }
    }
}

/// Signed in: the home page with the pages it opens pushed on top, the
/// capture bar pinned underneath, Settings as a sheet.
struct MainView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel

    var body: some View {
        NavigationStack(path: $app.path) {
            HomeView(calendar: app.calendar, google: app.googleCalendar)
                .navigationDestination(for: Selection.self) { selection in
                    DetailView(selection: selection)
                }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            CaptureBar()
        }
        .sheet(isPresented: $app.settingsPresented) {
            SettingsView()
        }
    }
}

/// What a pushed page shows: the note itself, or the meeting's status
/// while it has no note yet.
private struct DetailView: View {
    @EnvironmentObject private var app: AppState
    let selection: Selection

    var body: some View {
        switch selection {
        case .capture(let jobId):
            if let recent = app.recents.first(where: { $0.jobId == jobId }) {
                if let noteId = recent.noteId {
                    NoteView(capture: recent, noteId: noteId, api: app.api)
                        .id(noteId)
                } else {
                    MeetingStatusView(row: recent)
                }
            } else {
                // Removed from the list while open.
                Color.clear.onAppear { app.goHome() }
            }
        case .note(let noteId):
            NoteView(capture: app.recents.first { $0.noteId == noteId }, noteId: noteId, api: app.api)
                .id(noteId)
        }
    }
}
