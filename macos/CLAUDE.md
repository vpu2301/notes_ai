# macOS capture app — working rules

- **Build only, never launch.** After `scripts/make-app.sh`, `swift build`, or
  any rebuild, do not run `open ".build/Notes AI Capture.app"`, `swift run`,
  or `pkill`/relaunch the app. Report the build result and let the user
  start the app themselves.
