#!/bin/bash
# PicotooPet Research Gateway 验证器：install-contract 验安装；full 再验证共享外部工具与在线调用。
set -euo pipefail

install_root="${PICOTOOPET_RESEARCH_INSTALL_ROOT:-$HOME/Library/Application Support/PicotooPet/ResearchGateway}"
gateway="$install_root/bin/picotoopet-research-gateway"
crawl_root="${PICOTOOPET_CRAWL4AI_ROOT:-$HOME/.local/share/picotoopet/research/crawl4ai}"
crawl_provider="$crawl_root/bin/picotoopet-crawl4ai-provider"
verify_query="${PICOTOOPET_RESEARCH_VERIFY_QUERY:-OpenAI}"
verify_mode="full"

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --mode)
      [[ "$#" -ge 2 ]] || { echo "--mode 缺少参数" >&2; exit 2; }
      verify_mode="$2"
      shift 2
      ;;
    *)
      echo "未知参数：$1" >&2
      exit 2
      ;;
  esac
done

case "$verify_mode" in
  full|install-contract) ;;
  *)
    echo "不支持的验证模式：$verify_mode；允许 full 或 install-contract。" >&2
    exit 2
    ;;
esac

failures=0
passes=0
skips=0

pass() {
  printf 'PASS %-32s %s\n' "$1" "${2:-}"
  passes=$((passes + 1))
}

fail() {
  printf 'FAIL %-32s %s\n' "$1" "${2:-}" >&2
  failures=$((failures + 1))
}

skip() {
  printf 'SKIP %-32s %s\n' "$1" "${2:-}"
  skips=$((skips + 1))
}

run_quiet() {
  local label="$1"
  shift
  local output
  if output="$("$@" 2>&1)"; then
    pass "$label"
    return 0
  fi
  # 诊断边界：只保留首行且截断，避免把用户内容、Cookie 或 Token 写进验证报告。
  fail "$label" "$(printf '%s' "$output" | head -n 1 | cut -c1-240)"
  return 1
}

if [[ ! -x "$gateway" ]]; then
  echo "FAIL gateway-installed Research Gateway 尚未安装：$gateway" >&2
  exit 1
fi

health_file="$(mktemp "${TMPDIR:-/tmp}/picotoopet-research-health.XXXXXX")"
cleanup() {
  rm -f "$health_file"
}
trap cleanup EXIT

# 安装合同：Gateway 自身必须可启动，并返回冻结版本/只读能力边界。
if "$gateway" --health > "$health_file"; then
  pass "gateway-health"
else
  fail "gateway-health" "--health 执行失败"
fi

if python3 - "$health_file" <<'PY' >/dev/null 2>&1
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload["version"] == "2.3.27.1"
assert payload["read_only"] is True
assert payload["xiaoyuzhou_enabled"] is False
assert isinstance(payload.get("tools"), dict)
assert isinstance(payload.get("crawl4ai"), dict)
assert isinstance(payload.get("browser_bridge"), dict)
PY
then
  pass "gateway-contract" "2.3.27.1 read-only"
else
  fail "gateway-contract" "版本/只读健康合同不一致"
fi

# 安装合同：package-owned Crawl4AI 必须存在且能在不联网、不启动浏览器时完成版本查询。
if [[ -x "$crawl_provider" ]]; then
  run_quiet "crawl4ai-provider-version" "$crawl_provider" --version || true
else
  fail "crawl4ai-provider-version" "private provider missing"
fi

if [[ "$verify_mode" == "install-contract" ]]; then
  # 共享健康分层：这些工具不归 PicotooPet 安装器所有，缺失/未登录/平台离线均不得反向判定安装失败。
  for tool in agent-reach opencli mcporter gh yt-dlp bili curl; do
    if command -v "$tool" >/dev/null 2>&1; then
      pass "shared-health:$tool" "present; live check deferred"
    else
      skip "shared-health:$tool" "not required for install contract"
    fi
  done

  if [[ -d "$HOME/.codex/mcp-servers/thunderbit" ]]; then
    pass "shared-health:thunderbit" "binding present; paid call deferred"
  else
    skip "shared-health:thunderbit" "not required for install contract"
  fi

  if [[ "$failures" -eq 0 ]]; then
    echo "RESEARCH_GATEWAY_INSTALL_CONTRACT=PASS"
    echo "RESEARCH_SHARED_HEALTH=NOT_REQUIRED"
    echo "PASSES=$passes SKIPS=$skips FAILURES=0"
    exit 0
  fi

  echo "RESEARCH_GATEWAY_INSTALL_CONTRACT=FAIL" >&2
  echo "PASSES=$passes SKIPS=$skips FAILURES=$failures" >&2
  exit 1
