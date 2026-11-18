#!/bin/bash
# Picotoo Pet V2 Mac Core 双击安装器。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNTIME_ROOT="$HOME/Library/Application Support/PicotooPetV2"
VERSION="2.2.0-phase2-slice1-$(date -u +%Y%m%dT%H%M%SZ)-$$"
VERSIONS_ROOT="$RUNTIME_ROOT/versions"
TARGET="$VERSIONS_ROOT/$VERSION"
CURRENT="$RUNTIME_ROOT/current"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
STATE_DIR="$RUNTIME_ROOT/state"
PORT_HELPER="$SCRIPT_DIR/lib/runtime_port.sh"

mkdir -p "$VERSIONS_ROOT" "$RUNTIME_ROOT/logs" "$RUNTIME_ROOT/backups" "$STATE_DIR" "$LAUNCH_AGENTS"


# 已有安装保留当前端口；首次安装时按 8765、8766 顺序选择空闲端口。
if [ -f "$STATE_DIR/api-port.txt" ]; then
  API_PORT="$(cat "$STATE_DIR/api-port.txt")"
else
  # shellcheck source=lib/runtime_port.sh
  source "$PORT_HELPER"
  API_PORT="$(select_api_port 8765 8766)" || {
    echo "8765 和 8766 均被占用，安装已停止。" >&2
    exit 1
  }
fi
case "$API_PORT" in
  ''|*[!0-9]*)
    echo "API 端口记录无效：$API_PORT" >&2
    exit 1
    ;;
esac
printf '%s\n' "$API_PORT" > "$STATE_DIR/api-port.txt"

# 保留上一个版本路径，为原子回滚提供依据。
if [ -L "$CURRENT" ]; then
  readlink "$CURRENT" > "$STATE_DIR/previous_version.txt"
elif [ -d "$CURRENT" ]; then
  printf '%s\n' "$CURRENT" > "$STATE_DIR/previous_version.txt"
fi

# 安装 uv；日常运行不需要用户打开终端。
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

rm -rf "$TARGET.partial"
mkdir -p "$TARGET.partial"
rsync -a \
  --exclude '.git' \
  --exclude '.pytest_cache' \
  --exclude '__pycache__' \
  "$SOURCE_ROOT/" "$TARGET.partial/"
mv "$TARGET.partial" "$TARGET"

# 首次联网安装时生成锁文件；已有锁文件时严格按锁安装。
if [ -f "$TARGET/uv.lock" ]; then
  uv sync --project "$TARGET" --frozen
else
  uv lock --project "$TARGET"
  uv sync --project "$TARGET" --frozen
fi

# 令牌只进入当前用户 Keychain；升级时保留现有令牌，避免已配对 Windows 无故掉线。
if ! security find-generic-password -a "$USER" -s "PicotooPetV2.API" >/dev/null 2>&1; then
  TOKEN="$(openssl rand -hex 32)"
  security add-generic-password -a "$USER" -s "PicotooPetV2.API" -w "$TOKEN" >/dev/null
  unset TOKEN
fi

ln -sfn "$TARGET" "$CURRENT.next"
mv -h "$CURRENT.next" "$CURRENT"

# 用虚拟环境 Python 渲染当前用户绝对路径。
"$TARGET/.venv/bin/python" - "$TARGET" "$HOME" "$LAUNCH_AGENTS" "$API_PORT" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]) / "deploy" / "macos"
home = sys.argv[2]
destination = Path(sys.argv[3])
api_port = sys.argv[4]
for name in ("com.picotoopet.mac-core.plist", "com.picotoopet.health-supervisor.plist"):
    text = (source / name).read_text(encoding="utf-8")
    text = text.replace("__HOME__", home).replace("__API_PORT__", api_port)
    (destination / name).write_text(text, encoding="utf-8")
PY

for label in com.picotoopet.mac-core com.picotoopet.health-supervisor; do
  launchctl bootout "gui/$UID/$label" >/dev/null 2>&1 || true
done
launchctl bootstrap "gui/$UID" "$LAUNCH_AGENTS/com.picotoopet.mac-core.plist"
launchctl bootstrap "gui/$UID" "$LAUNCH_AGENTS/com.picotoopet.health-supervisor.plist"

"$CURRENT/.venv/bin/picotoopet-core" health --skip-ollama > "$RUNTIME_ROOT/state/install-health.json"
open "$RUNTIME_ROOT/state/install-health.json"
