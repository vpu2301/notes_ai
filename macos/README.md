# Notes AI Capture (macOS)

A small SwiftUI **menu-bar** companion app that turns your Mac into an
ambient meeting-capture device for Notes AI:

1. Click the waveform icon in the menu bar, type a meeting title, pick the
   language (English / Українська), leave **Separate speakers** on, and hit
   the big record button. The icon turns into a red record dot while
   recording; the popover shows the elapsed time and a live input-level meter.
2. On stop, the audio (`.m4a`) is uploaded to the ASR service
   (`POST /asr/jobs` with `diarize`), polled every 3 s, and — once the
   transcription completes — a meeting note is drafted via
   `POST /v1/notes/from-transcript` using the **meeting_notes** template
   (looked up once from `GET /templates` and cached).
3. **Open note** launches `<web app URL>/notes/<id>` in your browser.
4. The **Recent** tab keeps your last 10 captures (job ids are persisted;
   statuses are re-fetched), each with a status chip and an open-note button.

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

## Run path 2 — a proper .app via XcodeGen

```sh
brew install xcodegen
cd macos
xcodegen
open NotesAICapture.xcodeproj
```

`project.yml` defines an app target that uses `Support/Info.plist`
(`NSMicrophoneUsageDescription` for the mic prompt, `LSUIElement` so the
app is menu-bar-only with no Dock icon) and
`Support/NotesAICapture.entitlements` (sandbox + network client +
audio input). Build & run from Xcode; macOS will show the standard
microphone consent prompt on first recording.

## Layout

```
macos/
├── Package.swift                    # SPM executable (swift build / swift run)
├── project.yml                      # XcodeGen spec for the .app bundle
├── Support/
│   ├── Info.plist                   # LSUIElement, NSMicrophoneUsageDescription
│   └── NotesAICapture.entitlements
└── Sources/NotesAICapture/
    ├── App.swift                    # @main MenuBarExtra scene + dynamic icon
    ├── Models.swift                 # API DTOs, settings, problem parsing
    ├── APIClient.swift              # async URLSession, multipart, refresh-once
    ├── Recorder.swift               # AVAudioRecorder + metering
    ├── AppState.swift               # auth/settings/recents/template cache
    ├── CaptureViewModel.swift       # record → upload → poll → note pipeline
    └── Views/                       # SignIn, Capture, Recents, Settings, components
```

Requires macOS 14 (Sonoma) or later. No third-party dependencies.
