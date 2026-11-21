#!/bin/bash
# Picotoo Pet V2 Mac Core 双击安装器。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNTIME_ROOT="$HOME/Library/Application Support/PicotooPetV2"
# 版本名必须来自这份 2.3 Core 的真实产品版本，严禁回退到 2.2 的伪标签。
PRODUCT_VERSION="$(cat "$SOURCE_ROOT/src/picotoopet_core/product-version.txt")"
if [[ ! "$PRODUCT_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "STOP=INVALID_PRODUCT_VERSION" >&2
  exit 1
fi
VERSION="${PRODUCT_VERSION}-v31-compat-$(date -u +%Y%m%dT%H%M%SZ)-${BASHPID}"
VERSIONS_ROOT="$RUNTIME_ROOT/versions"
TARGET="$VERSIONS_ROOT/$VERSION"
CURRENT="$RUNTIME_ROOT/current"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
CORE_PLIST="$LAUNCH_AGENTS/com.picotoopet.mac-core.plist"
STATE_DIR="$RUNTIME_ROOT/state"
PORT_HELPER="$SCRIPT_DIR/lib/runtime_port.sh"
DB_COMPAT="$SCRIPT_DIR/lib/check_install_database.py"
DATABASE_FILE="$RUNTIME_ROOT/database/core.db"
DB_REQUIRE=()
if [ -L "$CURRENT" ] || [ -d "$CURRENT" ]; then
  DB_REQUIRE=(--require-existing)
fi

# 先只读验明 Schema 24 家族；本机历史任务不允许任何降级或同编号异构接管。
# 当前仍运行的 2.3 Core 不在这一步中被卸载；不启动 Worker 或 Comfy。
command -v python3 >/dev/null 2>&1 || { echo "STOP=PYTHON3_UNAVAILABLE" >&2; exit 1; }
python3 "$DB_COMPAT" --database "$DATABASE_FILE" "${DB_REQUIRE[@]}"

mkdir -p "$VERSIONS_ROOT" "$RUNTIME_ROOT/logs" "$RUNTIME_ROOT/backups" "$STATE_DIR" "$LAUNCH_AGENTS"


# 已有安装保留当前端口；首次安装时按 8765、8766 顺序选择空闲端口。
if [ -f "$STATE_DIR/api-port.txt" ]; then
  API_PORT="$(cat "$STATE_DIR/api-port.txt")"
  # 新状态文件不得与已启动实例的 LaunchAgent 记录冲突。
  if [ -f "$CORE_PLIST" ]; then
    INSTALLED_PORT="$(/usr/libexec/PlistBuddy -c 'Print :EnvironmentVariables:PICOTOO_API_PORT' "$CORE_PLIST" 2>/dev/null)" || {
      echo "STOP=EXISTING_LAUNCHAGENT_PORT_UNKNOWN" >&2
      exit 1
    }
    if [ "$API_PORT" != "$INSTALLED_PORT" ]; then
      echo "STOP=PORT_STATE_CONFLICT" >&2
      exit 1
    fi
  fi
elif [ -f "$CORE_PLIST" ]; then
  # 兼容手工部署的 2.3 LaunchAgent：从原配置读取端口，不误占 8765 AI Server。
  API_PORT="$(/usr/libexec/PlistBuddy -c 'Print :EnvironmentVariables:PICOTOO_API_PORT' "$CORE_PLIST" 2>/dev/null)" || {
    echo "STOP=EXISTING_LAUNCHAGENT_PORT_UNKNOWN" >&2
    exit 1
  }
elif [ -L "$CURRENT" ]; then
  echo "STOP=EXISTING_CORE_PORT_UNKNOWN" >&2
  exit 1
else
  # shellcheck source=lib/runtime_port.sh
  source "$PORT_HELPER"
  API_PORT="$(select_api_port 8765 8766)" || {
    echo "STOP=NO_FREE_API_PORT" >&2
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

# 只能原子切换现有符号链接；普通目录、相对链接或损坏链接一律拒绝。
PREVIOUS_TARGET=""
PREVIOUS_EXISTS=0
if [ -L "$CURRENT" ]; then
  PREVIOUS_TARGET="$(readlink "$CURRENT")"
  if [[ "$PREVIOUS_TARGET" != /* ]] || [ ! -d "$PREVIOUS_TARGET" ]; then
    echo "STOP=UNSAFE_PREVIOUS_CORE_LINK" >&2
    exit 1
  fi
  PREVIOUS_EXISTS=1
  printf '%s\n' "$PREVIOUS_TARGET" > "$STATE_DIR/previous_version.txt"
elif [ -e "$CURRENT" ]; then
  echo "STOP=UNMANAGED_CURRENT_DIRECTORY" >&2
  exit 1
fi
if [ -e "$CURRENT.next" ] || [ -L "$CURRENT.next" ]; then
  echo "STOP=STALE_CURRENT_NEXT" >&2
  exit 1
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

# 在线备份必须在任何 Keychain、current 或 LaunchAgent 变更之前验证完成。
# 不复制活动 WAL 原始文件；备份失败时原 Core 仍保持运行。
python3 "$DB_COMPAT" --database "$DATABASE_FILE" --backup-dir "$RUNTIME_ROOT/backups" "${DB_REQUIRE[@]}"

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
for name in ("com.picotoopet.mac-core.plist",):
    text = (source / name).read_text(encoding="utf-8")
    text = text.replace("__HOME__", home).replace("__API_PORT__", api_port)
    (destination / name).write_text(text, encoding="utf-8")
PY

# 只重启 Mac Core；恢复现场的 Health Supervisor 继续保持未启动态，不由升级器启动。
# 这里不会调用 Windows Worker、ComfyUI，也不会授予任何 GPU 生产许可。
label=com.picotoopet.mac-core
launchctl bootout "gui/$UID/$label" >/dev/null 2>&1 || true
unloaded=0
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if ! launchctl print "gui/$UID/$label" >/dev/null 2>&1; then
    unloaded=1
    break
  fi
  sleep 1
done
if [ "$unloaded" != 1 ]; then
  echo "STOP=LAUNCHAGENT_UNLOAD_TIMEOUT:$label" >&2
  exit 1
fi
bootstrapped=0
for attempt in 1 2 3 4 5 6 7 8; do
  if launchctl bootstrap "gui/$UID" "$LAUNCH_AGENTS/$label.plist"; then
    bootstrapped=1
    break
  fi
  sleep 1
done
if [ "$bootstrapped" != 1 ]; then
  echo "STOP=LAUNCHAGENT_BOOTSTRAP_FAILED:$label" >&2
  exit 1
fi

"$CURRENT/.venv/bin/picotoopet-core" health --skip-ollama > "$RUNTIME_ROOT/state/install-health.json"
open "$RUNTIME_ROOT/state/install-health.json"
