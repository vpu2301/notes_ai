# Notes AI — Web UI

The product SPA for the Notes AI backend. The flow is deliberately close to
Granola: press **New meeting**, talk, press **Stop** — the recording uploads,
transcribes, becomes a note, and the note opens with **Notes** and
**Transcript** tabs. Everything else (share, download, finalize, amend,
history, delete) is one menu away, never in the main path.

Hand-crafted React + TypeScript + Vite. No component library, no external
CDNs — everything renders offline against a local backend.

## Design

One design language across the three clients — this app, `macos/` and `ios/`
(`…/Views/Theme.swift`). Paper and ink with a moss accent, hairline frames
instead of shadows, continuous corners.

- **Typeface** — Geist (UI) and Geist Mono (codes, timers), self-hosted from
  `public/fonts/` and declared in `src/styles/fonts.css`. No third-party
  origin. Display text (titles, the greeting, the wordmark) takes Avenir Next
  on a Mac, which is what the capture apps set.
- **Tokens** — `src/styles/tokens.css`. Warm paper ground, warm ink, and the
  moss accent (`#4f7a5e` / `#8fbf9c`) the Mac and iPhone apps use. `--density`
  and `--fs` scale every padding and font-size respectively.
- **Frames never carry the accent.** Every hairline — resting, hovered,
  selected — is a warm neutral (`--line`, `--line-hover`, `--line-active`).
  A live element is told apart by its surface, a 1 px lift, or a moss ring on
  focus; never by a coloured border. The accent lives in tints, icons and text.
- **Continuous corners** — the radii in `--radius-*` are drawn as true
  squircles wherever the browser ships `corner-shape` (`base.css`), which is
  what `.continuous` gives the AppKit and UIKit surfaces. The brand mark does
  not wait for that: `src/components/BrandMark.tsx` is a real superellipse
  path, and `index.html` cuts the favicon from the same curve.
- **Theme** — light / dark / follow-system, picked in the sidebar footer and
  stamped as `<html data-theme>` before first paint (`src/shell/theme.ts`).
- **Shell** — 256 px collapsible sidebar (brand, ink "New meeting" split
  button, uppercase group headers, footer with theme toggle + account menu),
  a transparent sticky topbar that gains a blurred ground once the page
  scrolls, and a dot print behind the home page and the meeting stage.
- **Keyboard** — `N` new meeting, `B` blank note (outside text fields).

Stylesheets: `tokens` → `base` → `shell` → `components` → `pages`.

## Run it

```bash
# 1. Backend up (from the repo root):
make dev-up && make migrate-up && make seed
# …then start the services you need (auth, note, asr, notification), or
# `docker compose up` for the full stack.

# 2. Web UI:
cd web
npm install
npm run dev        # http://localhost:5173  (port is pinned — CORS allow-list)
```

Sign in with the dev seed account: **member@tenant-a.example** / **dev-password**.

## What's implemented

| Area | Details |
|---|---|
| Login | email + password, OTP step-up when MFA asks for it; access token in memory, silent refresh via the HttpOnly cookie |
| Sign up | `/signup` (BE-0): name, address and password, then the 6-digit code that confirms the address — and straight into the app, signed in with the password just chosen. The route the macOS and iOS apps open in a browser from "Create one". `POST /auth/signup` answers the same 202 for a known and an unknown address, so the code screen says *if* the address is new and offers "Sign in instead" rather than implying the server recognised it. A refused password lists the server's `reasons[]` under the field. `/login/password` meeting `email_not_verified` offers a resend and a way to spend the code |
| Home | one list: meetings still transcribing sit at the top ("In progress"), notes below grouped by day; full-text search with highlighted snippets; cursor pagination. Finished recordings turn into notes on their own and appear in the list without a reload |
| Coming up | the top of Home: today's date and the next 7 days of events from the user's connected calendars, **Start** on any of them opens New meeting with the event's title, **Join** opens the video call. Two ways in, both stored on note-service and shared with the macOS app: **Connect Google Calendar** (the sign-in round-trips through note-service and lands back on `/?calendar=connected`; shown only when the server has `GOOGLE_CALENDAR_CLIENT_ID` set) and **Add calendar link** (paste the calendar's private iCal address — Google, Outlook or iCloud; needs nothing on the server). The ⋯ menu chooses calendars, adds another account or link, disconnects. Hidden only when neither way in is available |
| New meeting | title + Record. Stop uploads and transcribes immediately; the page shows progress and opens the note when it's ready (or you leave, and it shows up on Home). Drop or pick a file to upload instead. "Options" hides speaker separation (on by default) and a vocabulary hint |
| Blank note | creates a note from the default meeting-notes template and opens it. "New from template…" keeps the full picker for the other templates |
| Note | document layout: title, meta line, then **Notes** / **Transcript** tabs (Transcript appears when the note came from a recording; speaker turns with timestamps, copy button). Per-section fields typed from the template, debounced autosave, version-conflict banner. The ⋯ menu holds **Share…** (private / whole workspace, a public link anyone can open at `/s/:token`, share with a colleague by e-mail, e-mail the link), **Download PDF** / **Download Markdown**, history, finalize, revert, amend, and **Delete note** |
| Spaces | the user's own folders, server-side in note-service (`/v1/spaces`, migration 0021) and shared with the macOS and iOS apps. The sidebar lists them under **All notes** with a note count; **+** adds one inline, the row's ⋯ renames or deletes it (its notes go back to All notes). Clicking one opens `/spaces/:id` — the same Home list narrowed to that space. A note is filed from the ⋯ menu on its Home row or in the note itself ("Move to …" / "Remove from …") |
| Shell | collapsible sidebar with a **New meeting** split button (Blank note / Upload / From template), **All notes** + Spaces, theme toggle, notification bell, account menu |

