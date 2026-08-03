#!/bin/bash
set -euo pipefail
worker_label(){ printf '%s\n' com.picotoopet.worker; }
worker_plist_path(){ printf '%s\n' "$HOME/Library/LaunchAgents/$(worker_label).plist"; }
write_worker_plist(){ local root="$1" id="$2" target; target="$(worker_plist_path)"; mkdir -p "$(dirname "$target")" "$root/logs"; python3 - "$target" "$root" "$id" <<'PY'
import plistlib, sys
from pathlib import Path
path=Path(sys.argv[1]); root=Path(sys.argv[2]); worker_id=sys.argv[3]
payload={"Label":"com.picotoopet.worker","ProgramArguments":[str(root/"current"/".venv"/"bin"/"picotoopet-core"),"worker","--loop","--worker-id",worker_id],"EnvironmentVariables":{"PICOTOO_RUNTIME_ROOT":str(root),"PICOTOO_WORKER_POLL_SECONDS":"2","PICOTOO_WORKER_LEASE_SECONDS":"60","PICOTOO_WORKER_HEARTBEAT_SECONDS":"15","PICOTOO_WORKER_STATUS_STALE_SECONDS":"45"},"RunAtLoad":True,"KeepAlive":True,"ProcessType":"Background","StandardOutPath":str(root/"logs"/"worker.stdout.log"),"StandardErrorPath":str(root/"logs"/"worker.stderr.log")}
with path.open("wb") as handle: plistlib.dump(payload,handle,sort_keys=True)
PY
chmod 600 "$target"; }
stop_fixture_worker(){ local root="$1" file="$root/state/fixture-worker.pid"; [[ -f "$file" ]] || return 0; local pid; pid="$(cat "$file")"; if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" >/dev/null 2>&1; then kill "$pid" || true; for _ in {1..50}; do kill -0 "$pid" >/dev/null 2>&1 || break; sleep .1; done; kill -0 "$pid" >/dev/null 2>&1 && kill -9 "$pid" || true; wait "$pid" || true; fi; rm -f "$file"; }
stop_worker_agent(){ if [[ "${PICOTOO_FIXTURE_MODE:-0}" == 1 ]]; then stop_fixture_worker "$(phase23_runtime_root)"; else launchctl bootout "gui/$UID/$(worker_label)" >/dev/null 2>&1 || true; fi; }
start_fixture_worker(){ local root="$1" id="$2" token="$3" exe="$root/current/.venv/bin/picotoopet-core"; mkdir -p "$root/state" "$root/logs"; stop_fixture_worker "$root"; nohup env PICOTOO_RUNTIME_ROOT="$root" PICOTOO_API_TOKEN="$token" PICOTOO_WORKER_POLL_SECONDS=.2 PICOTOO_WORKER_LEASE_SECONDS=10 PICOTOO_WORKER_HEARTBEAT_SECONDS=2 PICOTOO_WORKER_STATUS_STALE_SECONDS=8 "$exe" worker --loop --worker-id "$id" </dev/null >"$root/logs/fixture-worker.stdout.log" 2>"$root/logs/fixture-worker.stderr.log" & local pid=$!; printf '%s\n' "$pid" > "$root/state/fixture-worker.pid"; sleep .5; kill -0 "$pid" >/dev/null 2>&1 || { cat "$root/logs/fixture-worker.stderr.log" >&2 || true; return 1; }; }
start_worker_agent(){ local root="$1" id="$2" token="${3:-}"; if [[ "${PICOTOO_FIXTURE_MODE:-0}" == 1 ]]; then start_fixture_worker "$root" "$id" "$token"; else local plist; plist="$(worker_plist_path)"; stop_worker_agent; launchctl bootstrap "gui/$UID" "$plist"; launchctl kickstart -k "gui/$UID/$(worker_label)"; fi; }
wait_for_worker_state(){ local root="$1" expected="${2:-online}" attempts="${3:-80}" path="$root/state/worker-status.json"; for ((i=0;i<attempts;i++)); do if python3 - "$path" "$expected" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); expected=sys.argv[2]
if not p.is_file(): raise SystemExit(1)
data=json.loads(p.read_text(encoding="utf-8"))
if data.get("state") != expected: raise SystemExit(1)
if expected == "online" and (data.get("available") is not True or data.get("supported_task_types") != ["system.diagnostic_snapshot","system.noop"]): raise SystemExit(1)
PY
then return 0; fi; sleep .25; done; echo "Worker 状态未进入 $expected" >&2; return 1; }
verify_slice_d_candidate_contract(){ local base="$1" token="$2"; python3 - "$base" "$token" <<'PY'
import json,sys,urllib.request
base=sys.argv[1].rstrip('/'); token=sys.argv[2]
def get(path,auth=False):
 h={"Authorization":f"Bearer {token}"} if auth else {}; r=urllib.request.Request(base+path,headers=h)
 with urllib.request.urlopen(r,timeout=5) as resp:return json.load(resp)
if get('/api/v1/health').get('status')!='ok': raise SystemExit('health failed')
features=get('/api/v1/capabilities').get('features',{})
if features.get('worker_status') is not True or features.get('local_worker') is not True: raise SystemExit('capabilities failed')
paths=get('/openapi.json').get('paths',{})
required={'/api/v1/tasks/system-diagnostic-snapshot','/api/v1/tasks/{task_id}/result'}
if required-set(paths): raise SystemExit('diagnostic paths missing')
get('/api/v1/workers/status',True)
PY
}
verify_worker_api_contract(){ local base="$1" token="$2"; python3 - "$base" "$token" <<'PY'
import json,sys,urllib.request
r=urllib.request.Request(sys.argv[1].rstrip('/')+'/api/v1/workers/status',headers={'Authorization':f'Bearer {sys.argv[2]}'})
with urllib.request.urlopen(r,timeout=5) as resp:data=json.load(resp)
if data.get('state')!='online' or data.get('available') is not True: raise SystemExit(f'worker offline: {data!r}')
if data.get('supported_task_types') != ['system.diagnostic_snapshot','system.noop']: raise SystemExit(f'types mismatch: {data!r}')
if not data.get('worker_id'): raise SystemExit('worker_id missing')
PY
}
write_worker_report(){ local root="$1" kind="$2" status="$3" version="$4" path="$5" error="${6:-}" installed="${7:-false}" reports="$root/reports"; mkdir -p "$reports"; local report="$reports/phase23-slice-d-${kind}-$(date -u +%Y%m%dT%H%M%SZ).json"; python3 - "$report" "$status" "$version" "$path" "$error" "$installed" <<'PY'
import json,sys
from pathlib import Path
data={"status":sys.argv[2],"version":sys.argv[3] or None,"runtime_version":"2.3.0-slice-d-worker","install_path":sys.argv[4] or None,"source_build_on_user_mac":False,"worker_runtime_installed":sys.argv[6].lower()=="true","worker_supported_task_types":["system.diagnostic_snapshot","system.noop"],"diagnostic_hard_timeout_seconds":30,"diagnostic_termination_grace_seconds":5,"error":sys.argv[5] or None}
Path(sys.argv[1]).write_text(json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8"); print(sys.argv[1])
PY
}
