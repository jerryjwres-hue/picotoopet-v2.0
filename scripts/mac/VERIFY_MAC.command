#!/bin/bash
# 验证数据库、API、launchd 和 gpt-oss:20b 常驻状态；失败时仍展示完整报告。
set -uo pipefail

ROOT="$HOME/Library/Application Support/PicotooPetV2"
CORE="$ROOT/current/.venv/bin/picotoopet-core"
STATE_DIR="$ROOT/state"
REPORT="$STATE_DIR/verification-$(date +%Y%m%d-%H%M%S).txt"
OVERALL=0
API_PORT="8765"

mkdir -p "$STATE_DIR"
if [ -f "$STATE_DIR/api-port.txt" ]; then
  API_PORT="$(cat "$STATE_DIR/api-port.txt")"
fi

run_check() {
  local label="$1"
  shift

  echo "===== ${label} ====="
  if "$@"; then
    echo "[PASS] ${label}"
  else
    local exit_code=$?
    echo "[FAIL] ${label}（退出码：${exit_code}）"
    OVERALL=1
  fi
  echo
}

check_launch_running() {
  local label="$1"
  local output

  output="$(launchctl print "gui/$UID/${label}" 2>&1)" || {
    printf '%s\n' "${output}"
    return 1
  }
  printf '%s\n' "${output}"
  printf '%s\n' "${output}" | grep -Fq "state = running"
}

{
  echo "Picotoo Pet V2 Mac 验证"
  echo "报告时间：$(date -u +%FT%TZ)"
  echo "运行目录：$ROOT"
  echo "API 端口：$API_PORT"
  echo

  if [ -x "$CORE" ]; then
    run_check "Mac Core health" "$CORE" health
    run_check "resident-check" "$CORE" resident-check
  else
    echo "===== Mac Core 可执行文件 ====="
    echo "[FAIL] 未找到或不可执行：$CORE"
    echo
    OVERALL=1
  fi

  run_check \
    "launchctl mac-core running" \
    check_launch_running "com.picotoopet.mac-core"
  run_check \
    "launchctl health-supervisor running" \
    check_launch_running "com.picotoopet.health-supervisor"
  run_check \
    "API health" \
    curl --fail --silent --show-error --connect-timeout 3 --max-time 10 \
      "http://127.0.0.1:${API_PORT}/api/v1/health"

  if [ "$OVERALL" -eq 0 ]; then
    echo "FINAL_STATUS=PASS"
  else
    echo "FINAL_STATUS=FAIL"
  fi
} > "$REPORT" 2>&1

printf '验证报告已生成：%s\n' "$REPORT"
if [ "$OVERALL" -eq 0 ]; then
  echo "验证结果：PASS"
else
  echo "验证结果：FAIL；报告中已列出具体失败项。"
fi

# 优先打开报告；若系统没有文本关联程序，则在 Finder 中定位文件。
open "$REPORT" >/dev/null 2>&1 || open -R "$REPORT" >/dev/null 2>&1 || true
exit "$OVERALL"
