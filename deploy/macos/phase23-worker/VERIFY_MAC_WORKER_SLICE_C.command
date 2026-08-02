#!/bin/bash
# 验证 Phase 2.3 Slice C Core 与 Worker 的在线合同。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$script_dir/lib.sh"
# shellcheck source=/dev/null
source "$script_dir/worker-lib.sh"

runtime_root="$(phase23_runtime_root)"
port="$(read_existing_port "$runtime_root")"
token="$(read_api_token)"
current_target="$(resolve_current_version "$runtime_root")"
report=""

on_error() {
  local code=$?
  local failed_command="${BASH_COMMAND:-unknown command}"
  trap - ERR
  report="$(write_worker_report \
    "$runtime_root" \
    "verify" \
    "fail" \
    "2.3.0-slice-c" \
    "$current_target" \
    "命令失败：$failed_command")" || true
  echo "Slice C Worker 验证失败。报告：$report" >&2
  exit "$code"
}
trap on_error ERR

if [[ ! -f "$(worker_plist_path)" && "${PICOTOO_FIXTURE_MODE:-0}" != "1" ]]; then
  echo "Worker LaunchAgent 定义不存在。" >&2
  exit 1
fi
wait_for_health "http://127.0.0.1:$port"
verify_slice_c_candidate_contract "http://127.0.0.1:$port" "$token"
wait_for_worker_state "$runtime_root" "online"
verify_worker_api_contract "http://127.0.0.1:$port" "$token"

report="$(write_worker_report \
  "$runtime_root" \
  "verify" \
  "pass" \
  "2.3.0-slice-c" \
  "$current_target" \
  "")"
echo "PHASE23_MAC_WORKER_VERIFY=PASS"
echo "REPORT=$report"
if [[ "${PICOTOO_FIXTURE_MODE:-0}" != "1" ]]; then
  open "$report"
fi
