#!/bin/bash
# 验证已激活的 Phase 2.3 Slice D Core 与 Worker 合同。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$script_dir/lib.sh"
# shellcheck source=/dev/null
source "$script_dir/worker-lib.sh"

runtime_root="$(phase23_runtime_root)"
expected_product_version="$(phase23_worker_product_version "$script_dir")"
manifest_product_version="$(read_manifest "$script_dir" product_version)"
if [[ "$manifest_product_version" != "$expected_product_version" ]]; then
  echo "Mac Worker Manifest 产品版本不一致：expected=$expected_product_version actual=$manifest_product_version" >&2
  exit 1
fi
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
    "false" \
    "$expected_product_version")" || true
  echo "Slice D Worker 验证失败。报告：$report" >&2
  exit "$code"
}
trap on_error ERR

if [[ ! -f "$(worker_plist_path)" && "${PICOTOO_FIXTURE_MODE:-0}" != "1" ]]; then
  echo "Worker LaunchAgent 定义不存在。" >&2
  exit 1
fi
base_url="http://127.0.0.1:$port"
verify_worker_product_version "$runtime_root" "$expected_product_version"
wait_for_health "$base_url"
verify_slice_d_candidate_contract "$base_url" "$token" "$expected_product_version"
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
    raise SystemExit(f"supported_task_types mismatch: {payload!r}")
if payload.get("active_task_id") is not None:
    raise SystemExit(f"Worker is not idle: {payload!r}")
PY

report="$(write_worker_report \
  "$runtime_root" \
  "verify" \
  "pass" \
  "2.3.0-slice-d-worker" \
  "$current_target" \
  "" \
  "true" \
  "$expected_product_version")"
echo "PHASE23_MAC_WORKER_VERIFY=PASS"
echo "PHASE23_MAC_WORKER_SLICE_D_VERIFY=PASS"
echo "PRODUCT_VERSION=$expected_product_version"
echo "REPORT=$report"
if [[ "${PICOTOO_FIXTURE_MODE:-0}" != "1" ]]; then
  open "$report"
fi
