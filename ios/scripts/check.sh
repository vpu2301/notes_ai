#!/usr/bin/env bash
# Compile the iOS app's sources against the iOS SDK without an Xcode build.
# Needs only the Xcode command-line tools (the iPhoneSimulator SDK); no
# simulator runtime or device support has to be installed.
#
#   ios/scripts/check.sh            # whole-module compile, warnings shown
#   ios/scripts/check.sh --quick    # type-check only (faster)
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

TARGET="arm64-apple-ios17.0-simulator"
FILES=()
while IFS= read -r f; do FILES+=("$f"); done < <(find Sources -name '*.swift' | sort)

if [[ "${1:-}" == "--quick" ]]; then
  xcrun -sdk iphonesimulator swiftc -typecheck -target "$TARGET" -parse-as-library "${FILES[@]}"
else
  OUT="$(mktemp -d)"
  trap 'rm -rf "$OUT"' EXIT
  xcrun -sdk iphonesimulator swiftc -target "$TARGET" -parse-as-library -module-name NotesAICapture \
    -wmo -Onone -emit-object -o "$OUT/NotesAICapture.o" "${FILES[@]}"
fi
echo "ok: ${#FILES[@]} files compile for $TARGET"
