#!/bin/bash
# 将 Picotoo Pet V2 Mac Core 从已占用的 8765 安全迁移到 8766；不修改旧服务。
set -uo pipefail

ROOT="$HOME/Library/Application Support/PicotooPetV2"
STATE_DIR="$ROOT/state"
LOG_DIR="$ROOT/logs"
PLIST="$HOME/Library/LaunchAgents/com.picotoopet.mac-core.plist"
CORE="$ROOT/current/.venv/bin/picotoopet-core"
TARGET_PORT="8766"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$ROOT/backups/port-conflict-${STAMP}"
REPORT="$STATE_DIR/port-repair-${STAMP}.txt"
TMP_BODY="$(mktemp -t picotoopet-port-repair.XXXXXX)"
OVERALL=0
ROLLED_BACK=0

mkdir -p "$STATE_DIR" "$LOG_DIR" "$BACKUP_DIR"
trap 'rm -f "$TMP_BODY"' EXIT

write_report_header() {
  printf 'Picotoo Pet V2 Mac 端口冲突修复\n'
  printf '报告时间：%s\n' "$(date -u +%FT%TZ)"
  printf '目标端口：%s\n' "$TARGET_PORT"
  printf '备份目录：%s\n\n' "$BACKUP_DIR"
}

restore_previous_configuration() {
  launchctl bootout "gui/$UID/com.picotoopet.mac-core" >/dev/null 2>&1 || true
  if [ -f "$BACKUP_DIR/com.picotoopet.mac-core.plist" ]; then
    cp "$BACKUP_DIR/com.picotoopet.mac-core.plist" "$PLIST"
  fi
  if [ -f "$BACKUP_DIR/api-port.txt" ]; then
    cp "$BACKUP_DIR/api-port.txt" "$STATE_DIR/api-port.txt"
  else
    rm -f "$STATE_DIR/api-port.txt"
  fi
  launchctl bootstrap "gui/$UID" "$PLIST" >/dev/null 2>&1 || true
  ROLLED_BACK=1
}