### How the meeting pipeline maps onto the backend

1. `POST /asr/jobs` (asr-service) with the recording; the browser remembers
   the job id as *its own* and the title you typed.
2. Home and the meeting page poll `GET /asr/jobs` while anything is queued or
   running.
3. When a job the browser started is `complete`, it calls
   `POST /v1/notes/from-transcript` (note-service picks the template from the
   transcript, or you can pass one) and opens the note. Jobs started
   elsewhere (the macOS app, another browser) show a **Create note** button
   instead — no surprise notes.
4. `GET /v1/notes/by-source-job` resolves which note a job became, so the
   editor can offer the **Transcript** tab (`GET /asr/jobs/{id}/result`).

## Configuration

Backend base URLs come from Vite env vars (defaults match the dev stack):

| Var | Default |
|---|---|
| `VITE_AUTH_BASE` | `http://localhost:8000` |
| `VITE_ASR_BASE` | `http://localhost:8001` |
| `VITE_NOTIFICATION_BASE` | `http://localhost:8004` |
| `VITE_NOTE_BASE` | `http://localhost:8006` |

Every base is a **different origin** from the SPA, so each one's CORS
`allow_headers` is a hard limit on what the client may send. A request
carrying a header the service does not list fails its preflight, the real
call is never sent, and it reaches the UI as "cannot reach the server"
rather than as an HTTP status. `CORS_CUSTOM_HEADERS` in `src/api/http.ts`
mirrors that allow-list per service — today only auth-service accepts
`X-Client-Type` and `X-Request-Id`; note, ASR and notification accept
`Authorization` and `Content-Type` only. Widen a row there only after the
matching service's `main.py` has been widened too.

## Scripts

```bash
npm run dev      # dev server on :5173
npm run build    # type-check + production build to dist/
npm run preview  # serve the production build locally
npm test         # Vitest — transport, auth context, sign-up branches
npm run test:e2e # Playwright — see below, needs a running stack
```

## The browser suite (WEB-1b)

`e2e/` proves the one journey the unit tests cannot: an address nobody has
seen, through an emailed code, to a note that exists. It needs a real
auth-service in **native** mode and a real Mailpit, because the sign-in code
is only ever readable from the mailbox — `/auth/email/start` answers 202 for
every valid address by construction, so there is nothing in the response to
scrape.

```bash
# From the repo root, once:
make web-e2e-stack   # auth-service in native mode, SMTP → Mailpit :8025
make migrate-up seed

# Then, as often as you like:
make web-e2e         # or: cd web && npm run test:e2e
npx playwright test e2e/first-use.spec.ts --headed   # watch it happen
```

`make web-e2e-stack` overrides `MDX_IDP_MODE` and the SMTP host for the
containers it starts. That second override matters: a developer with a real
relay in their `.env` must not have a test suite mailing sign-in codes to
the internet. Put the stack back with `make dev-up`.

Two things the suite deliberately does **not** fake:

* **The microphone.** Chromium runs with `--use-fake-device-for-media-stream`,
  so `getUserMedia` hands back a real `MediaStream` carrying a synthetic
  tone. Monkey-patching `navigator.mediaDevices` would prove the stub works
  and nothing about `MediaRecorder`.
* **The transcription.** Stop really uploads, the worker really runs Whisper,
  and the test waits for the note. That is minutes on a cold CPU worker, and
  it is the hand-off — finished job to written note — that a mock would skip.

The regression specs skip themselves unless their fixtures are named:

```bash
E2E_PASSWORD_EMAIL=member@tenant-a.example E2E_PASSWORD=dev-password \
E2E_MFA_EMAIL=mfa@tenant-a.example npm run test:e2e
```

It is not a per-PR CI job: the ASR worker image bakes whisper-large-v3, which
is not something a GitHub runner should build on every push. Run it against
the dev stack before merging anything on the sign-in path.

## Screenshots

_(add screenshots here)_

## Sharing and deleting (0016)

- New notes are **private**: the author, co-authors, and people it was shared
  with can open it. *Everyone in the workspace* makes it visible to all members.
- A **public link** (`/s/<token>`) opens a read-only page with PDF / Markdown
  download and no sign-in. Turn it off from the same dialog.
- **Share with a colleague** takes an e-mail address; a workspace member gets
  read access plus an in-app and e-mail notification (the mail carries the note
  code and who shared it, never the content). An outside address gets a
  pre-filled mail with the public link instead.
- **Delete** is a soft delete: the note leaves every list, its links stop
  working, and the row stays for the workspace's records.
