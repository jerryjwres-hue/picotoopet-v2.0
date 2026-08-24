#!/bin/bash
# 安装 PicotooPet Research Gateway；共享研究工具只绑定，package-owned Crawl4AI 使用独立私有 venv。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
payload_dir="$script_dir/payload"
install_root="${PICOTOOPET_RESEARCH_INSTALL_ROOT:-$HOME/Library/Application Support/PicotooPet/ResearchGateway}"
runtime_dir="$install_root/runtime"
bin_dir="$install_root/bin"
state_dir="$install_root/state"
crawl_root="${PICOTOOPET_CRAWL4AI_ROOT:-$HOME/.local/share/picotoopet/research/crawl4ai}"
crawl_venv="$crawl_root/venv"
crawl_runtime="$crawl_root/runtime"
crawl_bin="$crawl_root/bin"
crawl_browser="$crawl_root/ms-playwright"
crawl_data="$crawl_root/data"
skip_crawl4ai="${PICOTOOPET_SKIP_CRAWL4AI_INSTALL:-0}"

for file in gateway.py VERSION research_gateway/__init__.py research_gateway/crawler_adapter.py crawl4ai_runner.py CRAWL4AI_ADAPTER_VERSION; do
  if [[ ! -f "$payload_dir/$file" ]]; then
    echo "安装包损坏：缺少 payload/$file。" >&2
    exit 1
  fi
done

mkdir -p "$runtime_dir/research_gateway" "$bin_dir" "$state_dir"
install -m 0644 "$payload_dir/gateway.py" "$runtime_dir/gateway.py"
install -m 0644 "$payload_dir/VERSION" "$runtime_dir/VERSION"
install -m 0644 "$payload_dir/research_gateway/__init__.py" "$runtime_dir/research_gateway/__init__.py"
install -m 0644 "$payload_dir/research_gateway/crawler_adapter.py" "$runtime_dir/research_gateway/crawler_adapter.py"

cat > "$bin_dir/picotoopet-research-gateway" <<EOF
#!/bin/bash
set -euo pipefail
export PYTHONPATH="$runtime_dir\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 "$runtime_dir/gateway.py" "\$@"
EOF
chmod 755 "$bin_dir/picotoopet-research-gateway"

is_compatible_python() {
  local candidate="$1"
  [[ -x "$candidate" ]] || return 1
  "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 14) else 1)
PY
}

select_compatible_python() {
  local requested="${PICOTOOPET_PYTHON_BIN:-}"
  local candidate=""
  local resolved=""
  local candidates=()

  if [[ -n "$requested" ]]; then
    resolved="$(command -v "$requested" 2>/dev/null || true)"
    [[ -n "$resolved" ]] || resolved="$requested"
    candidates+=("$resolved")
  fi
  if [[ -x "$crawl_venv/bin/python" ]]; then
    candidates+=("$crawl_venv/bin/python")
  fi
  for name in python3.13 python3.12; do
    resolved="$(command -v "$name" 2>/dev/null || true)"
    [[ -z "$resolved" ]] || candidates+=("$resolved")
  done
  candidates+=(
    "/opt/homebrew/bin/python3.13"
    "/opt/homebrew/bin/python3.12"
    "/opt/homebrew/opt/python@3.13/bin/python3.13"
    "/opt/homebrew/opt/python@3.12/bin/python3.12"
    "/usr/local/bin/python3.13"
    "/usr/local/bin/python3.12"
    "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
    "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
  )
  resolved="$(command -v python3 2>/dev/null || true)"
  [[ -z "$resolved" ]] || candidates+=("$resolved")

  for candidate in "${candidates[@]}"; do
    if is_compatible_python "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

# Crawl4AI 属于 PicotooPet 自有 provider：只装进 ~/.local/share/picotoopet/research/crawl4ai，绝不进 Mac Core venv。
if [[ "$skip_crawl4ai" != "1" ]]; then
  if ! python_bin="$(select_compatible_python)"; then
    echo "Research Gateway 已写入，但 Crawl4AI 需要 Python 3.12-3.13；未找到兼容解释器，安装中止。" >&2
    echo "可设置 PICOTOOPET_PYTHON_BIN=/完整路径/python3 后重新运行。" >&2
    exit 1
  fi
  mkdir -p "$crawl_runtime" "$crawl_bin" "$crawl_data"
  if [[ ! -x "$crawl_venv/bin/python" ]]; then
    "$python_bin" -m venv "$crawl_venv"
    "$crawl_venv/bin/python" -m pip install "crawl4ai==0.9.2"
  fi
  crawl4ai_version="$($crawl_venv/bin/python - <<'PY'
from importlib import metadata
print(metadata.version("crawl4ai"))
PY
)"
  case "$crawl4ai_version" in
    0.9.*) ;;
    *)
      echo "Crawl4AI 私有环境版本不在批准的 0.9.x 范围：$crawl4ai_version" >&2
      exit 1
      ;;
  esac

  export PLAYWRIGHT_BROWSERS_PATH="$crawl_browser"
  if [[ ! -d "$crawl_browser" ]]; then
    "$crawl_venv/bin/python" -m playwright install chromium
  fi
  install -m 0644 "$payload_dir/crawl4ai_runner.py" "$crawl_runtime/crawl4ai_runner.py"
  install -m 0644 "$payload_dir/CRAWL4AI_ADAPTER_VERSION" "$crawl_runtime/CRAWL4AI_ADAPTER_VERSION"
  cat > "$crawl_bin/picotoopet-crawl4ai-provider" <<EOF
