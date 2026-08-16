#!/bin/bash
# Phase 2.3 Slice D Worker 安装、验证和回滚共享函数。
set -euo pipefail

phase23_worker_product_version() {
  local package_root="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
  phase23_product_version "$package_root"
}

verify_worker_product_version() {
  local runtime_root="$1"
  local expected_product_version="$2"
  "$runtime_root/current/.venv/bin/python" - "$expected_product_version" <<'PY'
import sys
from picotoopet_core import __version__

expected_product_version = sys.argv[1]
if __version__ != expected_product_version:
    raise SystemExit(
        "Mac Worker product version mismatch: "
        f"expected={expected_product_version!r}, actual={__version__!r}"
    )
PY
}

worker_label() {
  printf '%s\n' "com.picotoopet.worker"
}

worker_plist_path() {
  printf '%s\n' "$HOME/Library/LaunchAgents/$(worker_label).plist"
}

write_worker_plist() {
  local runtime_root="$1"
  local worker_id="$2"
  local github_cli_executable="${3:-}"
  local target
  target="$(worker_plist_path)"
  mkdir -p "$(dirname "$target")" "$runtime_root/logs"
  python3 - "$target" "$runtime_root" "$worker_id" "$github_cli_executable" <<'PY'
import os
import plistlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
runtime_root = Path(sys.argv[2])
worker_id = sys.argv[3]
github_cli_executable = sys.argv[4].strip()
preserved_keys = (
    "PICOTOO_PROVIDER_REPOSITORY",
    "PICOTOO_PROVIDER_WORKTREE_ROOT",
    "PICOTOO_CODEX_EXECUTABLE",
    "PICOTOO_GITHUB_CLI_EXECUTABLE",
)
preserved_environment = {}
if path.is_file():
    try:
        with path.open("rb") as handle:
            existing = plistlib.load(handle)
    except (OSError, ValueError, plistlib.InvalidFileException):
        existing = {}
    existing_environment = existing.get("EnvironmentVariables", {})
    if isinstance(existing_environment, dict):
        for key in preserved_keys:
            value = existing_environment.get(key)
            if isinstance(value, str) and value.strip():
                preserved_environment[key] = value.strip()

# `gh` 必须是已存在的绝对可执行文件；发现失败时不注册 publication handler。
existing_gh = preserved_environment.get("PICOTOO_GITHUB_CLI_EXECUTABLE", "")
if existing_gh and (
    not Path(existing_gh).is_absolute()
    or not Path(existing_gh).is_file()
    or not os.access(existing_gh, os.X_OK)
):
    preserved_environment.pop("PICOTOO_GITHUB_CLI_EXECUTABLE", None)
if github_cli_executable:
    candidate = Path(github_cli_executable)
    if candidate.is_absolute() and candidate.is_file() and os.access(candidate, os.X_OK):
        preserved_environment["PICOTOO_GITHUB_CLI_EXECUTABLE"] = str(candidate)

# LaunchAgent 不继承交互 shell PATH；显式绑定已部署的用户级、Homebrew 和系统工具目录。
research_worker_path = os.pathsep.join(
    [
        str(Path.home() / ".local" / "bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
)
environment = {
    "PATH": research_worker_path,
    "PICOTOO_RUNTIME_ROOT": str(runtime_root),
    "PICOTOO_WORKER_POLL_SECONDS": "2",
    "PICOTOO_WORKER_LEASE_SECONDS": "60",
    "PICOTOO_WORKER_HEARTBEAT_SECONDS": "15",
    "PICOTOO_WORKER_STATUS_STALE_SECONDS": "45",
}
environment.update(preserved_environment)
payload = {
    "Label": "com.picotoopet.worker",
    "ProgramArguments": [
        str(runtime_root / "current" / ".venv" / "bin" / "picotoopet-core"),
        "worker",
        "--loop",
        "--worker-id",
        worker_id,
    ],
    "EnvironmentVariables": environment,
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

stop_worker_agent() {
  if [[ "${PICOTOO_FIXTURE_MODE:-0}" == "1" ]]; then
    stop_fixture_worker "$(phase23_runtime_root)"
    return 0
  fi
  launchctl bootout "gui/$UID/$(worker_label)" >/dev/null 2>&1 || true
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
if expected == "online":
    if payload.get("available") is not True:
        raise SystemExit(1)
    supported = payload.get("supported_task_types")
    required = {"system.diagnostic_snapshot", "system.noop"}
    allowed = required | {
        "business.local_intelligence.v1",
        "creative.content_plan.v1",
        "provider.codex.handoff-v1",
        "provider.adoption.apply-v1",
        "provider.commit.create-v1",
        "provider.publish.pr-create-v1",
        "research.search",
    }
    # 累计能力验证：历史已实现与健康的 Research 类型可注册，未知类型继续被拒绝。
    if not isinstance(supported, list) or not required <= set(supported):
        raise SystemExit(1)
    unexpected = set(supported) - allowed
    if unexpected:
        raise SystemExit(f"unexpected Worker task type: {sorted(unexpected)!r}")
PY
    then
      return 0
    fi
    sleep 0.25
  done
  echo "Worker 状态未进入 $expected：$path" >&2
  return 1
}

verify_slice_d_candidate_contract() {
  local base_url="$1"
  local token="$2"
  local expected_product_version="${3:-}"
  python3 - "$base_url" "$token" "$expected_product_version" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
token = sys.argv[2]
expected_product_version = sys.argv[3]


def get(path: str, *, authenticated: bool = False):
    headers = {"Authorization": f"Bearer {token}"} if authenticated else {}
    request = urllib.request.Request(f"{base}{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)

health = get("/api/v1/health")
if health.get("status") != "ok":
    raise SystemExit(f"health failed: {health!r}")
if expected_product_version and health.get("version") != expected_product_version:
    raise SystemExit(
        "Mac Worker Core product version mismatch: "
        f"expected={expected_product_version!r}, actual={health.get('version')!r}"
    )
features = get("/api/v1/capabilities").get("features", {})
if features.get("worker_status") is not True or features.get("local_worker") is not True:
    raise SystemExit(f"capabilities failed: {features!r}")
paths = get("/openapi.json").get("paths", {})
required = {
    "/api/v1/tasks/system-diagnostic-snapshot",
    "/api/v1/tasks/research-search",
    "/api/v1/tasks/{task_id}/result",
    "/api/v1/provider-commit-candidates/{commit_candidate_id}/publication/prepare",
    "/api/v1/provider-publication-candidates",
    "/api/v1/provider-publication-candidates/{publication_candidate_id}",
}
missing = sorted(required - set(paths))
if missing:
    raise SystemExit(f"Slice D/Research paths missing: {missing!r}")
status = get("/api/v1/workers/status", authenticated=True)
if status.get("state") not in {
    "not_deployed", "starting", "online", "degraded", "offline"
}:
    raise SystemExit(f"unexpected Worker state: {status!r}")
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
request = urllib.request.Request(
    f"{base}/api/v1/workers/status",
    headers={"Authorization": f"Bearer {sys.argv[2]}"},
)
with urllib.request.urlopen(request, timeout=5) as response:
    status = json.load(response)
if status.get("state") != "online" or status.get("available") is not True:
    raise SystemExit(f"Worker 必须在线：{status!r}")
supported = status.get("supported_task_types")
required = {"system.diagnostic_snapshot", "system.noop"}
allowed = required | {
    "business.local_intelligence.v1",
    "creative.content_plan.v1",
    "provider.codex.handoff-v1",
    "provider.adoption.apply-v1",
    "provider.commit.create-v1",
    "provider.publish.pr-create-v1",
    "research.search",
}
if not isinstance(supported, list) or not required <= set(supported):
    raise SystemExit(f"Worker 缺少基础冻结类型：{status!r}")
unexpected = set(supported) - allowed
if unexpected:
    raise SystemExit(f"unexpected Worker task type: {sorted(unexpected)!r}")
if not status.get("worker_id"):
    raise SystemExit(f"worker_id 缺失：{status!r}")
PY
}

write_worker_report() {
  local runtime_root="$1"
  local kind="$2"
  local status="$3"
  local version="$4"
  local install_path="$5"
  local error_message="${6:-}"
  local worker_installed="${7:-false}"
  local product_version="${8:-}"
  local reports="$runtime_root/reports"
  mkdir -p "$reports"
  local stamp
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local report="$reports/phase23-slice-d-worker-${kind}-${stamp}.json"
  python3 - \
    "$report" \
    "$status" \
    "$version" \
    "$install_path" \
    "$error_message" \
    "$worker_installed" \
    "$product_version" <<'PY'
import json
import sys
from pathlib import Path

payload = {
    "status": sys.argv[2],
    "version": sys.argv[3] or None,
    "product_version": sys.argv[7] or None,
    "runtime_version": "2.3.0-slice-d-worker",
    "install_path": sys.argv[4] or None,
    "source_build_on_user_mac": False,
    "worker_runtime_installed": sys.argv[6].lower() == "true",
    "worker_supported_task_types": [
        "system.diagnostic_snapshot",
        "system.noop",
    ],
    "worker_optional_registered_task_types": [
        "business.local_intelligence.v1",
        "creative.content_plan.v1",
        "provider.codex.handoff-v1",
        "provider.adoption.apply-v1",
        "provider.commit.create-v1",
        "provider.publish.pr-create-v1",
        "research.search",
    ],
    "diagnostic_hard_timeout_seconds": 30,
    "diagnostic_termination_grace_seconds": 5,
    "error": sys.argv[5] or None,
}
path = Path(sys.argv[1])
path.write_text(
    json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
print(path)
PY
}
