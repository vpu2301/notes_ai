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
            case .locked:
                LockedView()
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
        .sheet(item: $app.reauth) { prompt in
            ReauthSheet(prompt: prompt)
        }
        .onOpenURL { url in app.handle(url) }
        .preferredColorScheme(app.themePref.colorScheme)
        .tint(DS.accentText)
        .onChange(of: scenePhase) { _, phase in
            // Coming back to a locked app asks for the face again; coming
            // back to an unchecked session (the phone was asleep on a
            // train) tries the server once more.
            if phase == .active, app.authState == .locked {
                Task { await app.unlock() }
            }
            guard phase == .active, app.authState == .signedIn else { return }
            if app.reconnecting { Task { await app.reconnect() } }
            app.calendar.recheckAccess()
            // A recording kept while the app was away, and a membership
            // removed while it was away, are both only discoverable here.
            app.refreshPending()
            Task {
                await app.refreshWorkspaces()
                await app.refreshRecents()
                await app.refreshNotes()
                await app.refreshSpaces()
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
        .safeAreaInset(edge: .top, spacing: 0) {
            if app.reconnecting { ReconnectingBanner() }
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
