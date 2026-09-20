#!/usr/bin/env bash
# CI gate — no audio file is ever tracked under eval/ (Sprint 28 B-7).
# The speaker gold set holds personal data; only manifests and RTTMs live in git.
set -euo pipefail
hits=$(git ls-files eval | grep -Ei '\.(flac|wav|webm|mp3|m4a|ogg|opus)$' || true)
if [[ -n "$hits" ]]; then
  echo "audio files tracked under eval/ (remove them and use fetch_speaker_corpus.py):" >&2
  echo "$hits" >&2
  exit 1
fi
echo "PASS: no audio under eval/"
