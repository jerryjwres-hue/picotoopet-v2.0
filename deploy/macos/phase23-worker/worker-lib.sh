#!/bin/bash
# Phase 2.3 Slice C Worker 安装、验证和回滚共享函数。
set -euo pipefail

worker_label() {
  printf '%s\n' "com.picotoopet.worker"
}

worker_plist_path() {
  printf '%s\n' "$HOME/Library/LaunchAgents/$(worker_label).plist"
}

write_worker_plist() {
  local runtime_root="$1"
  local worker_id="$2"
  local target
  target="$(worker_plist_path)"
  mkdir -p "$(dirname "$target")" "$runtime_root/logs"
  python3 - "$target" "$runtime_root" "$worker_id" <<'PY'
import plistlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
runtime_root = Path(sys.argv[2])
worker_id = sys.argv[3]
payload = {
    "Label": "com.picotoopet.worker",
    "ProgramArguments": [
        str(runtime_root / "current" / ".venv" / "bin" / "picotoopet-core"),
        "worker",
        "--loop",
        "--worker-id",
        worker_id,
    ],
    "EnvironmentVariables": {
        "PICOTOO_RUNTIME_ROOT": str(runtime_root),
        "PICOTOO_WORKER_POLL_SECONDS": "2",
        "PICOTOO_WORKER_LEASE_SECONDS": "60",
        "PICOTOO_WORKER_HEARTBEAT_SECONDS": "15",
        "PICOTOO_WORKER_STATUS_STALE_SECONDS": "45",
    },
    "RunAtLoad": True,
    "KeepAlive": True,
    "ProcessType": "Background",
    "StandardOutPath": str(runtime_root / "logs" / "worker.stdout.log"),
    "StandardErrorPath": str(runtime_root / "logs" / "worker.stderr.log"),
}
with path.open("wb") as handle:
    plistlib.dump(payload, handle, sort_keys=True)
PY
  chmod 600 "$target"
}

stop_worker_agent() {
  local label
  label="$(worker_label)"
  if [[ "${PICOTOO_FIXTURE_MODE:-0}" == "1" ]]; then
    stop_fixture_worker "$(phase23_runtime_root)"
    return 0
  fi
  launchctl bootout "gui/$UID/$label" >/dev/null 2>&1 || true
}

start_worker_agent() {
  local runtime_root="$1"
  local worker_id="$2"
  local token="${3:-}"
  if [[ "${PICOTOO_FIXTURE_MODE:-0}" == "1" ]]; then
    start_fixture_worker "$runtime_root" "$worker_id" "$token"
    return 0
  fi
  local plist
  plist="$(worker_plist_path)"
  stop_worker_agent
  launchctl bootstrap "gui/$UID" "$plist"
  launchctl kickstart -k "gui/$UID/$(worker_label)"
}

