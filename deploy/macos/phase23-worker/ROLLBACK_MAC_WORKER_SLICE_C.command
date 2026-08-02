#!/bin/bash
# 回滚 Phase 2.3 Slice C Core 与 Worker 组合，不删除任何版本或数据。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$script_dir/lib.sh"
# shellcheck source=/dev/null
source "$script_dir/worker-lib.sh"

runtime_root="$(phase23_runtime_root)"
state_root="$runtime_root/state"
previous_version_file="$state_root/slice-c-previous-version.txt"
worker_present_file="$state_root/slice-c-previous-worker-present.txt"
previous_worker_backup="$state_root/slice-c-previous-worker.plist"
current_target="$(resolve_current_version "$runtime_root")"
port="$(read_existing_port "$runtime_root")"
token="$(read_api_token)"
core_label="com.picotoopet.mac-core"
report=""

on_error() {
  local code=$?
  local failed_command="${BASH_COMMAND:-unknown command}"
  trap - ERR
  report="$(write_worker_report \
    "$runtime_root" \
    "rollback" \
    "fail" \
    "2.3.0-slice-c" \
    "$current_target" \
    "命令失败：$failed_command" \
    "false")" || true
  echo "Slice C Worker 回滚失败。报告：$report" >&2
  exit "$code"
}
trap on_error ERR

if [[ ! -f "$previous_version_file" ]]; then
  echo "缺少 Slice C 上一版本记录：$previous_version_file" >&2
  exit 1
fi
previous_target="$(cat "$previous_version_file")"
if [[ -z "$previous_target" || ! -d "$previous_target" ]]; then
  echo "上一版本目录无效：$previous_target" >&2
  exit 1
fi
previous_worker_present="0"
if [[ -f "$worker_present_file" ]]; then
  previous_worker_present="$(tr -d '[:space:]' < "$worker_present_file")"
fi

stop_worker_agent
atomic_switch_current "$runtime_root" "$previous_target"
if [[ "${PICOTOO_FIXTURE_MODE:-0}" == "1" ]]; then
  stop_fixture_service "$runtime_root"
  start_fixture_service \
    "$runtime_root" \
    "$runtime_root/current/.venv/bin/picotoopet-core" \
    "$port" \
    "$token"
else
  restart_user_agent "$core_label"
  wait_for_health "http://127.0.0.1:$port"
fi
verify_health "http://127.0.0.1:$port"

plist="$(worker_plist_path)"
if [[ "$previous_worker_present" == "1" && -f "$previous_worker_backup" ]]; then
  cp "$previous_worker_backup" "$plist"
  chmod 600 "$plist"
  if [[ "${PICOTOO_FIXTURE_MODE:-0}" != "1" ]]; then
    launchctl bootstrap "gui/$UID" "$plist"
    launchctl kickstart -k "gui/$UID/$(worker_label)"
  fi
else
  rm -f "$plist"
  rm -f "$runtime_root/state/worker-status.json"
fi

printf '%s\n' "$current_target" > "$state_root/slice-c-rollback-from.txt"
report="$(write_worker_report \
  "$runtime_root" \
  "rollback" \
  "pass" \
  "previous" \
  "$previous_target" \
  "" \
  "false")"
echo "PHASE23_MAC_WORKER_ROLLBACK=PASS"
echo "REPORT=$report"
if [[ "${PICOTOO_FIXTURE_MODE:-0}" != "1" ]]; then
  open "$report"
fi
