#!/usr/bin/env bash
# CI gate — no gold content is ever tracked under eval/ (Sprint 28 B-7,
# extended in Sprint TQ1 T2).
#
# 1. Audio, anywhere under eval/. The speaker gold set holds personal data;
#    only manifests and RTTMs live in git for eval/speakers.
# 2. Text, under eval/asr/** and eval/notes/**: references, spans, gold
#    notes, review sheets and RTTMs are content (a human-corrected transcript
#    is the recording in words). Only manifest.json and README.md may be
#    tracked there.
#
# `--paths FILE...` checks the given paths instead of `git ls-files eval`
# (used by tests/unit/test_asr_eval.py).
set -euo pipefail

if [[ "${1:-}" == "--paths" ]]; then
  shift
  tracked=$(printf '%s\n' "$@")
else
  tracked=$(git ls-files eval)
fi

fail=0
audio=$(grep -Ei '\.(flac|wav|webm|mp3|m4a|ogg|opus|aac|aiff?)$' <<<"$tracked" || true)
if [[ -n "$audio" ]]; then
  echo "audio files tracked under eval/ (remove them; content lives in the eval bucket):" >&2
  echo "$audio" >&2
  fail=1
fi

text=$(grep -E '^eval/(asr|notes)/' <<<"$tracked" \
  | grep -Ei '\.(json|csv|txt|rttm|tsv|srt|vtt|md)$' \
  | grep -Ev '(^|/)(manifest\.json|README\.md)$' || true)
if [[ -n "$text" ]]; then
  echo "gold content tracked under eval/asr or eval/notes (only manifest.json and README.md may be):" >&2
  echo "$text" >&2
  fail=1
fi

if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
echo "PASS: no audio under eval/, no gold content under eval/asr or eval/notes"
