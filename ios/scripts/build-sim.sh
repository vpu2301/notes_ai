#!/usr/bin/env bash
# Build the .app for the iOS Simulator with xcodebuild (no signing needed).
# Requires the iOS platform to be installed in Xcode
# (Xcode › Settings › Components, or `xcodebuild -downloadPlatform iOS`).
#
#   ios/scripts/build-sim.sh                 # Debug
#   ios/scripts/build-sim.sh Release
set -euo pipefail

CONFIG="${1:-Debug}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

xcodebuild -project NotesAICapture.xcodeproj -scheme NotesAICapture -configuration "$CONFIG" \
  -destination 'generic/platform=iOS Simulator' -derivedDataPath build \
  CODE_SIGNING_ALLOWED=NO build

echo "Built: $HERE/build/Build/Products/$CONFIG-iphonesimulator/NotesAICapture.app"
