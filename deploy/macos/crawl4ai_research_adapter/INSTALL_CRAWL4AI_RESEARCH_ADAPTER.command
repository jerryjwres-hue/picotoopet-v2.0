#!/bin/bash
# 安装 PicotooPet Crawl4AI Research Adapter；只修改独立 adapter 目录和既有 Research Gateway 接线文件。
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
gateway_module_dir="$gateway_runtime/research_gateway"
worker_runtime="${PICOTOO_RUNTIME_ROOT_OVERRIDE:-$HOME/Library/Application Support/PicotooPetV2}"
worker_plist="$HOME/Library/LaunchAgents/com.picotoopet.worker.plist"
backup_gateway="$state_dir/gateway.py.pre-crawl4ai"
install_state="$state_dir/install-state.json"
created_venv=false
created_venv_this_run=false
patched_gateway=false

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "此安装包仅支持 macOS。" >&2
  exit 1
fi
test "$(uname -m)" = "arm64"

for file in gateway.py crawler_adapter.py crawl4ai_runner.py VERSION CRAWL4AI_ADAPTER_VERSION; do
  if [[ ! -f "$payload_dir/$file" ]]; then
    echo "安装包损坏：缺少 payload/$file" >&2
    exit 1
  fi
done

is_compatible_python() {
  local candidate="$1"
  [[ -x "$candidate" ]] || return 1
  "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 14) else 1)
PY
}

select_compatible_python() {
  # macOS 自带 /usr/bin/python3 可能仍是 3.9；必须验证版本，而不是拿 PATH 中第一个 python3。
  local requested="${PICOTOOPET_PYTHON_BIN:-}"
  local resolved=""
  local candidate=""
  local legacy_python3_path=""
  local seen="|"
  local candidates=()

  if [[ -n "$requested" ]]; then
    resolved="$(command -v "$requested" 2>/dev/null || true)"
    if [[ -z "$resolved" && -x "$requested" ]]; then
      resolved="$requested"
    fi
    if [[ -n "$resolved" ]]; then
      candidates+=("$resolved")
    fi
  fi

  # 重复安装时优先复用 adapter 自己已经验证过的私有 venv，不依赖共享 Python 顺序。
  if [[ -x "$venv_dir/bin/python" ]]; then
    candidates+=("$venv_dir/bin/python")
  fi

  for name in python3.13 python3.12; do
    resolved="$(command -v "$name" 2>/dev/null || true)"
    if [[ -n "$resolved" ]]; then
      candidates+=("$resolved")
    fi
  done

  # Apple Silicon Homebrew、Intel/Homebrew 兼容路径与 python.org Framework 常见安装位置。
  candidates+=(
    "/opt/homebrew/bin/python3.13"
    "/opt/homebrew/bin/python3.12"
    "/opt/homebrew/opt/python@3.13/bin/python3.13"
    "/opt/homebrew/opt/python@3.12/bin/python3.12"
    "/usr/local/bin/python3.13"
    "/usr/local/bin/python3.12"
    "/usr/local/opt/python@3.13/bin/python3.13"
    "/usr/local/opt/python@3.12/bin/python3.12"
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
  )

  # 最后才尝试通用 python3；它必须通过同一版本门禁，系统 3.9 不会被误选。
  legacy_python3_path="$(command -v python3 2>/dev/null || true)"
  if [[ -n "$legacy_python3_path" ]]; then
    candidates+=("$legacy_python3_path")
  fi

  for candidate in "${candidates[@]}"; do
    [[ -n "$candidate" ]] || continue
    case "$seen" in
      *"|$candidate|"*) continue ;;
    esac
    seen="${seen}${candidate}|"
    if is_compatible_python "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

# 前置检测：只读取现状，不升级 Python、Docker、Scrapling、Research Gateway 或 Mac Worker。
if ! python_bin="$(select_compatible_python)"; then
  current_python="$(command -v python3 2>/dev/null || true)"
  current_version="unknown"
  if [[ -n "$current_python" ]]; then
    current_version="$($current_python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || printf 'unknown')"
  fi
  echo "未找到兼容 Python 3.12-3.13。" >&2
  if [[ -n "$current_python" ]]; then
    echo "当前 PATH 的 python3：${current_python}（${current_version}）" >&2
  fi
  echo "已检查 python3.13、python3.12、Homebrew 与 python.org Framework 常见路径。" >&2
  echo "如已安装在其它位置，可设置 PICOTOOPET_PYTHON_BIN=/完整路径/python3 后重试。" >&2
  echo "本包不会替你安装、升级或覆盖系统 Python。" >&2
  exit 1
