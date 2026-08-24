#!/bin/bash
# PicotooPet Research Gateway 完整只读实机验证；不会安装/升级工具，也不会读取或导出 Cookie/Token。
set -euo pipefail

install_root="${PICOTOOPET_RESEARCH_INSTALL_ROOT:-$HOME/Library/Application Support/PicotooPet/ResearchGateway}"
gateway="$install_root/bin/picotoopet-research-gateway"
crawl_root="${PICOTOOPET_CRAWL4AI_ROOT:-$HOME/.local/share/picotoopet/research/crawl4ai}"
crawl_provider="$crawl_root/bin/picotoopet-crawl4ai-provider"
verify_query="${PICOTOOPET_RESEARCH_VERIFY_QUERY:-OpenAI}"

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

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
  # 只保留首行诊断，不把可能含用户内容的完整外部输出写入验证报告。
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

# 共享依赖：只验证存在性，不安装、不升级、不改登录态。
for tool in agent-reach opencli mcporter gh yt-dlp bili curl; do
  if command -v "$tool" >/dev/null 2>&1; then
    pass "tool:$tool"
  else
    fail "tool:$tool" "missing"
  fi
done

# Doctor/Auth 只读检查。
if command -v opencli >/dev/null 2>&1; then
  run_quiet "opencli-doctor" opencli doctor || true
fi
if command -v agent-reach >/dev/null 2>&1; then
  run_quiet "agent-reach-doctor" agent-reach doctor || true
fi
if command -v gh >/dev/null 2>&1; then
  run_quiet "github-auth" gh auth status || true
fi

# Research Gateway 真实调用链：每个 smoke 都是只读、限量、公共资料。
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

# Crawl4AI 直接 smoke，确保不是只存在文件而无法实际抓公共页面。
if [[ -x "$crawl_provider" ]]; then
  run_quiet "crawl4ai-public-page" \
    "$crawl_provider" --url https://example.com \
    --timeout-seconds 20 --max-content-bytes 65536 --redirect-limit 3 --retry-limit 0 || true
else
  fail "crawl4ai-public-page" "private provider missing"
fi

# Scrapling 通过正式 Gateway 路由执行，验证 mcporter + Scrapling 接线。
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

# OpenCLI 社区/社媒后端逐一做只读 1 条查询；失败会明确指出具体平台。
if command -v opencli >/dev/null 2>&1; then
  for platform in reddit twitter xiaohongshu facebook instagram xueqiu; do
    run_quiet "social:$platform" \
      "$gateway" --capability research.social.search \
      --params-json "{\"platform\":\"$platform\",\"query\":\"$verify_query\",\"limit\":1}" || true
  done
fi

# Thunderbit 会消耗 credits：只验证本地绑定，绝不为了 smoke 自动花钱。
if [[ -d "$HOME/.codex/mcp-servers/thunderbit" ]]; then
  pass "thunderbit-binding" "paid smoke intentionally skipped"
  skip "thunderbit-paid-call" "需要显式付费批准"
else
  fail "thunderbit-binding" "missing"
fi

# Amazon/TikTok 评论采集属于已登录 Browser Bridge，而不是无会话 Crawl4AI。
# opencli doctor/各平台只读查询负责验证 Bridge/渠道可用性；Core 永不读取 Cookie。
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
