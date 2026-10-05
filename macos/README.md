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
   *Home*, and your **spaces** — your own folders for notes, kept on the
   server (`/v1/spaces`, migration 0021) so the phone shows the same ones
   (＋ to add, ⋯ to rename or delete; file a note with *Move to …* in its
   ⋯ menu). Spaces this Mac kept locally before 0021 are moved up the
   first time it signs in. Two icons sit beside the wordmark: **collapse /
   expand the sidebar** (⌃⌘S — it shrinks to an icon rail wide enough to
   keep the traffic lights inside it, and the choice is remembered) and
   **invite people** (also *Invite people…* in the account menu), a sheet
   that adds a colleague to the workspace by e-mail
   (`POST /tenants/{id}/members`, owners and admins only) and, when the
   address has no account here yet, offers the invite link to copy or
   e-mail plus the current member roster. The
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
   sharing (workspace visibility, public link, and **Send by email…** — a
   sheet that takes addresses and a message and has the SERVER send a
   branded mail; members are granted access, anyone else gets the public
   link), *Download PDF / Markdown*, *Finalize note* / *Revert to draft*,
   *Amend in web app…*, *Move to …* and *Move to trash*. A meeting without a
   note shows the live card while it is being processed, its failure, or a
   **Create note** button when the transcript finished without a note.
   The look is paper and ink, in the spirit of Granola and Codex: a warm
   off-white ground, ½ pt hairlines instead of shadows, rounded corners,
   **Avenir Next** (bundled with macOS) for all text with the DemiBold cut
   for titles, one black pill button, a muted moss accent for tints and
   links, and a faint dot print behind the home page and sign-in. Dark mode
   is the same palette turned over. Everything lives in `Views/Theme.swift`.
