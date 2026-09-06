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
3. **Home** is a greeting, your **spaces** as chips (your own folders for
   notes, kept on the server so the Mac shows the same ones; ＋ adds one,
   hold a chip to rename or delete), then on a dotted
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
   addresses, **Account** (see below), and **Connectors**:
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

## Signing in (IDX-I1, IOS-1)

Sign-in is an address and a six-digit code from the mail — the same path
signs you up and signs you in, and the server never says which of the two
just happened. A password screen is one link away for accounts that have
one, a second factor and a welcome step appear only when the server asks
for them, and *Forgot?* opens the web app.

**Two kinds of session, side by side.** For the duration of the
dual-issuer period ([ADR-0047](../docs/adr/0047-dual-issuer-period.md)) an
email code gets you a **native** session minted by auth-service, and a
password gets you a **Keycloak** one. Both are refresh tokens this phone
holds in the same Keychain item and presents in a request body — even the
Keycloak login hands a native client its token rather than setting a
cookie, because the app sends `X-Client-Type: ios`
(`routers/login.py:243`). What tells them apart is the token's own `nrt_`
prefix, which is also what the server routes `/auth/refresh` on, and the
app stores it as `kind` so the two can never disagree.

| Step | What it asks | Endpoint |
| --- | --- | --- |
| Create one | out to `<web app>/signup` in Safari — signup is a web flow (BE-0) and stays one | — |
| Email | your address | `POST /auth/email/start` |
| Code | six digits, pasted or typed; resend counts down from the server's `resend_after` | `POST /auth/email/verify` |
| Password *(optional path)* | the password for that address, or Face ID over the one saved on this phone | `POST /auth/login` — 404 on a server without the native password grant, and the app quietly goes back to the code |
| Second factor | authenticator code or a recovery code | `POST /auth/mfa/verify` |
| Welcome | your display name, skippable | `PATCH /auth/me` |

An account made through the web signup lands unconfirmed, and `/auth/login`
refuses it with `403 email_not_verified` until the link in its mail is
followed. That is the one auth answer this app treats as information
rather than as a refusal: the notice turns from red to blue, says what is
owed, and offers **Resend the confirmation email**
(`POST /auth/signup/resend`). Nothing else about a BE-0 account is
special — it signs in with `/auth/login` like a seeded user, and the saved
password works for it as for anyone else.

What is kept where:

* the **refresh token** is in the Keychain (`ai.notes.capture.session`,
  device-only, after-first-unlock so an upload that finishes while the
  phone is locked can still refresh). It travels in the **body** of
  `POST /auth/refresh` and comes back rotated;
* the **access token** is in memory only, refreshed once per 401 and
  before a long upload (single-flight — two requests carrying one refresh
  token is exactly what the server's replay detection is looking for);
* the **saved password** (`ai.notes.capture.credentials`, behind
  `.biometryCurrentSet`) is kept for Keycloak accounts and only for those.
  IDX-I1 deleted this vault; IOS-1 brought it back for the dual period,
  because during it a password is still how every pre-existing user signs
  in and taking it away in the release that adds email codes would be a
  regression for them and a benefit to nobody. IDX-A4/A5 deletes it, by
  changing one default in `SessionMigration`. A native session never
  writes one;
* the **keepalive** runs for Keycloak sessions and only for those. A
  Keycloak refresh token dies after the realm's thirty idle minutes, so
  without it a long meeting ends with a recording and no session to upload
  it with; a native one idles for thirty days
  (`AUTH_REFRESH_TTL_SECONDS`), and waking the phone every quarter of an
  hour to prove that would cost battery for nothing. Either way an upload
  refreshes once just before it starts;
* the Keycloak **refresh cookie** is deleted on the first launch after the
  update. Nothing has read it since IDX-I1, and a credential nothing reads
  is one nobody rotates.

**Switching workspace is native-only** for the duration: `POST /auth/token`
re-mints an access token for another `tid`, and auth-service cannot re-mint
a Keycloak token without Keycloak's key (`409 legacy_session`, recorded up
front in ADR-0047). The switcher is disabled with the reason on screen
rather than left to fail on tap.

**Require Face ID to open** is built and tested but **not offered in this
batch** (`AppState.gateOffered`). It seals the refresh token with AES-GCM
under a random key in its own Keychain item — `.biometryCurrentSet`,
passcode-set-only accessibility — so a cold start asks for your face before
anything carrying a token leaves the phone, and re-enrolling Face ID
destroys the key and the session with it. It is a native-session
capability: a Keycloak refresh token has nothing this app can seal, and a
toggle that works for half the user base is worse than one that is not
there yet. It comes back with I1-05, once A4/A5 has made every session
native.

## Workspaces, and recordings that are waiting (IDX-I2)

One account can be in several **workspaces** — an agency and each of its
clients, a consultant and their own company. The app shows one at a time:
the name is a chip at the top of Home, and tapping it switches (`POST
/auth/token`, which re-reads the membership before it mints anything).
Everything follows: notes, spaces, the search, and this phone's own list of
meetings.

That list is kept per identity **and** per workspace
(`recentCaptures.<identity>.<tenant>` in UserDefaults), so switching never
shows another workspace's meetings and handing the phone to a colleague
never shows them yours. The meetings this app remembered before the update
move to the first account that signs in, once. Settings › Account lists
what other accounts have left here and removes it on request — never
automatically.

