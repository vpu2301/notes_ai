# Notes AI (iOS)

The iPhone counterpart of the Mac capture app: a SwiftUI app that turns
your phone into an ambient meeting-capture device for Notes AI and opens the
resulting notes natively. Same backends, same look (paper and ink, Avenir
Next, hairlines, one black pill button), same data as the web app and the
Mac app — a note captured here shows up there and the other way round.

1. Tap **New meeting** (the pill pinned to the bottom of every screen).
   Recording starts immediately; type a title while the meeting runs if you
   like. The card shows the elapsed time and a live input-level meter.
   Swipe it down (or tap the chevron) to fold it to one line — timer and
   Stop — and swipe up to get the whole card back; it unfolds by itself
   when the note is ready or something fails. The recording keeps going
   when the phone is locked or another app is in front (the `audio`
   background mode); a phone call pauses it and it resumes when the call
   ends.
2. Tap **Stop**. The audio (16 kHz mono **FLAC**, WAV if FLAC is
   unavailable) is uploaded (`POST /asr/jobs` with `diarize` and, by default,
   `language=auto`), polled every 3 s, and — once the transcription
   completes — a meeting note is drafted via `POST /v1/notes/from-transcript`.
   The bar walks through Upload → Transcribe → Draft note and ends on
   **Open note**.
3. **Home** is a greeting, your **spaces** as chips (local folders for
   notes; ＋ adds one, hold a chip to rename or delete), then on a dotted
   ground: **Coming up** calendar events (a mic button starts a meeting with
   the event's title, a video button joins the call), **Meetings** still in
   flight on this phone, and every **note** in the workspace grouped by day
   (`GET /v1/notes/search`, pull down to refresh). The search box in the
   navigation bar runs the server's full-text search. A note's ⋯ menu (or a
   long press) has *Open*, *Open in web app*, *Copy link*, *Move to <space>*
   and *Move to trash*.
4. **A note** is a page: editable title and template sections that
   **autosave** (`PUT /v1/notes/{id}/draft`, 0.9 s debounce, save state in
   the bar, conflict banner on 409), a **Transcript** tab for notes captured
   on this phone (speaker turns; tap a name to rename the speaker on the
   job so the web app agrees), and a ⋯ menu with *Open in web app*,
   sharing (workspace visibility, public link, e-mail, share with a
   colleague), *Share PDF / Markdown* (the system share sheet: Files, Mail,
   AirDrop…), *Finalize note* / *Revert to draft*, *Amend in web app…*,
   *Move to …* and *Move to trash*.
5. Everything else lives in **Settings** (the avatar in the top-right):
   language (Auto / EN / UK / DE), separate speakers, theme, server
   addresses, sign out, and **Connectors**:
   - **Google Calendar & calendar links** — connected on the server
     (note-service `/v1/calendar`), so the same account feeds the web app
     and the Mac app. Google sign-in opens in an in-app browser sheet
     (`ASWebAuthenticationSession`) and comes back on `notesai://`. A
     private iCal address works without any Google client id.
   - **This phone's calendars** — EventKit, read-only, asked for once; pick
     which calendars feed Coming up.
   - **MCP connectors** — HubSpot, Notion, Linear, Atlassian or any custom
     Streamable-HTTP MCP server. *Connect* runs the `initialize` handshake
     and lists the server's tools; a 401 starts the OAuth flow (resource
     metadata → server metadata → dynamic client registration → PKCE in a
     browser sheet). Tokens live in the Keychain. Unlike the Mac there is no
     `localhost` loopback redirect (a backgrounded phone app cannot answer
     it), so a server that does not register apps itself needs an app on
     its side whose redirect URL is `notesai://oauth/callback`.

Auth is email/password (+ optional one-time code) against
`POST /auth/login`. Leave **Save password for Face ID** on and the
password is kept in the Keychain behind Face ID / Touch ID
(`.biometryCurrentSet`, this device only): the next time the session has
lapsed, the sign-in screen asks for your face and signs you in. A password
that stops working is forgotten again; Settings › Account has **Forget**. The HttpOnly refresh cookie lives in URLSession's
cookie storage; the access token is kept **in memory only** and is
refreshed automatically (single-flight, with a keepalive a minute before
expiry). Only the backend URLs and your email are persisted.

## Dev sign-in (local stack after `make seed`)

| Email                     | Password       |
| ------------------------- | -------------- |
| `member@tenant-a.example` | `dev-password` |

Default backends: auth `http://localhost:8000`, ASR `http://localhost:8001`,
notes `http://localhost:8006`, web app `http://localhost:5173`. `localhost`
is right on the **simulator**. On a **phone** it is the phone itself, so:

