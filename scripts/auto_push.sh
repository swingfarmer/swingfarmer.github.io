#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
git add -A
CHANGES=$(git diff --cached --stat)
if [ -z "$CHANGES" ]; then
  exit 0
fi
git commit -m "auto: $(date '+%Y-%m-%d %H:%M')"
git push origin main