4. Everything else — language (Detect / EN / UK / DE), separate speakers, theme,
   sign out, server addresses — lives in **Settings** (⌘,), a sheet behind
   the account row. Its **Connectors** tab (also *Connectors…* in the
   account menu and the popover's ⋯ menu) is where the app is wired to the
   outside:
   - **Calendar** — connect the Mac's calendars (EventKit) and pick which
     ones feed the home page's Upcoming list. Google, Outlook and iCloud
     calendars all arrive through the account added in System Settings ›
     Internet Accounts (one button away). Changes in Calendar.app refresh
     the list live.
   - **MCP connectors** — remote Model Context Protocol servers such as
     HubSpot, Notion, Linear, Atlassian, or any custom URL
     (`Connectors/MCPClient.swift`, Streamable HTTP). *Connect* runs the
     `initialize` handshake and lists the server's tools; a 401 starts the
     MCP OAuth flow (`Connectors/MCPOAuth.swift`: RFC 9728 resource
     metadata → RFC 8414 server metadata → RFC 7591 dynamic client
     registration → PKCE in the browser, callback on the app's
     `notesai://oauth/callback` scheme). Servers that do not register apps
     themselves (HubSpot) take a client ID/secret from an app you create on
     their side, with `http://localhost:52581/callback` as the redirect
     URL; a pasted access token or an open server work too. Tokens and
     secrets live in the login Keychain, never in UserDefaults. The
     connections are per-Mac for now — the backend does not yet consume
     them when drafting notes. Dropdowns (⋯ menus, the account menu, selects) are
   drawn in the app's own style rather than as native NSMenus
   (`Views/Dropdowns.swift`). The last 10 captures are persisted (job ids;
   statuses are re-fetched). While the window is open the app behaves like
   a regular app (Dock icon, ⌘-Tab); it goes back to menu-bar-only when you
   close it. `open "Notes AI Capture.app" --args --window` launches straight
   into it.

## Call audio (Sprint 31)

With headphones on, the other people in an online call never reach the
microphone, so a microphone-only recording has half the meeting. With
**Settings › General › Record call audio (other participants)** on, the
app also records what the Mac plays and uploads a **two-channel** file:
ch0 = your microphone, ch1 = the call audio (16 kHz FLAC, WAV fallback),
with `channel_layout=mic_system` and `local_speaker_name` (your account's
display name) on `POST /asr/jobs`. The server uses the split to tell *you*
from the other side; a speaker named from the channel shows
"· from your microphone" and an ✕ that removes the name.

**How it records** (`SystemAudioTap.swift`, macOS 14.2+): one Core Audio
*process tap* of every process except this app
(`CATapDescription(stereoGlobalTapButExcludeProcesses:)`, private,
unmuted), placed in a **private aggregate device** together with the
default input device, drift compensation on the tap. Microphone and call
audio arrive in one IO callback on one clock, so the channels stay aligned
for the whole meeting. When the default input or output device changes
(AirPods connect) the aggregate device is rebuilt on the new one after a
250 ms settle — a short gap on both channels. The aggregate device
(`ai.notes.capture.aggregate.*`) and the tap are destroyed on Stop; a
device a crashed run left behind is removed at the next launch. On macOS
older than 14.2 the setting has no effect.

**Consent posture.** The setting is **off** by default. Turning it on shows
a blocking notice — what is recorded (other participants' audio from this
Mac), that *you* are responsible for telling participants and getting their
agreement where required, a sentence to say, and a help link
(`CallAudioConsent.helpURL`, currently
`https://notes.ai/help/recording-call-audio` — **that page must exist before
release**). *Accept* turns the setting on; *Not now* keeps recordings
microphone-only. The accepted version is stored on this Mac
(`callAudioConsentVersion`); raising `CallAudioConsent.currentVersion` asks
again, and until it is accepted recordings are microphone-only. While call
audio is recorded, the menu-bar record dot carries a small headphones badge
and the card shows two meters, **You** and **Call audio**.

**Permission.** macOS asks once to allow *System Audio Recording* for Notes
AI Capture (`NSAudioCaptureUsageDescription` in `Support/Info.plist`). It
lives in System Settings › Privacy & Security › **Screen & System Audio
Recording**; the card's **Fix** link opens that pane.

**Troubleshooting.**
- *"Recording your microphone only — call audio permission is off"*: the tap
  could not be created. Click **Fix**, allow Notes AI Capture under System
  Audio Recording, then start a new meeting. `tccutil reset AudioCapture
  ai.notes.capture` should make macOS ask again (service name not yet
  checked on a real machine).
- *Call audio is silent although the card says it is recorded*: when the
  permission is denied macOS may still create the tap and deliver silence —
  the app cannot tell that apart from a quiet call. Check the permission.
- *"Call audio stopped"*: the tap or the aggregate device went away
  mid-meeting (a device change that could not be rebuilt). The recording
  continues from the microphone; ch1 is silence from that point and the
  file is still uploaded as two-channel.
- As with the microphone, the grant is keyed to the code signature — use
  `scripts/make-app.sh` (persistent identity), not ad-hoc signing.

**Not verified on hardware yet** (the app is only built, never launched,
in development by the assistant): that the tap works under App Sandbox
(the XcodeGen build) — no extra entitlement is added, none is documented;
the permission prompt; channel skew < 5 ms over 60 min; CPU < 3 %; the
AirPods rebuild gap. ScreenCaptureKit (audio-only `SCStream`) is the
fallback if the tap fails any of these; it is not built.

## Signing in (IDX-M1)

The default way in is your address and a six-digit code from the mail —
the same path signs you up if you have never used Notes AI here. A
password screen is one link away for accounts that have one, and the
second factor and the "what should we call you" step appear only when the
server says they are owed.

| Step | Endpoint | Notes |
| --- | --- | --- |
| Address → code | `POST /auth/email/start` | 202 for every address, known or not; six digits, good for ten minutes, resend after 60 s |
| Code → session | `POST /auth/email/verify` | Answers a session, or `status: "mfa_required"` |
| Password | `POST /auth/login` | Keycloak-mode deployments only until IDX-A4; a 404 makes the app offer the code instead. "Forgot?" opens `<web app>/reset` in the browser |
| Second factor | `POST /auth/mfa/verify` | Authenticator code, or one of your recovery codes |
| Your name | `PATCH /auth/me` | New accounts only, and skippable — the server has already used the address's local part |
| Renew | `POST /auth/refresh` | Body `{refresh_token}`; rotates on every call |
| Sign out | `POST /auth/logout` | Body `{refresh_token}`; removes the Keychain item |

**Where the session lives.** The refresh token is a generic-password item
in this Mac's login Keychain (service `ai.notes.capture.session`,
device-only, never synchronised to iCloud, readable after the first
unlock). It travels in the **body** of `/auth/refresh` because the app
declares itself with `X-Client-Type: macos`; the app keeps **no cookie
store at all**, and any `mdx_rt` cookie left by an older build is deleted
at launch. The access token is kept in memory only and is renewed once,
on 401 or just before it expires. A **native** session idles for thirty
days, so nothing keeps it warm: an idle Mac makes no requests at all, and
a 45-minute recording costs exactly one refresh at upload time. A
**Keycloak** session — what existing password accounts still get during
the dual-issuer period (ADR-0047) — idles out after thirty minutes, and
that clock belongs to the Keycloak session rather than to the cookie the
token used to arrive in, so moving it into the Keychain did not slow it
down. Those sessions alone are kept warm by a background refresh, armed
off the refresh lifetime the server states rather than off the token's
shape. A rotated token presented twice is a replay: the
server revokes the session, and the app says so ("You were signed out for
security") rather than silently showing a sign-in form. Only the backend
URLs, your email and the recents list are in UserDefaults — never a
password, never a token.

**Signing is what keeps you signed in.** Keychain items are keyed to the
app's code-signing identity, exactly like the microphone grant, so
`scripts/make-app.sh` signs with the persistent **Notes AI Capture Dev**
identity. An ad-hoc signature drops the session on every rebuild.

**A recording is never thrown away.** If the upload fails — the session
ended, the server was unreachable, the app was quit mid-pipeline — the
audio is moved to `~/Library/Application Support/Notes AI Capture/pending/`
with a sidecar JSON (title, language, speakers, when, whose). They appear
as **Not uploaded yet** on the home page, above the notes, with *Send*,
*Export…*, *Show in Finder* and *Delete* (which asks first, because it
removes the only copy). Signing back in sends them automatically, and so
does reconnecting. Nothing in the app deletes one on its own.

## My notes: typing during the meeting (Sprint 34, ADR-0055)

Pressing Record now **opens the note**, before there is any audio. The
capture card carries a scratchpad — the note's own `user_notes` section —
and what you type there is the note from the first second.

What that guarantees, and how:

- **It is saved as you type.** Every change is written to the app's
  protected container within half a second (`PendingMeetingNotes`), and
  autosaved into the note (`PUT /v1/notes/{id}/draft`) about a second
  later. An app kill, a crash or a flat battery costs a sentence at worst.
- **Offline is not a special case.** With no network the recorder starts
  anyway and the note is opened at Stop instead; if that fails too, the
  typing waits on disk and is replayed the next time a workspace loads.
  Creating the note is idempotent on the capture id, so a replay never
  makes a second one.
- **Two devices never overwrite each other.** When the server already has
  different text (you typed on the Mac too), the local lines are
  **appended under a `---` divider**, and lines the server already holds
  are skipped. Nothing you typed is ever replaced by something else.
- **Nothing rewrites your words.** `user_notes` comes back byte-identical
  after the transcript lands. A line the recording cannot support is kept
  and marked, never silently corrected or dropped.
- **Line times, not keystrokes.** The first moment each line appears is
  recorded as `line_key → offset_ms` — a hash and an offset, no content —
  so the document can later say what was being said when you wrote it.
- **Sign-out clears them.** Unsynced scratchpads for the identity signing
  out are deleted (`SignOutCleanup`); another person's on a shared device
  are left alone, and kept *recordings* are never touched.

The menu-bar popover adds **Quick note…** while a recording runs: one
line, Return, and it is appended to the same `user_notes` with the moment
it was written — without opening the window.

## Names and terms: the workspace glossary (Sprint 35)

Renaming a speaker offers, once, to remember the spelling for the
workspace — and only a tap on **Remember** writes anything. The rules for
when it is worth asking live in `RememberableName` and are the same on all
three clients: a name typed over a placeholder or over a different
spelling counts; case, spacing, or clearing a name back to "Speaker 2" do
not, and neither do the invisible characters that make one name render as
another.

The terms are listed under **Settings → Names and terms**, deletable by
whoever added them, and the capture sends them as the upload's
`vocabulary_hint` so the transcriber has the spellings before it guesses.
Fetching the hint never delays a recording: it happens beside
`beginRecording()`, and a failure costs the hint, not the meeting.

## Workspaces (IDX-M2)

The account row at the bottom of the sidebar shows the **workspace** you
are in and switches between them; the same list is in Settings › Account.
Switching calls `POST /auth/token`, which re-reads your membership on the
server and mints a token scoped to that workspace — so what changes is not
a filter but the token every request carries.

Everything that is per-workspace follows it: notes, spaces, and this Mac's
meetings list. That list is now filed under **your identity and the
workspace** (`recentCaptures.<identity>.<tenant>` in UserDefaults), so a
second account signing in on this Mac sees its own meetings, and the
meetings you left in another workspace are still there when you go back.
The first sign-in after this update moves the old single list under
whoever signs in first.

- A recording that was made in workspace A finishes uploading to A even
  after you have moved to B — it carries A's own token.
- If you are **removed from a workspace**, the app says so, moves you to
  another one (your personal workspace first), and keeps that workspace's
  local state on disk. Recordings that were waiting for it say "you are no
  longer a member" and offer **Send to…** another workspace, or Export.
- **Offline:** with a valid session the app works from local state and
  keeps recordings for later. If the session reaches its absolute expiry
  while you are away from the network, the app signs out but keeps
  everything: the sign-in screen lists the recordings waiting on this Mac,
  and signing in as the same person sends them.
- Settings › Account also lists **where you are signed in**
  (`GET /auth/sessions`) with *End* per session and *Sign out everywhere
  else* (which asks you to confirm it is you first), and links out to the
  web app for password, two-factor and email changes.
- Settings › Advanced can **remove another account's local data** from
  this Mac — its meetings list and any recordings kept for it. Local only;
  nothing on the server is touched.
- `notesai://invite/<token>` links are received (the app answers the
  scheme in an `LSUIElement` process through the Apple Event, since there
  is no window to hang `onOpenURL` on), but no server in this estate can
  issue or redeem an invitation yet — IDX-B1 — so the app says so rather
  than showing a preview it cannot honour.

## Dev sign-in (local stack)

The emailed-code flow needs the auth service in **native mode**:

```sh
MDX_IDP_MODE=native docker compose up -d auth-service
```

Codes are caught by Mailpit at <http://localhost:8025> — sign in with any
address and read the code there. In the default `keycloak` mode
`/auth/email/*` is not mounted; use the password screen with the seeded
account (`make seed`):

| Email                     | Password       |
| ------------------------- | -------------- |
| `member@tenant-a.example` | `dev-password` |

Keycloak-mode sign-in has no native session to keep, so the app will say
the server answered with something it cannot store — that is IDX-A4's
missing half, not a fault of this Mac.

Default backends (editable in the app's Settings tab, and behind the host
name on the sign-in screen):
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
`NSAudioCaptureUsageDescription` for the call-audio prompt,
`CFBundleURLTypes` for the `notesai://` OAuth callback of MCP connectors,
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
    ├── Shared -> ../../../clients/Shared   # sources compiled unchanged into both apps
    ├── App.swift                    # @main MenuBarExtra scene + dynamic icon
    ├── Models.swift                 # API DTOs, settings, problem parsing
    ├── APIClient.swift              # async URLSession, multipart, single-flight refresh
    ├── SessionStore.swift           # the Keychain session + legacy-cookie cleanup
    ├── LocalStore.swift             # UserDefaults, keyed by identity + workspace
    ├── PendingUploads.swift         # send / re-target / export / delete what is waiting
    ├── AppURLRouter.swift           # notesai:// links from outside the app
    ├── AuthCopy.swift               # what each error code says to the person
    ├── PendingCaptures.swift        # recordings that never reached the server
    ├── Recorder.swift               # AVAudioEngine → FLAC/WAV, mono or mic+call (TapSink), metering
    ├── SystemAudioTap.swift         # Core Audio process tap + private aggregate device (call audio)
    ├── CallAudio.swift              # consent notice/version, channel_layout, local_speaker_name
    ├── AppState.swift               # auth/settings/recents/selection/template cache
    ├── CaptureViewModel.swift       # record → upload → poll → note pipeline
    ├── NoteViewModel.swift          # one open note: load, autosave, finalize, transcript, PDF
    ├── CalendarService.swift        # EventKit: upcoming events, calendar picker, live refresh
    ├── Connectors/
    │   ├── MCPClient.swift          # MCP over Streamable HTTP: initialize, tools/list
    │   ├── MCPOAuth.swift           # discovery, dynamic registration, PKCE, loopback/scheme callback
    │   └── ConnectorStore.swift     # connector list, Keychain tokens, connect/disconnect
    └── Views/
        ├── Theme.swift              # design tokens, button/field/toggle/pill styles
        ├── Dropdowns.swift          # styled ⋯ menus (DSMenu) and select fields (DSSelect)
        ├── Components.swift         # status chip, level meter, pipeline stepper, skeleton
        ├── CaptureView.swift        # ActiveCaptureCard + NewMeetingButton
        ├── CallAudioConsentSheet.swift # the blocking call-audio notice
        ├── RecentsView.swift        # popover rows / list (grouped by day)
        ├── RootView.swift           # menu-bar popover
        ├── MainWindowView.swift     # window: sidebar + detail (note / status / home)
        ├── Sidebar.swift            # search, one button, Home, spaces, account row, rail
        ├── InviteView.swift         # invite people: add a member by e-mail, invite link
        ├── HomeView.swift           # upcoming events, meetings in flight, notes by day
        ├── NoteView.swift           # the note as a document: sections, transcript, ⋯
        ├── ConnectorsView.swift     # Settings › Connectors: calendar + MCP servers
        ├── ReauthSheet.swift        # step-up sheet + the "Reconnecting…" banner
        ├── WorkspaceViews.swift     # switcher, workspace banner, pending uploads, sessions
        └── SettingsView / SignInView # SignInView: email → code, password, MFA, welcome
```

## Tests

```sh
cd macos
swift test          # the session, the transport, workspaces, pending uploads, call audio
```

They stub the network with a `URLProtocol` and the Keychain with an
in-memory store, so nothing touches your login keychain and no server is
needed. CI runs the same two commands on a macOS runner.

Requires macOS 14 (Sonoma) or later. No third-party dependencies.
