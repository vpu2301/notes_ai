import SwiftUI

/// The root: connecting → sign-in → the app. Applies the theme; refreshes on foreground.
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
            // Locked: ask for the face again; unchecked session: try the server once more.
            if phase == .active, app.authState == .locked {
                Task { await app.unlock() }
            }
            guard phase == .active, app.authState == .signedIn else { return }
            if app.reconnecting { Task { await app.reconnect() } }
            app.calendar.recheckAccess()
            // A kept recording and a removed membership are only discoverable here.
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

/// Signed in: the home page and its pushed pages, the capture bar, Settings as a sheet.
struct MainView: View {
    @EnvironmentObject private var app: AppState
    @EnvironmentObject private var capture: CaptureViewModel
    @Environment(\.scenePhase) private var scenePhase

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
        .sheet(isPresented: $app.invitePresented) {
            InviteView { app.invitePresented = false }
        }
        .sheet(isPresented: $app.newNotePresented) {
            NewNoteSheet { app.newNotePresented = false }
        }
        .sheet(isPresented: $app.notificationsPresented) {
            NotificationsSheet(model: app.notifications) { app.notificationsPresented = false }
        }
        // The bell's count, every half minute while the app is in front.
        .task(id: scenePhase) {
            guard scenePhase == .active else { return }
            await app.notifications.poll()
        }
    }
}

/// What a pushed page shows: the note, or the meeting's status while it has none.
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