**Recordings waiting** is the section at the top of Home. A recording that
could not be uploaded is never deleted; it sits in
`<Application Support>/pending/` (written
`.completeUntilFirstUserAuthentication`, so an upload still running as the
phone locks does not fail) with a sidecar saying what it was, who made it
and which workspace it was for. Each row offers:

* **Retry** — uploads with a token for *its* workspace, not whichever is
  open. The file is deleted only once the server has a job for it.
* **Export** — the system share sheet, so a recording can leave the phone
  even when there is no workspace left to send it to.
* **Delete** — behind a confirmation. The only path in this app that
  destroys a recording.
* **Send to <workspace>** — for a recording made for a workspace you have
  since been removed from. The client never uploads to a workspace it
  already knows it left.

Retries run in the foreground: there is no background `URLSession` in this
app (that is IOS-S1 in the Foundation pack), so nothing uploads while
Notes AI is not on screen, and the section says so.

If a membership is removed while the app is open, the next
`GET /tenants` — on foreground activation, at most once every five minutes,
or immediately after a 403 — says so with a banner offering the workspaces
you are still in. Nothing local is deleted; a network failure never drops a
membership.

Settings › **Account** is the rest: your display name (`PATCH /auth/me`),
your workspaces, the Face ID gate, where you are signed in
(`GET /auth/sessions`, end one, or "sign out everywhere else" — which asks
you to confirm it is you), a link out to the web app for passwords and
two-factor, what this phone is holding, and signing out (which warns first
if recordings are waiting).

**Invitation links are not built.** `notesai://invite/<token>` is
recognised and answered with an explanation, and there is no Associated
Domains entitlement or AASA file, because invitations have no server:
no table in any migration, no router in auth-service, no `/invite/:token`
page in the web app. IDX-W1 and IDX-W2 recorded the same gate. When IDX-B1
lands, what is missing here is the preview sheet.

A release build talks **https only** (`NSAllowsArbitraryLoads` is false, and
the local-networking exception exists in Debug alone).

## Dev sign-in (local stack after `make seed`)

| Email                     | Password       |
| ------------------------- | -------------- |
| `member@tenant-a.example` | `dev-password` |

With `MDX_IDP_MODE=native` there is no password grant at all: sign in with
the emailed code (the dev stack prints it in the auth-service log).

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

The **Debug** configuration allows plain http (`Support/Config/Debug.xcconfig`
→ `NSAllowsArbitraryLoads`); Release does not, and `scripts/check-ats.sh`
fails the build if that ever changes. Two things stay Mac-only with this setup:
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
ios/scripts/build-sim.sh Release
ios/scripts/check-ats.sh        # asserts the Release build allows no plain http
ios/scripts/test.sh             # the unit tests — BOOTS A SIMULATOR
```

The end-to-end smoke (IOS-0) needs a running stack and is opt-in at both
ends, so nothing here fails on a laptop with nothing up:

```sh
make dev-up
make smoke-ios                                       # the API half
NOTES_STACK_HOST=localhost ios/scripts/test.sh       # the app half (LiveStackTests)
```

It is not run by CI, for the same reason `make web-e2e` is not: the stack
includes an asr-worker that bakes whisper-large-v3 (2.7 GiB), and the iOS
job runs on a macOS runner with no Docker. Both halves are *compiled* on
every push, so they cannot rot while they wait. Set the repository
variable `NOTES_STACK_HOST` to a reachable stack and the job runs them.

## Layout

```
ios/
├── NotesAICapture.xcodeproj/        # hand-written project + shared scheme
├── Support/Info.plist               # mic + Face ID + calendar usage, notesai://
│                                    #   scheme, audio background mode, ATS (#if DEV_HTTP)
├── Support/Config/*.xcconfig        # the Debug/Release split behind that #if
├── Tests/NotesAICaptureTests/       # session, dual-issuer, signup, gate, transport, capture safety, copy
│                                    #   + LiveStackTests (opt-in, real stack)
├── scripts/check.sh                 # swiftc compile check (no simulator needed)
├── scripts/build-sim.sh             # xcodebuild → build/…/NotesAICapture.app
├── scripts/check-ats.sh             # Release ATS assertion (IDX-I1)
├── scripts/test.sh                  # xcodebuild test (boots a simulator)
└── Sources/NotesAICapture/
    ├── App.swift                    # @main WindowGroup
    ├── Models.swift                 # API DTOs, settings, problem parsing (as on the Mac)
    ├── APIClient.swift              # async URLSession, multipart, refresh-once (as on the Mac)
    ├── Recorder.swift               # AVAudioEngine + AVAudioSession, interruptions, FLAC
    ├── AppState.swift               # auth/settings/recents/spaces + the navigation path
    ├── SessionStore.swift           # the Keychain session, `SessionKind`, the gate, the migration
    ├── Credentials.swift            # the saved password — Keycloak accounts only, during `dual`
    ├── AuthCopy.swift               # one error code → one sentence
    ├── PendingCaptures.swift        # recordings that did not reach the server
    ├── LocalStore.swift             # per-identity, per-workspace UserDefaults keys
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
        ├── ReauthSheet.swift        # step-up sheet + the reconnecting banner
        ├── WorkspaceView.swift      # the workspace chip and the switcher sheet
        ├── PendingUploadsView.swift # recordings waiting: retry / export / delete / re-target
        ├── AccountView.swift        # profile, workspaces, sessions, local data, sign out
        └── SignInView.swift         # email → code → password → MFA → welcome, and LockedView
```

Requires iOS 17 or later. No third-party dependencies.
