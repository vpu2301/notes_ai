#!/usr/bin/env bash
# Run the unit tests on an iOS Simulator. This BOOTS A SIMULATOR (check.sh
# and build-sim.sh only compile); see ios/CLAUDE.md.
#
#   ios/scripts/test.sh                       # first available iPhone runtime
#   ios/scripts/test.sh 'iPhone 16 Pro'
set -euo pipefail

DEVICE="${1:-iPhone 16}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

xcodebuild -project NotesAICapture.xcodeproj -scheme NotesAICapture \
  -configuration Debug -destination "platform=iOS Simulator,name=$DEVICE" \
  -derivedDataPath build CODE_SIGNING_ALLOWED=NO test