fi
python_version="$($python_bin -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
docker_path="$(command -v docker 2>/dev/null || true)"
scrapling_path="$(command -v scrapling-mcp-local 2>/dev/null || true)"
if [[ -z "$scrapling_path" && -x "$HOME/.local/bin/scrapling-mcp-local" ]]; then
  scrapling_path="$HOME/.local/bin/scrapling-mcp-local"
fi

if [[ ! -f "$gateway_runtime/gateway.py" || ! -f "$gateway_runtime/VERSION" ]]; then
  echo "未检测到现有 ResearchGateway runtime：$gateway_runtime" >&2
  echo "请先保留并安装当前 PicotooPet Research Gateway；本包不会重装它。" >&2
  exit 1
fi
existing_gateway_version="$(tr -d '\r\n' < "$gateway_runtime/VERSION")"
if [[ "$existing_gateway_version" != "2.3.27.1" ]]; then
  echo "ResearchGateway 版本不兼容：$existing_gateway_version；要求 2.3.27.1。" >&2
  exit 1
fi

worker_detected=0
if [[ -d "$worker_runtime" || -f "$worker_plist" ]]; then
  worker_detected=1
fi
scrapling_detected=0
if [[ -n "$scrapling_path" ]]; then
  scrapling_detected=1
fi
docker_detected=0
if [[ -n "$docker_path" ]]; then
  docker_detected=1
fi

mkdir -p "$runtime_dir" "$bin_dir" "$state_dir" "$logs_dir" "$data_dir"
log_file="$logs_dir/install-$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(tee -a "$log_file") 2>&1

echo "PicotooPet Crawl4AI Research Adapter 安装开始"
echo "Python: $python_bin ($python_version)"
echo "Docker detected: $docker_detected"
echo "Scrapling detected: $scrapling_detected"
echo "ResearchGateway: $gateway_runtime"
echo "Mac Worker detected: $worker_detected"

# Python 版本门禁：与 PicotooPet Research runtime 对齐；只检测 3.12/3.13，不安装或升级 Python。
"$python_bin" - <<'PY'
import sys
if not ((3, 12) <= sys.version_info[:2] < (3, 14)):
    raise SystemExit(
        f"需要 Python 3.12-3.13；当前为 {sys.version_info.major}.{sys.version_info.minor}"
    )
PY

# 重复安装继承首次安装的 venv 所有权；不能把 true 覆盖成 false 而破坏 rollback。
if [[ -f "$install_state" ]]; then
  previous_created="$($python_bin - "$install_state" <<'PY'
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
  if [[ "$previous_created" == "true" ]]; then
    created_venv=true
  fi
fi

cleanup_failed_install() {
  local code=$?
  trap - ERR
  if [[ "$patched_gateway" == "true" && -f "$backup_gateway" ]]; then
    install -m 0644 "$backup_gateway" "$gateway_runtime/gateway.py" || true
    rm -f "$gateway_module_dir/crawler_adapter.py" || true
    rmdir "$gateway_module_dir" 2>/dev/null || true
  fi
  if [[ "$created_venv_this_run" == "true" ]]; then
    rm -rf "$venv_dir" "$browser_dir"
  fi
  echo "安装失败，已撤回本次 Crawl4AI adapter 变更；Scrapling、ResearchGateway 目录和 Mac Worker 未删除。" >&2
  exit "$code"
}
trap cleanup_failed_install ERR

# 私有 venv：第一次安装固定 0.9.2；重复安装只绑定已有兼容 0.9.x，不执行 upgrade。
if [[ ! -e "$venv_dir" ]]; then
  "$python_bin" -m venv "$venv_dir"
  created_venv=true
  created_venv_this_run=true
  export PLAYWRIGHT_BROWSERS_PATH="$browser_dir"
  "$venv_dir/bin/python" -m pip install "crawl4ai==0.9.2"
  "$venv_dir/bin/python" -m playwright install chromium
elif [[ ! -x "$venv_dir/bin/python" ]]; then
  echo "adapter venv 已存在但不完整：$venv_dir；为避免覆盖未知环境，安装中止。" >&2
  exit 1
fi

# Gateway 的早期 bootstrap 固定跳转到这个解释器，因此私有 venv 本身也必须满足项目 Python 门禁。
if ! is_compatible_python "$venv_dir/bin/python"; then
  echo "adapter 私有 venv Python 版本不兼容；必须为 3.12-3.13：$venv_dir/bin/python" >&2
  exit 1
fi

crawl4ai_version="$($venv_dir/bin/python - <<'PY'
import importlib.metadata
try:
    print(importlib.metadata.version("crawl4ai"))
except importlib.metadata.PackageNotFoundError:
    raise SystemExit(1)