fi

# full 模式：以下均为共享工具/账号/网络健康检查，保持严格失败语义供人工诊断。
for tool in agent-reach opencli mcporter gh yt-dlp bili curl; do
  if command -v "$tool" >/dev/null 2>&1; then
    pass "tool:$tool"
  else
    fail "tool:$tool" "missing"
  fi
done

if command -v opencli >/dev/null 2>&1; then
  run_quiet "opencli-doctor" opencli doctor || true
fi
if command -v agent-reach >/dev/null 2>&1; then
  run_quiet "agent-reach-doctor" agent-reach doctor || true
fi
if command -v gh >/dev/null 2>&1; then
  run_quiet "github-auth" gh auth status || true
fi

if command -v mcporter >/dev/null 2>&1; then
  run_quiet "research.search/exa" \
    "$gateway" --capability research.search \
    --params-json "{\"query\":\"$verify_query\",\"limit\":1}" || true
else
  fail "research.search/exa" "mcporter missing"
fi

if command -v curl >/dev/null 2>&1; then
  run_quiet "research.web.read" \
    "$gateway" --capability research.web.read \
    --params-json '{"url":"https://example.com"}' || true
fi

if [[ -x "$crawl_provider" ]]; then
  run_quiet "crawl4ai-public-page" \
    "$crawl_provider" --url https://example.com \
    --timeout-seconds 20 --max-content-bytes 65536 --redirect-limit 3 --retry-limit 0 || true
else
  fail "crawl4ai-public-page" "private provider missing"
fi

if command -v mcporter >/dev/null 2>&1; then
  run_quiet "scrapling-static-crawl" \
    "$gateway" --capability research.web.crawl \
    --params-json '{"url":"https://example.com","mode":"static"}' || true
fi

if command -v gh >/dev/null 2>&1; then
  run_quiet "github-search" \
    "$gateway" --capability research.github.search \
    --params-json '{"query":"openai","kind":"repos","limit":1}' || true
fi

if command -v yt-dlp >/dev/null 2>&1; then
  run_quiet "youtube-search" \
    "$gateway" --capability research.video.search \
    --params-json '{"platform":"youtube","query":"OpenAI","limit":1}' || true
fi

if command -v opencli >/dev/null 2>&1; then
  for platform in reddit twitter xiaohongshu facebook instagram xueqiu; do
    run_quiet "social:$platform" \
      "$gateway" --capability research.social.search \
      --params-json "{\"platform\":\"$platform\",\"query\":\"$verify_query\",\"limit\":1}" || true
  done
fi

# Thunderbit 会消耗 credits：full 模式也只检查绑定，不自动付费调用。
if [[ -d "$HOME/.codex/mcp-servers/thunderbit" ]]; then
  pass "thunderbit-binding" "paid smoke intentionally skipped"
  skip "thunderbit-paid-call" "需要显式付费批准"
else
  fail "thunderbit-binding" "missing"
fi

if [[ "$failures" -eq 0 ]]; then
  echo "RESEARCH_GATEWAY_VERIFY=PASS"
  echo "RESEARCH_TOOL_CALLS=PASS"
  echo "PASSES=$passes SKIPS=$skips FAILURES=0"
  exit 0
fi

echo "RESEARCH_GATEWAY_VERIFY=FAIL" >&2
echo "RESEARCH_TOOL_CALLS=FAIL" >&2
echo "PASSES=$passes SKIPS=$skips FAILURES=$failures" >&2
exit 1
