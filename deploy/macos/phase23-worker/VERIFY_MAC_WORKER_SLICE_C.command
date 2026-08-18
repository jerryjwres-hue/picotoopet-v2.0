#!/bin/bash
# 验证已激活的 Phase 2.3 Slice D Core、Worker 与累计可选能力。
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
supported = payload.get("supported_task_types")
required = {"system.diagnostic_snapshot", "system.noop"}
allowed = required | {
    "autonomous.local_analysis.v1",
    "autonomous.discovery.v1",
    "autonomous.goal_synthesis.v1",
    "autonomous.goal_handoff.v1",
    "autonomous.storage_maintenance.v1",
    "business.local_intelligence.v1",
    "creative.content_plan.v1",
    "provider.codex.handoff-v1",
    "provider.adoption.apply-v1",
    "provider.commit.create-v1",
    "provider.publish.pr-create-v1",
    "research.search",
}
# 累计能力验证：基础系统类型必须存在，只有明确列出的健康受控能力允许出现。
# 禁止 autonomous.* 或其它通配，避免安装验证器意外放宽 Worker 执行边界。
if not isinstance(supported, list) or not required <= set(supported):
    raise SystemExit(f"Worker 缺少基础冻结类型：{payload!r}")
unexpected = set(supported) - allowed
if unexpected:
    raise SystemExit(f"unexpected Worker task type: {sorted(unexpected)!r}")
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
