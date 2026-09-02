# Notes AI Capture (macOS)

A SwiftUI **menu-bar** companion app that turns your Mac into an ambient
meeting-capture device for Notes AI — and opens the resulting notes
natively, in a window laid out like the Claude / Codex desktop apps
(sidebar of meetings on the left, the document on the right):

1. Click the waveform icon in the menu bar and press **New meeting** (or
   ⌘N with the window open). Recording starts immediately; type a title
   while the meeting runs if you like. The icon turns into a red record dot
   and the card shows the elapsed time and a live input-level meter.
2. Press **Stop** (⌘.). The audio (16 kHz mono **FLAC**, WAV if FLAC is
   unavailable — the ASR service's MIME allow-list has no `audio/mp4`) is
   uploaded (`POST /asr/jobs` with `diarize` and, by default,
   `language=auto` so the transcript and note come out in the spoken
   language), polled every 3 s, and — once the transcription completes — a
   meeting note is drafted via `POST /v1/notes/from-transcript`. With a
   pinned language the **meeting_notes** template for it is looked up once
   from `GET /templates`; with *Detect* the server picks the template in the
   transcript's language. The card walks through Upload → Transcribe →
   Draft note and ends on **Open note**, which opens the note **in the
   app** (the web app is one menu item away).
3. **The window** (**All meetings**, ⌘⇧N, or clicking a meeting in the
   popover) is a sidebar + page layout. The sidebar has a **search** box
   (the server's full-text search, with synonym expansion), the one button,
   *Home*, and your **spaces** — local folders for notes (＋ to add, ⋯ to
   rename or delete; file a note with *Move to …* in its ⋯ menu). The
   **home page** lists, on a dotted ground: **Upcoming** calendar events
   (EventKit, read-only, asked for once; hover an event for *Start*, which
   begins a meeting with that title), **Meetings** still in flight on this
   Mac, and every **note** in the workspace grouped by day (`GET
   /v1/notes/search`). A note's ⋯ menu has *Open*, *Open in web app*, *Copy
   link*, *Move to <space>* and **Move to trash** (`DELETE /v1/notes/{id}`,
   a soft delete — the note leaves every list, public links stop working).
   Selecting a note shows it as a document: editable title and template
   sections that **autosave** (`PUT /v1/notes/{id}/draft`, 0.9 s debounce,
   save state in the bar, conflict banner on 409), a **Transcript** tab for
   notes captured on this Mac (`GET /asr/jobs/{id}/result`, grouped into
   speaker turns, copyable), and a ⋯ menu with *Open in web app* (⌘⇧O),
   sharing, *Download PDF / Markdown*, *Finalize note* / *Revert to draft*,
   *Amend in web app…*, *Move to …* and *Move to trash*. A meeting without a
   note shows the live card while it is being processed, its failure, or a
   **Create note** button when the transcript finished without a note.
   The look is paper and ink, in the spirit of Granola and Codex: a warm
   off-white ground, ½ pt hairlines instead of shadows, rounded corners,
   **Avenir Next** (bundled with macOS) for all text with the DemiBold cut
   for titles, one black pill button, a muted moss accent for tints and
   links, and a faint dot print behind the home page and sign-in. Dark mode
   is the same palette turned over. Everything lives in `Views/Theme.swift`.
4. Everything else — language (Detect / EN / UK), separate speakers, theme,
   sign out, server addresses — lives in **Settings** (⌘,), a sheet behind
   the account row. Dropdowns (⋯ menus, the account menu, selects) are
   drawn in the app's own style rather than as native NSMenus
   (`Views/Dropdowns.swift`). The last 10 captures are persisted (job ids;
   statuses are re-fetched). While the window is open the app behaves like
   a regular app (Dock icon, ⌘-Tab); it goes back to menu-bar-only when you
   close it. `open "Notes AI Capture.app" --args --window` launches straight
   into it.

Auth is email/password (+ optional one-time code) against
`POST /auth/login`. The HttpOnly refresh cookie lives in URLSession's
default cookie storage; the access token is kept **in memory only** and is
refreshed automatically via `POST /auth/refresh` on 401/expiry. Only the
backend URLs and your email are persisted (UserDefaults) — never the
password or tokens.

## Dev sign-in (local stack after `make seed`)

| Email                     | Password       |
| ------------------------- | -------------- |
| `member@tenant-a.example` | `dev-password` |

Default backends (editable in the app's Settings tab):
auth `http://localhost:8000`, ASR `http://localhost:8001`,
notes `http://localhost:8006`, web app `http://localhost:5173`.

## Run path 1 — headless dev build (no Xcode project needed)

```sh
cd macos
swift build            # compiles the SPM executable
swift run              # runs the menu-bar app from your terminal
```

**Microphone permission:** a bare SPM executable has no app bundle and no
Info.plist, so macOS attributes the microphone access to the **terminal**
you launched it from. Grant your terminal mic access (System Settings →
Privacy & Security → Microphone) — the app then inherits it. This is fine
for development; for a real app identity use run path 2.

## Run path 1b — a proper .app without Xcode (`scripts/make-app.sh`)

```sh
cd macos
scripts/make-app.sh              # or: scripts/make-app.sh release
open ".build/Notes AI Capture.app"
```

Wraps the SPM binary in a signed bundle using `Support/Info.plist`, so the
app gets its own bundle id (`ai.notes.capture`), no Dock icon, and its own
microphone prompt — no XcodeGen or `.xcodeproj` needed. The menu-bar icon is
a small waveform-in-a-circle near the right end of the menu bar.

**Signing and the microphone permission.** macOS ties a privacy grant to
the app's code-signing *designated requirement*. An ad-hoc signature has
nothing stable to key on, so every rebuild looked like a new app and the
microphone grant was silently dropped ("not allowed", no prompt). The
script therefore signs with a persistent self-signed identity, **Notes AI
Capture Dev**, which `scripts/make-signing-identity.sh` creates in your
login keychain the first time (it may ask for your password to trust the
certificate for code signing). With that, the grant survives rebuilds; you
allow the microphone once. Set `NOTES_AI_SIGN_IDENTITY` to use another
identity (e.g. an Apple Development certificate). If the grant ever gets
stuck, `tccutil reset Microphone ai.notes.capture` makes macOS prompt again,
and the app's card offers an **Open System Settings** shortcut when access
is off.

## Run path 2 — a proper .app via XcodeGen

```sh
brew install xcodegen
cd macos
xcodegen
open NotesAICapture.xcodeproj
```

`project.yml` defines an app target that uses `Support/Info.plist`
(`NSMicrophoneUsageDescription` for the mic prompt,
`NSCalendarsFullAccessUsageDescription` for the home page's Upcoming list,
`LSUIElement` so the app is menu-bar-only with no Dock icon) and
`Support/NotesAICapture.entitlements` (sandbox + network client +
audio input + calendars). Without the bundle (`swift run`) the calendar
section is simply hidden. Build & run from Xcode; macOS will show the standard
microphone consent prompt on first recording.

## Layout

```
macos/
├── Package.swift                    # SPM executable (swift build / swift run)
├── scripts/make-app.sh              # SPM binary → signed .app bundle
├── scripts/make-signing-identity.sh # one-time self-signed code-signing identity
├── project.yml                      # XcodeGen spec for the .app bundle
├── Support/
│   ├── Info.plist                   # LSUIElement, NSMicrophoneUsageDescription
│   └── NotesAICapture.entitlements
└── Sources/NotesAICapture/
    ├── App.swift                    # @main MenuBarExtra scene + dynamic icon
    ├── Models.swift                 # API DTOs, settings, problem parsing
    ├── APIClient.swift              # async URLSession, multipart, refresh-once
    ├── Recorder.swift               # AVAudioRecorder + metering
    ├── AppState.swift               # auth/settings/recents/selection/template cache
    ├── CaptureViewModel.swift       # record → upload → poll → note pipeline
    ├── NoteViewModel.swift          # one open note: load, autosave, finalize, transcript, PDF
    ├── CalendarService.swift        # EventKit: upcoming events for the home page
    └── Views/
        ├── Theme.swift              # design tokens, button/field/toggle/pill styles
        ├── Dropdowns.swift          # styled ⋯ menus (DSMenu) and select fields (DSSelect)
        ├── Components.swift         # status chip, level meter, pipeline stepper, skeleton
        ├── CaptureView.swift        # ActiveCaptureCard + NewMeetingButton
        ├── RecentsView.swift        # popover rows / list (grouped by day)
        ├── RootView.swift           # menu-bar popover
        ├── MainWindowView.swift     # window: sidebar + detail (note / status / home)
        ├── Sidebar.swift            # search, one button, Home, spaces, account row
        ├── HomeView.swift           # upcoming events, meetings in flight, notes by day
        ├── NoteView.swift           # the note as a document: sections, transcript, ⋯
        └── SettingsView / SignInView
```

Requires macOS 14 (Sonoma) or later. No third-party dependencies.
