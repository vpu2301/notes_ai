#!/usr/bin/env bash
# Run the unit tests (IDX-I1) on an iOS Simulator.
#
# This BOOTS A SIMULATOR — unlike scripts/check.sh and scripts/build-sim.sh,
# which only compile. CI runs it on every push; run it yourself when you
# want the tests, and see ios/CLAUDE.md for why the assistant does not.
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
