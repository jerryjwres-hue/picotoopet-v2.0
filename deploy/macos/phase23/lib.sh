#!/bin/bash
# Phase 2.3 Slice B Mac Core 增量交付共享安全函数。
set -euo pipefail

phase23_runtime_root() {
  printf '%s\n' "${PICOTOO_RUNTIME_ROOT_OVERRIDE:-$HOME/Library/Application Support/PicotooPetV2}"
}

read_manifest() {
  local package_root="$1"
  local key="$2"
  python3 - "$package_root/release-manifest.json" "$key" <<'PY'
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
key = sys.argv[2]
payload = json.loads(manifest_path.read_text(encoding="utf-8"))
value = payload
for part in key.split("."):
    if not isinstance(value, dict) or part not in value:
        raise SystemExit(f"manifest key not found: {key}")
    value = value[part]
if isinstance(value, (dict, list)):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
else:
    print(value)
PY
}

verify_manifest_files() {
  local package_root="$1"
  python3 - "$package_root" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
manifest_path = root / "release-manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
entries = manifest.get("files")
if not isinstance(entries, list) or not entries:
    raise SystemExit("release manifest has no files")
for entry in entries:
    relative = entry.get("path")
    if not isinstance(relative, str) or not relative:
        raise SystemExit("manifest path is empty")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise SystemExit(f"unsafe manifest path: {relative}")
    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"manifest path escapes package: {relative}") from exc
    if not target.is_file():
        raise SystemExit(f"manifest file missing: {relative}")
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != entry.get("sha256"):
        raise SystemExit(f"manifest hash mismatch: {relative}")
    if target.stat().st_size != entry.get("size_bytes"):
        raise SystemExit(f"manifest size mismatch: {relative}")
PY
}

resolve_current_version() {
  local runtime_root="$1"
  local current="$runtime_root/current"
  if [[ ! -e "$current" && ! -L "$current" ]]; then
    echo "current runtime is missing: $current" >&2
    return 1
  fi
  python3 - "$runtime_root" "$current" <<'PY'
import sys
from pathlib import Path

runtime = Path(sys.argv[1]).resolve()
current = Path(sys.argv[2])
target = current.resolve()
versions = (runtime / "versions").resolve()
try:
    target.relative_to(versions)
except ValueError as exc:
    raise SystemExit(f"current target is outside versions: {target}") from exc
print(target)
PY
}

read_existing_port() {
  local runtime_root="$1"
  local port_file="$runtime_root/state/api-port.txt"
  if [[ ! -f "$port_file" ]]; then
    echo "existing API port record is missing: $port_file" >&2
    return 1
  fi
  local port
  port="$(tr -d '[:space:]' < "$port_file")"
  if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
    echo "existing API port is invalid: $port" >&2
    return 1
  fi
  printf '%s\n' "$port"
}

read_api_token() {
  if [[ -n "${PICOTOO_API_TOKEN:-}" ]]; then
    printf '%s\n' "$PICOTOO_API_TOKEN"
    return 0
  fi
  security find-generic-password -a "$USER" -s "PicotooPetV2.API" -w
}