stop_fixture_worker() {
  local runtime_root="$1"
  local pid_file="$runtime_root/state/fixture-worker.pid"
  if [[ ! -f "$pid_file" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "$pid_file")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
    local index
    for ((index = 0; index < 50; index += 1)); do
      if ! kill -0 "$pid" >/dev/null 2>&1; then
        break
      fi
      sleep 0.1
    done
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
    wait "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$pid_file"
}

start_fixture_worker() {
  local runtime_root="$1"
  local worker_id="$2"
  local token="$3"
  local executable="$runtime_root/current/.venv/bin/picotoopet-core"
  local stdout_log="$runtime_root/logs/fixture-worker.stdout.log"
  local stderr_log="$runtime_root/logs/fixture-worker.stderr.log"
  mkdir -p "$runtime_root/state" "$runtime_root/logs"
  stop_fixture_worker "$runtime_root"
  nohup env \
    PICOTOO_RUNTIME_ROOT="$runtime_root" \
    PICOTOO_API_TOKEN="$token" \
    PICOTOO_WORKER_POLL_SECONDS="0.2" \
    PICOTOO_WORKER_LEASE_SECONDS="10" \
    PICOTOO_WORKER_HEARTBEAT_SECONDS="2" \
    PICOTOO_WORKER_STATUS_STALE_SECONDS="8" \
    "$executable" worker --loop --worker-id "$worker_id" \
      </dev/null >"$stdout_log" 2>"$stderr_log" &
  local pid=$!
  printf '%s\n' "$pid" > "$runtime_root/state/fixture-worker.pid"
  sleep 0.5
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "fixture Worker 启动失败；stderr：" >&2
    cat "$stderr_log" >&2 || true
    return 1
  fi
}

wait_for_worker_state() {
  local runtime_root="$1"
  local expected="${2:-online}"
  local attempts="${3:-80}"
  local path="$runtime_root/state/worker-status.json"
  local index
  for ((index = 0; index < attempts; index += 1)); do
    if python3 - "$path" "$expected" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected = sys.argv[2]
if not path.is_file():
    raise SystemExit(1)
payload = json.loads(path.read_text(encoding="utf-8"))
if payload.get("state") != expected:
    raise SystemExit(1)
if expected == "online" and payload.get("available") is not True:
    raise SystemExit(1)
if expected == "online" and payload.get("supported_task_types") != ["system.noop"]:
    raise SystemExit(1)
PY
    then
      return 0
    fi
    sleep 0.25
  done
  echo "Worker 状态未进入 $expected：$path" >&2
  return 1
}

verify_slice_c_candidate_contract() {
  local base_url="$1"
  local token="$2"
  python3 - "$base_url" "$token" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
token = sys.argv[2]


def get(path: str, authenticated: bool = False):
    headers = {"Authorization": f"Bearer {token}"} if authenticated else {}
    request = urllib.request.Request(f"{base}{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)

health = get("/api/v1/health")
if health.get("status") != "ok" or health.get("version") != "2.3.0-slice-c":
    raise SystemExit(f"Slice C health contract failed: {health!r}")
features = get("/api/v1/capabilities").get("features", {})
if features.get("worker_status") is not True or features.get("local_worker") is not True:
    raise SystemExit(f"Slice C capabilities failed: {features!r}")
status = get("/api/v1/workers/status", authenticated=True)
if status.get("state") not in {"not_deployed", "offline", "online"}:
    raise SystemExit(f"unexpected worker state: {status!r}")
PY
}

verify_worker_api_contract() {
  local base_url="$1"
  local token="$2"
  python3 - "$base_url" "$token" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
token = sys.argv[2]
headers = {"Authorization": f"Bearer {token}"}
request = urllib.request.Request(f"{base}/api/v1/workers/status", headers=headers)
with urllib.request.urlopen(request, timeout=5) as response:
    status = json.load(response)
if status.get("state") != "online":
    raise SystemExit(f"worker state must be online: {status!r}")
if status.get("available") is not True:
    raise SystemExit(f"worker available must be true: {status!r}")
if status.get("supported_task_types") != ["system.noop"]:
    raise SystemExit(f"worker task types are not frozen: {status!r}")
if status.get("worker_id") in {None, ""}:
    raise SystemExit(f"worker_id is missing: {status!r}")
PY
}

write_worker_report() {
  local runtime_root="$1"
  local kind="$2"
  local status="$3"
  local version="$4"
  local install_path="$5"
  local error_message="${6:-}"
  local reports="$runtime_root/reports"
  mkdir -p "$reports"
  local stamp
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local report="$reports/phase23-slice-c-${kind}-${stamp}.json"
  python3 - "$report" "$status" "$version" "$install_path" "$error_message" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "status": sys.argv[2],
    "version": sys.argv[3] or None,
    "install_path": sys.argv[4] or None,
    "source_build_on_user_mac": False,
    "worker_runtime_installed": sys.argv[2] == "pass",
    "worker_supported_task_types": ["system.noop"],
    "error": sys.argv[5] or None,
}
path.write_text(
    json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
print(path)
PY
}