PY
)"
if [[ ! "$crawl4ai_version" =~ ^0\.9\.[0-9]+([.+-].*)?$ ]]; then
  echo "现有隔离环境 Crawl4AI 版本不在批准的 0.9.x 范围：$crawl4ai_version" >&2
  echo "本安装器不会自动升级或降级已有环境。" >&2
  exit 1
fi

# 浏览器依赖必须位于 adapter 私有目录；绝不调用系统 Chrome，也不读取 Chrome profile/cookies。
export PLAYWRIGHT_BROWSERS_PATH="$browser_dir"
if [[ ! -d "$browser_dir" ]]; then
  if [[ "$created_venv" == "true" ]]; then
    "$venv_dir/bin/python" -m playwright install chromium
  else
    echo "外部提供的 adapter venv 缺少私有 Playwright Chromium：$browser_dir" >&2
    echo "为避免修改未知旧环境，安装中止。" >&2
    exit 1
  fi
fi

# 首次接线只备份原始 Gateway；重复安装保留同一份 pre-Crawl4AI 基线以支持真正 rollback。
if [[ ! -f "$backup_gateway" ]]; then
  install -m 0644 "$gateway_runtime/gateway.py" "$backup_gateway"
fi
install -m 0644 "$payload_dir/gateway.py" "$gateway_runtime/gateway.py"
# 正式 Gateway 是 flat runtime/gateway.py；创建固定同目录 package 子目录满足 research_gateway.crawler_adapter 导入。
mkdir -p "$gateway_module_dir"
install -m 0644 "$payload_dir/crawler_adapter.py" "$gateway_module_dir/crawler_adapter.py"
patched_gateway=true

install -m 0644 "$payload_dir/crawl4ai_runner.py" "$runtime_dir/crawl4ai_runner.py"
install -m 0644 "$payload_dir/CRAWL4AI_ADAPTER_VERSION" "$runtime_dir/CRAWL4AI_ADAPTER_VERSION"
install -m 0644 "$payload_dir/VERSION" "$runtime_dir/RESEARCH_GATEWAY_VERSION"

cat > "$bin_dir/picotoopet-crawl4ai-provider" <<EOF
#!/bin/bash
# 运行 adapter 私有 Crawl4AI；禁用用户 site-packages 并固定私有 Chromium/Data 目录。
set -euo pipefail
export PYTHONNOUSERSITE=1
export PLAYWRIGHT_BROWSERS_PATH="$browser_dir"
export PICOTOOPET_CRAWL4AI_DATA_ROOT="$data_dir"
export CRAWL4_AI_BASE_DIRECTORY="$data_dir"
exec "$venv_dir/bin/python" "$runtime_dir/crawl4ai_runner.py" "\$@"
EOF
chmod 755 "$bin_dir/picotoopet-crawl4ai-provider"

# 安装状态只记录版本/路径/布尔检测结果，不记录 cookie、密码、token 或浏览器登录信息。
"$python_bin" - "$install_state" "$crawl4ai_version" "$created_venv" "$scrapling_detected" "$worker_detected" "$docker_detected" "$log_file" <<'PY'
import json
import sys
from pathlib import Path

state = {
    "schema_version": "1.0",
    "adapter_version": "2.3.27.1-crawl4ai.4",
    "crawl4ai_version": sys.argv[2],
    "created_venv": sys.argv[3].lower() == "true",
    "scrapling_detected": sys.argv[4] == "1",
    "mac_worker_detected": sys.argv[5] == "1",
    "docker_detected": sys.argv[6] == "1",
    "gateway_private_python_bootstrap": True,
    "read_only": True,
    "chrome_profile_access": False,
    "captcha_bypass": False,
    "install_log": sys.argv[7],
}
Path(sys.argv[1]).write_text(
    json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

# 最终健康检查：现有 wrapper 即使解析到旧系统 Python，也会由 adapter Gateway 早期切换到私有兼容 Python。
"$gateway_root/bin/picotoopet-research-gateway" --health >/dev/null
"$bin_dir/picotoopet-crawl4ai-provider" --version >/dev/null

trap - ERR
printf '\n安装完成：PicotooPet Crawl4AI Research Adapter\n'
printf 'Crawl4AI: %s\n' "$crawl4ai_version"
printf 'Adapter root: %s\n' "$adapter_root"
printf 'Install log: %s\n' "$log_file"
printf '现有 Scrapling、ResearchGateway、Mac Worker 与 Chrome 登录状态均未被升级或删除。\n'
printf '下一步运行 VERIFY_CRAWL4AI_RESEARCH_ADAPTER.command。\n'