#!/bin/bash
set -euo pipefail
export PYTHONNOUSERSITE=1
export PLAYWRIGHT_BROWSERS_PATH="$crawl_browser"
export PICOTOOPET_CRAWL4AI_DATA_ROOT="$crawl_data"
exec "$crawl_venv/bin/python" "$crawl_runtime/crawl4ai_runner.py" "\$@"
EOF
  chmod 755 "$crawl_bin/picotoopet-crawl4ai-provider"
fi

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# 绑定状态仅记录布尔存在性；不执行认证写入，也不读取浏览器 cookie/token。
agent_reach=0
opencli=0
mcporter=0
gh_cli=0
yt_dlp=0
bili=0
curl_cli=0
scrapling=0
thunderbit=0
crawl4ai=0

if command -v agent-reach >/dev/null 2>&1; then agent_reach=1; fi
if command -v opencli >/dev/null 2>&1; then opencli=1; fi
if command -v mcporter >/dev/null 2>&1; then mcporter=1; fi
if command -v gh >/dev/null 2>&1; then gh_cli=1; fi
if command -v yt-dlp >/dev/null 2>&1; then yt_dlp=1; fi
if command -v bili >/dev/null 2>&1; then bili=1; fi
if command -v curl >/dev/null 2>&1; then curl_cli=1; fi
if [[ -x "$HOME/.local/bin/scrapling-mcp-local" ]]; then scrapling=1; fi
if [[ -d "$HOME/.codex/mcp-servers/thunderbit" ]]; then thunderbit=1; fi
if [[ -x "$crawl_bin/picotoopet-crawl4ai-provider" ]]; then crawl4ai=1; fi

cat > "$state_dir/bindings.json" <<EOF
{
  "agent_reach": $agent_reach,
  "opencli": $opencli,
  "mcporter": $mcporter,
  "gh": $gh_cli,
  "yt_dlp": $yt_dlp,
  "bili": $bili,
  "curl": $curl_cli,
  "scrapling_mcp_local": $scrapling,
  "thunderbit_mcp": $thunderbit,
  "crawl4ai_provider": $crawl4ai
}
EOF

"$bin_dir/picotoopet-research-gateway" --health

printf '\nPicotooPet Research Gateway 2.3.27.1 已更新：\n%s\n' "$bin_dir/picotoopet-research-gateway"
printf 'Crawl4AI 使用独立私有目录：%s\n' "$crawl_root"
printf '共享 Agent Reach/OpenCLI/Scrapling/Thunderbit 等只做绑定，不升级、不覆盖登录态。\n'
printf '请运行 VERIFY_RESEARCH_GATEWAY.command 做完整只读工具调用验证。\n'
