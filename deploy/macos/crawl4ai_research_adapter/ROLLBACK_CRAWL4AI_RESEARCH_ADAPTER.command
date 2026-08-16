#!/bin/bash
# 回滚仅属于 Crawl4AI adapter 的接线与私有运行时；绝不删除 Scrapling、Research Gateway 或 Mac Worker。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
payload_dir="$script_dir/payload"
adapter_root="${PICOTOOPET_CRAWL4AI_ROOT:-$HOME/.local/share/picotoopet/research/crawl4ai}"
venv_dir="$adapter_root/venv"
runtime_dir="$adapter_root/runtime"
bin_dir="$adapter_root/bin"
state_dir="$adapter_root/state"
logs_dir="$adapter_root/logs"
browser_dir="$adapter_root/ms-playwright"
data_dir="$adapter_root/data"
gateway_root="${PICOTOOPET_RESEARCH_INSTALL_ROOT:-$HOME/Library/Application Support/PicotooPet/ResearchGateway}"
gateway_runtime="$gateway_root/runtime"
backup_gateway="$state_dir/gateway.py.pre-crawl4ai"
install_state="$state_dir/install-state.json"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "此回滚入口仅支持 macOS。" >&2
  exit 1
fi
test "$(uname -m)" = "arm64"

mkdir -p "$logs_dir"
log_file="$logs_dir/rollback-$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(tee -a "$log_file") 2>&1

if [[ ! -f "$backup_gateway" ]]; then
  echo "没有找到 gateway.py.pre-crawl4ai；为避免覆盖未知 Gateway，回滚中止。" >&2
  exit 1
fi
if [[ ! -d "$gateway_runtime" ]]; then
  echo "Research Gateway runtime 不存在：$gateway_runtime" >&2
  exit 1
fi

created_venv=false
if [[ -f "$install_state" ]]; then
  created_venv="$(python3 - "$install_state" <<'PY'
import json
import sys
from pathlib import Path
try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, ValueError):
    print("false")
else:
    print("true" if payload.get("created_venv") is True else "false")
PY
)"
fi

# 恢复安装前 Gateway 源文件；Gateway 本体、VERSION、bin wrapper 与其它 Research 工具全部保留。
install -m 0644 "$backup_gateway" "$gateway_runtime/gateway.py"

# 仅当当前 crawler_adapter.py 仍等于本包 payload 时删除，避免覆盖后来的人为修改。
if [[ -f "$gateway_runtime/crawler_adapter.py" && -f "$payload_dir/crawler_adapter.py" ]]; then
  installed_hash="$(shasum -a 256 "$gateway_runtime/crawler_adapter.py" | awk '{print tolower($1)}')"
  package_hash="$(shasum -a 256 "$payload_dir/crawler_adapter.py" | awk '{print tolower($1)}')"
  if [[ "$installed_hash" == "$package_hash" ]]; then
    rm -f "$gateway_runtime/crawler_adapter.py"
  else
    echo "检测到 crawler_adapter.py 已被后来修改；为避免破坏新代码，文件保留。"
  fi
fi

# 删除 adapter 自己的 wrapper/runtime/data；外部提供的 venv 不归本包所有，不删除。
rm -f "$bin_dir/picotoopet-crawl4ai-provider"
rm -f "$runtime_dir/crawl4ai_runner.py" "$runtime_dir/CRAWL4AI_ADAPTER_VERSION" "$runtime_dir/RESEARCH_GATEWAY_VERSION"
rm -rf "$data_dir"
if [[ "$created_venv" == "true" ]]; then
  rm -rf "$venv_dir" "$browser_dir"
fi

# 审计状态保留在 adapter state/logs 中，不包含 cookie、密码、token 或 Chrome profile 内容。
python3 - "$install_state" "$created_venv" "$log_file" <<'PY'
import json
import sys
from pathlib import Path

state = {
    "schema_version": "1.0",
    "adapter_version": "2.3.27.1-crawl4ai.1",
    "status": "rolled_back",
    "created_venv": sys.argv[2].lower() == "true",
    "read_only": True,
    "chrome_profile_access": False,
    "rollback_log": sys.argv[3],
}
Path(sys.argv[1]).write_text(
    json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

# 恢复后只验证既有 Gateway 能启动；不会触发 Scrapling 安装、账号登录或浏览器状态修改。
if [[ -x "$gateway_root/bin/picotoopet-research-gateway" ]]; then
  "$gateway_root/bin/picotoopet-research-gateway" --health >/dev/null
fi

printf '\nCrawl4AI Research Adapter 已回滚。\n'
printf 'Research Gateway 已恢复到 pre-Crawl4AI 接线文件。\n'
printf 'Scrapling、Mac Worker、Chrome 登录状态和其它 Research 工具未删除。\n'
printf 'Rollback log: %s\n' "$log_file"
