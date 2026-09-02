#!/usr/bin/env bash
# Wrap the SPM build into a real .app bundle (menu-bar identity, mic prompt)
# without needing XcodeGen / an .xcodeproj.
#
#   macos/scripts/make-app.sh            # debug build → macos/.build/Notes AI Capture.app
#   macos/scripts/make-app.sh release    # release build
#
# Then: open "macos/.build/Notes AI Capture.app"
set -euo pipefail

CONFIG="${1:-debug}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

swift build -c "$CONFIG"

BIN="$(swift build -c "$CONFIG" --show-bin-path)/NotesAICapture"
APP="$HERE/.build/Notes AI Capture.app"
CONTENTS="$APP/Contents"

rm -rf "$APP"
mkdir -p "$CONTENTS/MacOS"
cp "$BIN" "$CONTENTS/MacOS/NotesAICapture"

# Substitute the Xcode build variables used in Support/Info.plist.
sed -e 's/\$(EXECUTABLE_NAME)/NotesAICapture/g' \
    -e 's/\$(PRODUCT_BUNDLE_IDENTIFIER)/ai.notes.capture/g' \
    -e 's/\$(MACOSX_DEPLOYMENT_TARGET)/14.0/g' \
    Support/Info.plist > "$CONTENTS/Info.plist"

# Sign with a PERSISTENT identity. The microphone permission is keyed to the
# signature's designated requirement; an ad-hoc signature changes with every
# build and makes macOS forget (and silently deny) the grant. The identity is
# created once by scripts/make-signing-identity.sh.
IDENTITY="${NOTES_AI_SIGN_IDENTITY:-Notes AI Capture Dev}"
if ! security find-identity -v -p codesigning 2>/dev/null | grep -q "\"$IDENTITY\""; then
  scripts/make-signing-identity.sh || true
fi
if security find-identity -v -p codesigning 2>/dev/null | grep -q "\"$IDENTITY\""; then
  codesign --force --sign "$IDENTITY" --identifier ai.notes.capture "$APP" >/dev/null
else
  echo "warning: no \"$IDENTITY\" identity — falling back to an ad-hoc signature;" >&2
  echo "         the microphone permission will not survive a rebuild." >&2
  codesign --force --sign - "$APP" >/dev/null
fi

echo "Built: $APP"