{
  write_report_header

  if [ ! -x "$CORE" ]; then
    printf '[FAIL] 未找到 Mac Core：%s\n' "$CORE"
    OVERALL=1
  fi
  if [ ! -f "$PLIST" ]; then
    printf '[FAIL] 未找到 launchd 配置：%s\n' "$PLIST"
    OVERALL=1
  fi

  printf '===== 8765 当前监听者（只读记录）=====\n'
  /usr/sbin/lsof -nP -iTCP:8765 -sTCP:LISTEN 2>&1 || true
  printf '\n'

  printf '===== 8766 可用性 =====\n'
  if /usr/sbin/lsof -nP -iTCP:"$TARGET_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    printf '[FAIL] 端口 %s 已被其他程序占用。\n' "$TARGET_PORT"
    OVERALL=1
  else
    printf '[PASS] 端口 %s 可用。\n' "$TARGET_PORT"
  fi
  printf '\n'

  if [ "$OVERALL" -eq 0 ]; then
    cp "$PLIST" "$BACKUP_DIR/com.picotoopet.mac-core.plist"
    if [ -f "$STATE_DIR/api-port.txt" ]; then
      cp "$STATE_DIR/api-port.txt" "$BACKUP_DIR/api-port.txt"
    fi

    /usr/libexec/PlistBuddy -c \
      "Set :EnvironmentVariables:PICOTOO_API_PORT $TARGET_PORT" "$PLIST" \
      >/dev/null 2>&1 || \
    /usr/libexec/PlistBuddy -c \
      "Add :EnvironmentVariables:PICOTOO_API_PORT string $TARGET_PORT" "$PLIST"
    printf '%s\n' "$TARGET_PORT" > "$STATE_DIR/api-port.txt"

    printf '===== 重新加载 V2 Mac Core =====\n'
    launchctl bootout "gui/$UID/com.picotoopet.mac-core" >/dev/null 2>&1 || true
    if launchctl bootstrap "gui/$UID" "$PLIST"; then
      printf '[PASS] launchd 已重新加载。\n'
    else
      printf '[FAIL] launchd 重新加载失败。\n'
      OVERALL=1
    fi
    printf '\n'
  fi

  if [ "$OVERALL" -eq 0 ]; then
    printf '===== 等待 V2 API =====\n'
    READY=0
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      HTTP_CODE="$(curl --silent --show-error --connect-timeout 2 --max-time 3 \
        --output "$TMP_BODY" --write-out '%{http_code}' \
        "http://127.0.0.1:${TARGET_PORT}/api/v1/health" 2>/dev/null || true)"
      if [ "$HTTP_CODE" = "200" ]; then
        READY=1
        break
      fi
      sleep 2
    done
    if [ "$READY" -eq 1 ]; then
      printf '[PASS] V2 health HTTP 200。\n'
      cat "$TMP_BODY"
      printf '\n'
    else
      printf '[FAIL] V2 API 未在端口 %s 就绪；最后 HTTP 状态：%s\n' \
        "$TARGET_PORT" "${HTTP_CODE:-连接失败}"
      OVERALL=1
    fi
    printf '\n'
  fi

  if [ "$OVERALL" -eq 0 ]; then
    printf '===== launchd 运行状态 =====\n'
    LAUNCH_OUTPUT="$(launchctl print "gui/$UID/com.picotoopet.mac-core" 2>&1 || true)"
    printf '%s\n' "$LAUNCH_OUTPUT"
    if printf '%s\n' "$LAUNCH_OUTPUT" | grep -Fq "state = running"; then
      printf '[PASS] Mac Core launchd 状态为 running。\n'
    else
      printf '[FAIL] Mac Core launchd 未进入 running。\n'
      OVERALL=1
    fi
    printf '\n'
  fi

  if [ "$OVERALL" -eq 0 ]; then
    printf '===== Keychain 认证状态 =====\n'
    TOKEN="$(security find-generic-password \
      -a "$USER" -s 'PicotooPetV2.API' -w 2>/dev/null || true)"
    if [ -z "$TOKEN" ]; then
      printf '[FAIL] 未找到 PicotooPetV2.API Keychain Token。\n'
      OVERALL=1
    else
      AUTH_CODE="$(curl --silent --show-error --connect-timeout 2 --max-time 5 \
        --output "$TMP_BODY" --write-out '%{http_code}' \
        -H "Authorization: Bearer ${TOKEN}" \
        "http://127.0.0.1:${TARGET_PORT}/api/v1/status" 2>/dev/null || true)"
      if [ "$AUTH_CODE" = "200" ]; then
        printf '[PASS] 认证 status HTTP 200。\n'
      else
        printf '[FAIL] 认证 status HTTP 状态：%s\n' "${AUTH_CODE:-连接失败}"
        OVERALL=1
      fi
    fi
    unset TOKEN
    printf '\n'
  fi

  if [ "$OVERALL" -ne 0 ] && [ -f "$BACKUP_DIR/com.picotoopet.mac-core.plist" ]; then
    printf '===== 自动回滚 =====\n'
    restore_previous_configuration
    printf '[INFO] 已恢复修复前的 V2 launchd 配置和端口记录。\n\n'
  fi

  printf '===== 最终状态 =====\n'
  if [ "$OVERALL" -eq 0 ]; then
    printf 'FINAL_STATUS=PASS\n'
    printf 'V2_API_URL=http://127.0.0.1:%s\n' "$TARGET_PORT"
    printf '旧 8765 服务未被修改。\n'
  else
    printf 'FINAL_STATUS=FAIL\n'
    printf 'ROLLED_BACK=%s\n' "$ROLLED_BACK"
  fi
} > "$REPORT" 2>&1

printf '修复报告已生成：%s\n' "$REPORT"
if [ "$OVERALL" -eq 0 ]; then
  printf '修复结果：PASS；V2 已迁移到端口 %s。\n' "$TARGET_PORT"
else
  printf '修复结果：FAIL；已保留或恢复原配置，请查看报告。\n'
fi
open "$REPORT" >/dev/null 2>&1 || open -R "$REPORT" >/dev/null 2>&1 || true
exit "$OVERALL"
