#!/usr/bin/env bash
# IDX-I1 L: a Release build must not allow arbitrary loads.
#
# Asserted on the built product rather than on the source plist, because
# the policy is produced by the Info.plist preprocessor (Support/Config/*.xcconfig)
# and a change there is exactly the kind of thing that would go unnoticed.
#
#   ios/scripts/check-ats.sh [path/to/Info.plist]
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="${1:-$HERE/build/Build/Products/Release-iphonesimulator/NotesAICapture.app/Info.plist}"

if [[ ! -f "$PLIST" ]]; then
  echo "no built Info.plist at $PLIST — run scripts/build-sim.sh Release first" >&2
  exit 2
fi

arbitrary="$(plutil -extract NSAppTransportSecurity.NSAllowsArbitraryLoads raw -o - "$PLIST" 2>/dev/null || echo missing)"
if [[ "$arbitrary" != "false" && "$arbitrary" != "0" ]]; then
  echo "FAIL: Release NSAllowsArbitraryLoads is '$arbitrary', expected false" >&2
  exit 1
fi

local_net="$(plutil -extract NSAppTransportSecurity.NSAllowsLocalNetworking raw -o - "$PLIST" 2>/dev/null || echo absent)"
if [[ "$local_net" == "true" || "$local_net" == "1" ]]; then
  echo "FAIL: Release keeps NSAllowsLocalNetworking; that exception is Debug-only" >&2
  exit 1
fi

echo "ok: Release build allows no arbitrary loads"
