# iOS capture app — working rules

- **Build only, never launch.** After `scripts/check.sh`, `scripts/build-sim.sh`
  or any `xcodebuild`, do not boot a simulator, `xcrun simctl launch`/`install`,
  or open Xcode. Report the build result and let the user run the app.
- The Xcode project is hand-written (`NotesAICapture.xcodeproj/project.pbxproj`,
  Xcode 16 synchronized-folder format): every file under
  `Sources/NotesAICapture` is picked up automatically, so adding a Swift file
  needs no project edit.
- `scripts/check.sh` type-checks and compiles the module against the iOS SDK
  with `swiftc` alone; it works even when Xcode has no iOS platform
  downloaded. Run it after every change.
- The unit tests (`Tests/NotesAICaptureTests`, added by IDX-I1) are an
  app-hosted XCTest bundle, so running them **boots a simulator** — which
  the rule above forbids. Verify them with
  `xcodebuild … build-for-testing` (compiles and links the bundle, boots
  nothing) and leave `scripts/test.sh` to the user and to CI.
- `scripts/build-sim.sh Release && scripts/check-ats.sh` is the only way to
  see the Release App Transport Security policy: it is produced by the
  Info.plist preprocessor from `Support/Config/*.xcconfig`, so it is not
  written literally in any file.
