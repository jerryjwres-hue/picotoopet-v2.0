#!/bin/bash
# 切回安装前记录的版本，并重新加载 launchd。
set -euo pipefail
ROOT="$HOME/Library/Application Support/PicotooPetV2"
STATE="$ROOT/state/previous_version.txt"
CURRENT="$ROOT/current"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

if [ ! -f "$STATE" ]; then
  echo "没有可用的 previous_version.txt。" >&2
  exit 1
fi
PREVIOUS="$(cat "$STATE")"
if [ ! -d "$PREVIOUS" ]; then
  echo "上一版本目录不存在：$PREVIOUS" >&2
  exit 1
fi

for label in com.picotoopet.mac-core com.picotoopet.health-supervisor; do
  launchctl bootout "gui/$UID/$label" >/dev/null 2>&1 || true
done
ln -sfn "$PREVIOUS" "$CURRENT.next"
mv -h "$CURRENT.next" "$CURRENT"
launchctl bootstrap "gui/$UID" "$LAUNCH_AGENTS/com.picotoopet.mac-core.plist"
launchctl bootstrap "gui/$UID" "$LAUNCH_AGENTS/com.picotoopet.health-supervisor.plist"
printf '%s\n' "$(date -u +%FT%TZ) rollback -> $PREVIOUS" >> "$ROOT/state/rollback.log"
open "$ROOT/state/rollback.log"
