#!/bin/bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"; source "$script_dir/lib.sh"; source "$script_dir/worker-lib.sh"
root="$(phase23_runtime_root)"; port="$(read_existing_port "$root")"; token="$(read_api_token)"; current="$(resolve_current_version "$root")"; report=""
on_error(){ code=$?; failed="${BASH_COMMAND:-unknown command}"; trap - ERR; report="$(write_worker_report "$root" verify fail 2.3.0-slice-d-worker "$current" "命令失败：$failed" false)" || true; echo "验证失败：$report" >&2; exit "$code"; }; trap on_error ERR
[[ -f "$(worker_plist_path)" || "${PICOTOO_FIXTURE_MODE:-0}" == 1 ]] || exit 1
base="http://127.0.0.1:$port"; wait_for_health "$base"; verify_slice_d_candidate_contract "$base" "$token"; wait_for_worker_state "$root" online; verify_worker_api_contract "$base" "$token"
python3 - "$root/state/worker-status.json" <<'PY'
import json,sys
from pathlib import Path
data=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
if data.get('supported_task_types') != ['system.diagnostic_snapshot','system.noop'] or data.get('active_task_id') is not None: raise SystemExit(data)
PY
report="$(write_worker_report "$root" verify pass 2.3.0-slice-d-worker "$current" "" true)"; echo "PHASE23_MAC_WORKER_SLICE_D_VERIFY=PASS"; echo "REPORT=$report"; [[ "${PICOTOO_FIXTURE_MODE:-0}" == 1 ]] || open "$report"
