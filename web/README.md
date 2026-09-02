# Notes AI — Web UI

The product SPA for the Notes AI backend. The flow is deliberately close to
Granola: press **New meeting**, talk, press **Stop** — the recording uploads,
transcribes, becomes a note, and the note opens with **Notes** and
**Transcript** tabs. Everything else (share, download, finalize, amend,
history, delete) is one menu away, never in the main path.

Hand-crafted React + TypeScript + Vite. No component library, no external
CDNs — everything renders offline against a local backend.

## Design

The UI shares its design language with the Klarnote platform (`~/Desktop/dictat`):

- **Typeface** — Geist (UI) and Geist Mono (codes, timers), self-hosted from
  `public/fonts/` and declared in `src/styles/fonts.css`. No third-party origin.
- **Tokens** — `src/styles/tokens.css`. Cool neutrals, hairline borders, one
  teal accent whose hover/tint/text/fill shades are `color-mix`-derived from
  `--accent`, so changing the single hex re-tints the whole app. `--density`
  and `--fs` scale every padding and font-size respectively.
- **Theme** — light / dark / follow-system, picked in the sidebar footer and
  stamped as `<html data-theme>` before first paint (`src/shell/theme.ts`).
- **Shell** — 248 px collapsible sidebar (brand, dark "New note" split button,
  uppercase group header, footer with theme toggle + account menu), a
  transparent sticky topbar that gains a blurred ground once the page scrolls,
  and a soft radial wash on the shell behind flat white panels.
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
| Home | one list: meetings still transcribing sit at the top ("In progress"), notes below grouped by day; full-text search with highlighted snippets; cursor pagination. Finished recordings turn into notes on their own and appear in the list without a reload |
| New meeting | title + Record. Stop uploads and transcribes immediately; the page shows progress and opens the note when it's ready (or you leave, and it shows up on Home). Drop or pick a file to upload instead. "Options" hides speaker separation (on by default) and a vocabulary hint |
| Blank note | creates a note from the default meeting-notes template and opens it. "New from template…" keeps the full picker for the other templates |
| Note | document layout: title, meta line, then **Notes** / **Transcript** tabs (Transcript appears when the note came from a recording; speaker turns with timestamps, copy button). Per-section fields typed from the template, debounced autosave, version-conflict banner. The ⋯ menu holds **Share…** (private / whole workspace, a public link anyone can open at `/s/:token`, share with a colleague by e-mail, e-mail the link), **Download PDF** / **Download Markdown**, history, finalize, revert, amend, and **Delete note** |
| Shell | collapsible sidebar with a **New meeting** split button (Blank note / Upload / From template), theme toggle, notification bell, account menu |

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

## Scripts

```bash
npm run dev      # dev server on :5173
npm run build    # type-check + production build to dist/
npm run preview  # serve the production build locally
```

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
