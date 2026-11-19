#!/bin/bash
# 使用 SQLite 在线备份接口创建一致性备份。
set -euo pipefail
ROOT="$HOME/Library/Application Support/PicotooPetV2"
DATABASE="$ROOT/database/core.db"
BACKUP="$ROOT/backups/core-$(date +%Y%m%d-%H%M%S).db"
mkdir -p "$ROOT/backups"
if [ ! -f "$DATABASE" ]; then
  echo "数据库不存在：$DATABASE" >&2
  exit 1
fi
sqlite3 "$DATABASE" ".backup '$BACKUP'"
shasum -a 256 "$BACKUP" > "$BACKUP.sha256"
open -R "$BACKUP"
