# macOS capture app — working rules

- `Sources/NotesAICapture/Shared` is a symlink to `clients/Shared`, the sources both
  apps compile unchanged. Edit them there; a file may join only when its code is
  byte-identical in both apps.

- **Build only, never launch.** After `scripts/make-app.sh`, `swift build`, or
  any rebuild, do not run `open ".build/Notes AI Capture.app"`, `swift run`,
  or `pkill`/relaunch the app. Report the build result and let the user
  start the app themselves.
