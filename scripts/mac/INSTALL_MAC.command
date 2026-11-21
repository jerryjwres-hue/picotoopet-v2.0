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

# 只读预检必须先于任何版本指针、密钥、LaunchAgent 或数据库变更。
# 现有数据若来自 24 版迁移，绝不可用只支持 1-4 版的 Core 覆盖运行。
DB_FILE="$RUNTIME_ROOT/database/core.db"
if [ -s "$DB_FILE" ]; then
  if ! command -v sqlite3 >/dev/null 2>&1; then
    echo "STOP=SQLITE_PREFLIGHT_UNAVAILABLE；已有数据库，不能安全判断兼容性。" >&2
    exit 1
  fi
  migrations="$(sqlite3 -readonly "$DB_FILE"     "SELECT COALESCE(MAX(version), 0) FROM schema_migrations" 2>/dev/null)" || {
    echo "STOP=UNKNOWN_EXISTING_DATABASE；迁移记录无法读取，未修改安装。" >&2
    exit 1
  }
  case "$migrations" in
    ''|*[!0-9]*)
      echo "STOP=UNKNOWN_EXISTING_DATABASE；迁移版本无效。" >&2
      exit 1
      ;;
  esac
  if [ "$migrations" -gt 4 ]; then
    echo "STOP=UNSUPPORTED_DATABASE_VERSION_$migrations；本安装包最高只支持版本 4。" >&2
    echo "保留现有 Core、SQLite、Goal 和审批记录；请勿重置或手工补表。" >&2
    exit 1
  fi
  if [ "$migrations" -eq 4 ]; then
    hold_table="$(sqlite3 -readonly "$DB_FILE"       "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='owner_production_hold'" 2>/dev/null)" || {
      echo "STOP=SQLITE_SCHEMA_CHECK_FAILED；现有数据库保留原状。" >&2
      exit 1
    }
    if [ "$hold_table" != "1" ]; then
      echo "STOP=INCOMPATIBLE_MIGRATION_004；同一迁移编号对应不同架构。" >&2
      exit 1
    fi
  fi
fi

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

# Worker 独立 HMAC 只保存在当前用户 Keychain；升级保留原值，不写入安装日志。
# 这里不会开启 GPU 准入、Owner 审核或授权任何视频任务。
WORKER_SERVICE="PicotooPetV3.WorkerAttestation"
if ! security find-generic-password -a "$USER" -s "$WORKER_SERVICE" >/dev/null 2>&1; then
  # Bash 命令替换会去除尾部换行；只删除 base64 填充符，不得误删随机字符 n。
  WORKER_KEY="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=')"
  if [ "${#WORKER_KEY}" -ne 43 ]; then
    echo "Worker 配对密钥生成失败，安装已停止。" >&2
    exit 1
  fi
  security add-generic-password -a "$USER" -s "$WORKER_SERVICE" -w "$WORKER_KEY" >/dev/null
  unset WORKER_KEY
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

# 等待 launchd 异步移除旧服务完成，再注册新 plist，规避 37: Operation already in progress。
# 当前用户的 GUI LaunchAgent 不需要 sudo；严格拒绝假成功，失败保留日志供诊断。
for label in com.picotoopet.mac-core com.picotoopet.health-supervisor; do
  launchctl bootout "gui/$UID/$label" >/dev/null 2>&1 || true
done

for label in com.picotoopet.mac-core com.picotoopet.health-supervisor; do
  unloaded=0
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    if ! launchctl print "gui/$UID/$label" >/dev/null 2>&1; then
      unloaded=1
      break
    fi
    sleep 1
  done
  if [ "$unloaded" -ne 1 ]; then
    echo "STOP: 旧 LaunchAgent 仍未卸载：$label" >&2
    exit 1
  fi

  bootstrapped=0
  for attempt in 1 2 3 4 5 6 7 8; do
    if launchctl bootstrap "gui/$UID" "$LAUNCH_AGENTS/$label.plist"; then
      bootstrapped=1
      break
    fi
    # launchd 有时稍后才完成注销；只重试该服务，不重装整个 Mac Core。
    sleep 1
  done
  if [ "$bootstrapped" -ne 1 ]; then
    echo "STOP: LaunchAgent 注册失败：$label；请检查 launchctl 日志。" >&2
    exit 1
  fi
done

# 保留完整机器报告；正常安装不弹技术 JSON，用户只需看到结论。
HEALTH_REPORT="$RUNTIME_ROOT/state/install-health.json"
"$CURRENT/.venv/bin/picotoopet-core" health --skip-ollama > "$HEALTH_REPORT"
if "$CURRENT/.venv/bin/python" - "$HEALTH_REPORT" <<'PY'
import json
import sys
from pathlib import Path

# 仅验证安装时的数据库/磁盘健康；不把跳过 Ollama 误报为模型实测。
report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
raise SystemExit(0 if report.get("status") == "ok" else 1)
PY
then
  printf '\n[PASS] PicotooPet Mac Core 安装完成，后台服务已配置。\n'
  printf '下一步：在 Windows 双击安装包并完成一次 Mac 配对。\n'
  printf '模型与双机实际联通仍须通过独立验收。\n'
else
  printf '\n[NEEDS_REVIEW] Mac Core 已部署，但健康检查未全部通过。\n' >&2
  printf '请查看诊断报告，暂不要开始生产。\n' >&2
  open "$HEALTH_REPORT" >/dev/null 2>&1 || true
  exit 2
fi
