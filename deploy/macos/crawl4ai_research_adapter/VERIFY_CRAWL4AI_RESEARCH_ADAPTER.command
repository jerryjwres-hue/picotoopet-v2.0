#!/bin/bash
# 验证 adapter 安装、真实静态/JS 页面、Markdown/metadata 与受控失败；不做账号登录或写操作。
set -euo pipefail

adapter_root="${PICOTOOPET_CRAWL4AI_ROOT:-$HOME/.local/share/picotoopet/research/crawl4ai}"
bin_dir="$adapter_root/bin"
state_dir="$adapter_root/state"
logs_dir="$adapter_root/logs"
evidence_dir="$adapter_root/verification"
gateway_root="${PICOTOOPET_RESEARCH_INSTALL_ROOT:-$HOME/Library/Application Support/PicotooPet/ResearchGateway}"
provider="$bin_dir/picotoopet-crawl4ai-provider"
install_state="$state_dir/install-state.json"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "此验证入口仅支持 macOS。" >&2
  exit 1
fi
test "$(uname -m)" = "arm64"

mkdir -p "$logs_dir" "$evidence_dir"
log_file="$logs_dir/verify-$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(tee -a "$log_file") 2>&1

if [[ ! -x "$provider" ]]; then
  echo "Crawl4AI provider 不存在或不可执行：$provider" >&2
  exit 1
fi
if [[ ! -f "$install_state" ]]; then
  echo "缺少安装状态：$install_state" >&2
  exit 1
fi
if [[ ! -x "$gateway_root/bin/picotoopet-research-gateway" ]]; then
  echo "现有 Research Gateway wrapper 不存在。" >&2
  exit 1
fi

# 基础健康：版本必须仍在批准 0.9.x；Gateway 保持原有只读健康接口。
crawl4ai_version="$($provider --version)"
if [[ ! "$crawl4ai_version" =~ ^0\.9\.[0-9]+([.+-].*)?$ ]]; then
  echo "Crawl4AI 版本超出批准范围：$crawl4ai_version" >&2
  exit 1
fi
"$gateway_root/bin/picotoopet-research-gateway" --health > "$evidence_dir/gateway-health.json"

run_success_fixture() {
  local label="$1"
  local url="$2"
  local javascript="$3"
  local output="$evidence_dir/$label.json"
  local args=(
    --url "$url"
    --timeout-seconds 30
    --max-content-bytes 262144
    --redirect-limit 5
    --retry-limit 1
  )
  if [[ "$javascript" == "true" ]]; then
    args+=(--javascript)
  fi
  "$provider" "${args[@]}" > "$output"
  python3 - "$output" <<'PY'
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("ok") is not True:
    raise SystemExit(f"fixture failed: {payload}")
for key in ("title", "url", "source", "markdown"):
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"missing non-empty field: {key}")
if not payload["url"].startswith(("http://", "https://")):
    raise SystemExit("result URL is not HTTP(S)")
if payload["source"] != (urlparse(payload["url"]).hostname or ""):
    raise SystemExit("source metadata does not match result URL hostname")
if len(payload["markdown"].encode("utf-8")) > 262_144:
    raise SystemExit("markdown exceeds configured content bound")
PY
}

run_failure_fixture() {
  local label="$1"
  local expected="$2"
  shift 2
  local output="$evidence_dir/$label.json"
  set +e
  "$provider" "$@" > "$output" 2>> "$log_file"
  local code=$?
  set -e
  if [[ "$code" -eq 0 ]]; then
    echo "失败 fixture 意外成功：$label" >&2
    exit 1
  fi
  python3 - "$output" "$expected" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("ok") is not False or payload.get("error") != sys.argv[2]:
    raise SystemExit(f"unexpected controlled failure: {payload}")
PY
}

# 真实网络 fixture：普通静态网页 + JS 渲染网页，均通过独立 Chromium context 读取。
run_success_fixture "static-example" "https://example.com/" "false"
run_success_fixture "javascript-quotes" "https://quotes.toscrape.com/js/" "true"

# 真实受控失败：HTTP 404、真实延迟超时、DNS 网络失败与超大正文。
run_failure_fixture \
  "not-found" \
  "not_found" \
  --url "https://www.rfc-editor.org/rfc/rfc999999.html" \
  --timeout-seconds 30 \
  --max-content-bytes 262144 \
  --redirect-limit 5 \
  --retry-limit 0
run_failure_fixture \
  "timeout" \
  "timeout" \
  --url "https://httpbin.org/delay/5" \
  --timeout-seconds 1 \
  --max-content-bytes 262144 \
  --redirect-limit 5 \
  --retry-limit 0
run_failure_fixture \
  "network-failure" \
  "network_failed" \
  --url "https://picotoopet-crawl4ai.invalid/" \
  --timeout-seconds 5 \
  --max-content-bytes 262144 \
  --redirect-limit 5 \
  --retry-limit 1
run_failure_fixture \
  "content-limit" \
  "content_limit_exceeded" \
  --url "https://www.rfc-editor.org/rfc/rfc9110.html" \
  --timeout-seconds 30 \
  --max-content-bytes 1024 \
  --redirect-limit 5 \
  --retry-limit 0

# 如果现有 Scrapling 可见，仅做只读 reachability 探测；不升级、不执行 stealth、不改变登录态。
scrapling_status="not_detected"
if command -v mcporter >/dev/null 2>&1 && {
  command -v scrapling-mcp-local >/dev/null 2>&1 || [[ -x "$HOME/.local/bin/scrapling-mcp-local" ]];
}; then
  set +e
  mcporter call scrapling.get \
    url=https://example.com/ \
    extraction_type=markdown \
    main_content_only=true > "$evidence_dir/scrapling-read.txt" 2>> "$log_file"
  scrapling_code=$?
  set -e
  if [[ "$scrapling_code" -eq 0 ]]; then
    scrapling_status="read_ok"
  else
    scrapling_status="detected_but_read_failed"
  fi
fi

python3 - "$evidence_dir/verification-summary.json" "$crawl4ai_version" "$scrapling_status" "$log_file" <<'PY'
import json
import sys
from pathlib import Path

summary = {
    "schema_version": "1.0",
    "status": "pass",
    "crawl4ai_version": sys.argv[2],
    "static_page": "pass",
    "javascript_page": "pass",
    "markdown_and_metadata": "pass",
    "not_found": "pass",
    "timeout": "pass",
    "network_failure": "pass",
    "content_limit": "pass",
    "scrapling_reachability": sys.argv[3],
    "max_pages": 3,
    "max_depth": 0,
    "timeout_seconds": 30,
    "max_content_bytes": 262144,
    "redirect_limit": 5,
    "concurrency": 2,
    "retry_limit": 1,
    "captcha_bypass": False,
    "account_login": False,
    "chrome_profile_access": False,
    "log": sys.argv[4],
}
Path(sys.argv[1]).write_text(
    json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

printf '\nCRAWL4AI_RESEARCH_ADAPTER_VERIFY=PASS\n'
printf 'Crawl4AI: %s\n' "$crawl4ai_version"
printf 'Evidence: %s\n' "$evidence_dir/verification-summary.json"
printf 'Scrapling reachability: %s\n' "$scrapling_status"
printf '本验证没有登录账号、读取 Chrome cookies/token、执行 CAPTCHA 绕过或账号写操作。\n'
