# Notes AI — Web UI

The product SPA for the Notes AI backend: sign in, search and write
template-based notes, and capture meetings (record in the browser or upload a
recording → diarized transcription → speaker-attributed note).

Hand-crafted React + TypeScript + Vite. No component library, no external
fonts/CDNs — everything renders offline against a local backend. Light and
dark themes follow the system.

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
| Notes | debounced full-text search, status filter chips, highlighted snippets, cursor pagination |
| New note | template picker grouped by category (seeded: meeting notes, 1-on-1, sales call, interview debrief, project update) |
| Editor | per-section fields typed from the template (free text, choice, date, numeric+unit), debounced autosave with visible save state and version-conflict banner, finalize / revert / amend (typed + reasoned, on the record), version history panel, PDF download |
| Capture | in-browser recording (level meter + timer) or drag-and-drop upload, language + "separate speakers" (diarization) + vocabulary hint, live-polled job list, one-click note creation from a finished transcript |
| Shell | sidebar nav, notification bell (unread count + feed + mark read), user menu |

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
