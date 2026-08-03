#!/bin/bash
# 验证 Phase 2.3 Slice D Core 与 Worker 的在线合同。
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
    "2.3.0-slice-d-worker" \
    "$current_target" \
    "命令失败：$failed_command" \
    "false")" || true
  echo "Slice D Worker 验证失败。报告：$report" >&2
  exit "$code"
}
trap on_error ERR

if [[ ! -f "$(worker_plist_path)" && "${PICOTOO_FIXTURE_MODE:-0}" != "1" ]]; then
  echo "Worker LaunchAgent 定义不存在。" >&2
  exit 1
fi
base_url="http://127.0.0.1:$port"
wait_for_health "$base_url"
verify_slice_d_candidate_contract "$base_url" "$token"
wait_for_worker_state "$runtime_root" "online"
verify_worker_api_contract "$base_url" "$token"

python3 - "$runtime_root/state/worker-status.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("supported_task_types") != [
    "system.diagnostic_snapshot",
    "system.noop",
]:
    raise SystemExit("Slice D Worker supported_task_types mismatch")
if payload.get("active_task_id") is not None:
    raise SystemExit("Worker VERIFY requires idle active_task_id")
PY

report="$(write_worker_report \
  "$runtime_root" \
  "verify" \
  "pass" \
  "2.3.0-slice-d-worker" \
  "$current_target" \
  "" \
  "true")"
echo "PHASE23_MAC_WORKER_VERIFY=PASS"
echo "REPORT=$report"
if [[ "${PICOTOO_FIXTURE_MODE:-0}" != "1" ]]; then
  open "$report"
fi