1. Publish the dev stack on the Mac's network interface — Docker binds
   every service to `127.0.0.1` by default. In the repo's `.env` set
   `PUBLISH_HOST=0.0.0.0`, then
   `docker compose up -d auth-service asr-service note-service`.
2. In the app, Settings › **Server**, enter the Mac's Wi‑Fi address
   (System Settings › Wi‑Fi › Details; e.g. `192.168.1.20`) and tap **Use** —
   all four addresses follow. The sign-in form says so itself when it
   cannot connect and the addresses still say localhost.
3. Allow the **Local Network** prompt the first time; iOS asks before an app
   may talk to addresses on your Wi‑Fi.

`Info.plist` allows plain http for development (`NSAllowsArbitraryLoads`) —
tighten it for a real build. Two things stay Mac-only with this setup:
*Open in web app* needs the Vite dev server on the LAN too (`npm run dev --
--host`, plus that origin in the services' CORS lists), and connecting
Google Calendar from the phone needs `GOOGLE_CALENDAR_REDIRECT_URI` to use
the Mac's address rather than localhost (and the same URI in Google's
console); a calendar **link** works from the phone as is.

## Build & run

```sh
open ios/NotesAICapture.xcodeproj      # then ⌘R on a simulator or your phone
```

The project is committed (no XcodeGen needed) in Xcode 16's
synchronized-folder format: everything under `Sources/NotesAICapture` is
part of the target automatically. It needs Xcode with the **iOS platform
installed** (Xcode › Settings › Components, or
`xcodebuild -downloadPlatform iOS`). To run on a phone, set your team under
Signing & Capabilities once. Bundle id `ai.notes.capture.ios`, iOS 17+.

Without a simulator runtime you can still compile everything:

```sh
ios/scripts/check.sh            # whole-module compile against the iOS SDK
ios/scripts/check.sh --quick    # type-check only
ios/scripts/build-sim.sh        # xcodebuild for the simulator (platform needed)
```

## Layout

```
ios/
├── NotesAICapture.xcodeproj/        # hand-written project + shared scheme
├── Support/Info.plist               # mic + calendar usage, notesai:// scheme,
│                                    #   audio background mode, ATS for dev http
├── scripts/check.sh                 # swiftc compile check (no simulator needed)
├── scripts/build-sim.sh             # xcodebuild → build/…/NotesAICapture.app
└── Sources/NotesAICapture/
    ├── App.swift                    # @main WindowGroup
    ├── Models.swift                 # API DTOs, settings, problem parsing (as on the Mac)
    ├── APIClient.swift              # async URLSession, multipart, refresh-once (as on the Mac)
    ├── Recorder.swift               # AVAudioEngine + AVAudioSession, interruptions, FLAC
    ├── AppState.swift               # auth/settings/recents/spaces + the navigation path
    ├── CaptureViewModel.swift       # record → upload → poll → note pipeline
    ├── NoteViewModel.swift          # one open note: load, autosave, finalize, transcript, export
    ├── CalendarService.swift        # EventKit: upcoming events, calendar picker
    ├── GoogleCalendarService.swift  # server-side calendar connections (shared with web)
    ├── Connectors/
    │   ├── MCPClient.swift          # MCP over Streamable HTTP: initialize, tools/list
    │   ├── MCPOAuth.swift           # discovery, registration, PKCE, ASWebAuthenticationSession
    │   └── ConnectorStore.swift     # connector list, Keychain tokens, connect/disconnect
    ├── Assets.xcassets/             # app icon
    └── Views/
        ├── Theme.swift              # design tokens (UIColor-dynamic), button/field/toggle styles
        ├── Dropdowns.swift          # DSMenu/DSSelect over the native Menu
        ├── Components.swift         # chips, level meter, pipeline steps, share sheet
        ├── CaptureView.swift        # live card, New meeting button, the bottom CaptureBar
        ├── RootView.swift           # connecting / sign-in / MainView (NavigationStack)
        ├── HomeView.swift           # spaces chips, Coming up, meetings, notes by day
        ├── NoteView.swift           # the note as a document: sections, transcript, ⋯
        ├── MeetingStatusView.swift  # a meeting without a note yet
        ├── SettingsView.swift       # sheet: meetings, appearance, connectors, account, servers
        ├── ConnectorsView.swift     # calendars + MCP servers, link sheet, connector editor
        └── SignInView.swift
```

Requires iOS 17 or later. No third-party dependencies.
