#!/bin/bash
cd "$(dirname "$0")/.." || exit 1

# GitHub 웹 UI 업로드 등 remote 변경분 먼저 반영
git pull --rebase origin main 2>/dev/null

git add -A
CHANGES=$(git diff --cached --stat)
if [ -z "$CHANGES" ]; then
  exit 0
fi
git commit -m "auto: $(date '+%Y-%m-%d %H:%M')"
git push origin main
