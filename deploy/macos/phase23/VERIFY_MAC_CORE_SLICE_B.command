#!/bin/bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
source "$script_dir/lib.sh"
runtime_root="$(phase23_runtime_root)"
port="$(read_existing_port "$runtime_root")"
token="$(read_api_token)"
current_target="$(resolve_current_version "$runtime_root")"
base_url="http://127.0.0.1:$port"
wait_for_health "$base_url"
verify_api_contract "$base_url" "$token"
python3 - "$base_url" "$token" <<'PY'
import json, sys, urllib.request
base, token = sys.argv[1:]
request = urllib.request.Request(f"{base.rstrip('/')}/openapi.json", headers={"Authorization": f"Bearer {token}"})
with urllib.request.urlopen(request, timeout=5) as response:
    paths = json.load(response).get("paths", {})
required = {"/api/v1/tasks/system-diagnostic-snapshot", "/api/v1/tasks/{task_id}/result"}
missing = sorted(required - set(paths))
if missing:
    raise SystemExit(f"Slice D diagnostic paths missing: {missing!r}")
PY
report="$(write_report "$runtime_root" verify pass "2.3.0-slice-d-core" "$current_target" "")"
echo "PHASE23_MAC_SLICE_D_CORE_VERIFY=PASS"
echo "REPORT=$report"
if [[ "${PICOTOO_FIXTURE_MODE:-0}" != "1" ]]; then open "$report"; fi