choose_free_port() {
  python3 - <<'PY'
import socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

wait_for_health() {
  local base_url="$1"
  local attempts="${2:-80}"
  local index
  for ((index = 0; index < attempts; index += 1)); do
    if curl --silent --show-error --fail --max-time 2 \
      "$base_url/api/v1/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  echo "health endpoint did not become ready: $base_url" >&2
  return 1
}

wait_for_port_release() {
  local port="$1"
  local attempts="${2:-80}"
  local index
  for ((index = 0; index < attempts; index += 1)); do
    if python3 - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(0.2)
    raise SystemExit(1 if sock.connect_ex(("127.0.0.1", port)) == 0 else 0)
PY
    then
      return 0
    fi
    sleep 0.25
  done
  echo "fixture API port did not become free: $port" >&2
  return 1
}

verify_health() {
  local base_url="$1"
  python3 - "$base_url" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
with urllib.request.urlopen(f"{base}/api/v1/health", timeout=5) as response:
    health = json.load(response)
if health.get("status") != "ok":
    raise SystemExit(f"health status is not ok: {health!r}")
PY
}

verify_api_contract() {
  local base_url="$1"
  local token="$2"
  python3 - "$base_url" "$token" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
token = sys.argv[2]


def get(path: str, *, authenticated: bool = False):
    headers = {"Authorization": f"Bearer {token}"} if authenticated else {}
    request = urllib.request.Request(f"{base}{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)

health = get("/api/v1/health")
if health.get("status") != "ok":
    raise SystemExit("health.status must be ok")
capabilities = get("/api/v1/capabilities")
features = capabilities.get("features", {})
if features.get("worker_status") is not True:
    raise SystemExit("capabilities.features.worker_status must be true")
if features.get("local_worker") is not False:
    raise SystemExit("capabilities.features.local_worker must be false")
worker = get("/api/v1/workers/status", authenticated=True)
if worker.get("state") != "not_deployed":
    raise SystemExit("workers.status.state must be not_deployed")
if worker.get("available") is not False:
    raise SystemExit("workers.status.available must be false")
PY
}

atomic_switch_current() {
  local runtime_root="$1"
  local target="$2"
  local versions_root
  versions_root="$(python3 - "$runtime_root/versions" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).resolve())
PY
)"
  local resolved_target
  resolved_target="$(python3 - "$target" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).resolve())
PY
)"
  case "$resolved_target" in
    "$versions_root"/*) ;;
    *)
      echo "activation target is outside versions: $resolved_target" >&2
      return 1
      ;;
  esac
  local next="$runtime_root/current.next"
  rm -f "$next"
  ln -s "$resolved_target" "$next"
  mv -h "$next" "$runtime_root/current"
}

restart_user_agent() {
  local label="${1:-com.picotoopet.mac-core}"
  if [[ "${PICOTOO_FIXTURE_MODE:-0}" == "1" ]]; then
    return 0
  fi
  launchctl kickstart -k "gui/$UID/$label"
}

stop_fixture_service() {
  local runtime_root="$1"
  local pid_file="$runtime_root/state/fixture-service.pid"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
      local index
      for ((index = 0; index < 40; index += 1)); do
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
  fi
}

start_fixture_service() {
  local runtime_root="$1"
  local executable="$2"
  local port="$3"
  local token="$4"
  local stdout_log="$runtime_root/logs/fixture-service.stdout.log"
  local stderr_log="$runtime_root/logs/fixture-service.stderr.log"
  mkdir -p "$runtime_root/state" "$runtime_root/logs"
  stop_fixture_service "$runtime_root"
  wait_for_port_release "$port"

  nohup env \
    PICOTOO_RUNTIME_ROOT="$runtime_root" \
    PICOTOO_API_HOST="127.0.0.1" \
    PICOTOO_API_PORT="$port" \
    PICOTOO_API_TOKEN="$token" \
    "$executable" serve \
      </dev/null \
      >"$stdout_log" \
      2>"$stderr_log" &
  local pid=$!
  printf '%s\n' "$pid" > "$runtime_root/state/fixture-service.pid"

  if ! wait_for_health "http://127.0.0.1:$port"; then
    echo "fixture service failed to become healthy; stderr follows:" >&2
    cat "$stderr_log" >&2 || true
    return 1
  fi

  # 首次健康可能来自刚退出的旧进程；要求新 PID 持续存活并再次通过健康检查。
  sleep 1
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "fixture service exited after initial health check; stderr follows:" >&2
    cat "$stderr_log" >&2 || true
    return 1
  fi
  if ! verify_health "http://127.0.0.1:$port"; then
    echo "fixture service was not stable after startup; stderr follows:" >&2
    cat "$stderr_log" >&2 || true
    return 1
  fi
}

write_report() {
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
  local report="$reports/phase23-slice-b-${kind}-${stamp}.json"
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
    "worker_runtime_installed": False,
    "error": sys.argv[5] or None,
}
path.write_text(
    json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
print(path)
PY
}
