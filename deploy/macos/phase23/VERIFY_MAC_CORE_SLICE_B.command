#!/bin/bash
# 验证已激活的 Phase 2.3 Slice B Mac Core 合同。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$script_dir/lib.sh"

runtime_root="$(phase23_runtime_root)"
port="$(read_existing_port "$runtime_root")"
token="$(read_api_token)"
current_target="$(resolve_current_version "$runtime_root")"
base_url="http://127.0.0.1:$port"

wait_for_health "$base_url"
# 必须同时验证 worker_status=true、local_worker=false、state=not_deployed。
verify_api_contract "$base_url" "$token"

report="$(write_report \
  "$runtime_root" \
  "verify" \
  "pass" \
  "2.3.0-slice-b" \
  "$current_target" \
  "")"
echo "PHASE23_MAC_DELTA_VERIFY=PASS"
echo "REPORT=$report"
if [[ "${PICOTOO_FIXTURE_MODE:-0}" != "1" ]]; then
  open "$report"
fi
