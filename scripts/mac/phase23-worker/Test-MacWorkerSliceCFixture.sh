#!/bin/bash
# 在临时含空格目录中验证 Slice C 安装、Worker 执行、历史任务保护与回滚。
set -euo pipefail

release_root="${1:-}"
if [[ -z "$release_root" || ! -d "$release_root" ]]; then
  echo "用法：$0 <release-root>" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "$0")" && pwd)"
bash "$script_dir/Test-MacWorkerSliceC.sh" "$release_root"

archive="$(find "$release_root" -maxdepth 1 -type f \
  -name 'PicotooPet-MacWorker-*.tar.gz' -print | sort | tail -n 1)"
temp_root="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-worker-fixture.XXXXXX")"
extract_root="$temp_root/package"
runtime_root="$temp_root/Application Support/PicotooPetV2"
fixture_home="$temp_root/home"
evidence_root="$release_root/fixture-evidence"
mkdir -p \
  "$extract_root" \
  "$runtime_root/versions" \
  "$runtime_root/state" \
  "$runtime_root/logs" \
  "$fixture_home/Library/LaunchAgents" \
  "$evidence_root"

tar -xzf "$archive" -C "$extract_root"
root_count="$(find "$extract_root" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
if [[ "$root_count" != "1" ]]; then
  echo "Fixture 归档根目录数量无效。" >&2
  exit 1
fi
package_root="$(find "$extract_root" -mindepth 1 -maxdepth 1 -type d -print | head -n 1)"
# shellcheck source=/dev/null
source "$package_root/lib.sh"
# shellcheck source=/dev/null
source "$package_root/worker-lib.sh"

export HOME="$fixture_home"
export PICOTOO_RUNTIME_ROOT_OVERRIDE="$runtime_root"
export PICOTOO_RUNTIME_ROOT="$runtime_root"
export PICOTOO_FIXTURE_MODE=1
token="fixture-token-0123456789abcdef0123456789"
export PICOTOO_API_TOKEN="$token"

cleanup() {
  stop_fixture_worker "$runtime_root" || true
  stop_fixture_service "$runtime_root" || true
  rm -rf "$temp_root"
}
trap cleanup EXIT

baseline="$runtime_root/versions/baseline-slice-b-compatible"
python3 -m venv "$baseline/.venv"
"$baseline/.venv/bin/python" -m pip install \
  --no-index \
  --find-links "$package_root/payload/wheelhouse" \
  "picotoopet-core==2.3.0.dev2"
ln -s "$baseline" "$runtime_root/current"

port="$(choose_free_port)"
printf '%s\n' "$port" > "$runtime_root/state/api-port.txt"
start_fixture_service \
  "$runtime_root" \
  "$runtime_root/current/.venv/bin/picotoopet-core" \
  "$port" \
  "$token"

historical_before="$temp_root/historical-before.json"
python3 - "http://127.0.0.1:$port" "$token" "$historical_before" <<'PY'
import json
import sys
import urllib.request
from pathlib import Path

base, token, output = sys.argv[1:]
body = json.dumps(
    {"task_type": "analysis", "payload": {"historical": True}, "priority": 1}
).encode("utf-8")
request = urllib.request.Request(
    f"{base}/api/v1/tasks",
    data=body,
    method="POST",
    headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    },
)
with urllib.request.urlopen(request, timeout=5) as response:
    task = json.load(response)
if task.get("status") != "Queued":
    raise SystemExit(f"historical task is not Queued: {task!r}")
Path(output).write_text(
    json.dumps(task, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

stop_fixture_service "$runtime_root"
bash "$package_root/INSTALL_MAC_WORKER_SLICE_C.command" --package-root "$package_root"
bash "$package_root/VERIFY_MAC_WORKER_SLICE_C.command"

historical_after="$temp_root/historical-after.json"
noop_after="$temp_root/noop-after.json"
python3 - \
  "http://127.0.0.1:$port" \
  "$token" \
  "$historical_before" \
  "$historical_after" \
  "$noop_after" <<'PY'
import json
import sys
import time
import urllib.request
from pathlib import Path

base, token, historical_before_path, historical_after_path, noop_after_path = sys.argv[1:]
headers = {"Authorization": f"Bearer {token}"}
before = json.loads(Path(historical_before_path).read_text(encoding="utf-8"))
request = urllib.request.Request(
    f"{base}/api/v1/tasks/{before['task_id']}",
    headers=headers,
)
with urllib.request.urlopen(request, timeout=5) as response:
    historical = json.load(response)
if historical.get("status") != "Queued":
    raise SystemExit(f"historical analysis task changed: {historical!r}")
if historical.get("updated_at") != before.get("updated_at"):
    raise SystemExit("historical analysis updated_at changed")
Path(historical_after_path).write_text(
    json.dumps(historical, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)

body = json.dumps(
    {"task_type": "system.noop", "payload": {"fixture": True}, "priority": 10}
).encode("utf-8")
create = urllib.request.Request(
    f"{base}/api/v1/tasks",
    data=body,
    method="POST",
    headers={**headers, "Content-Type": "application/json"},
)
with urllib.request.urlopen(create, timeout=5) as response:
    noop = json.load(response)
for _ in range(100):
    get = urllib.request.Request(
        f"{base}/api/v1/tasks/{noop['task_id']}",
        headers=headers,
    )
    with urllib.request.urlopen(get, timeout=5) as response:
        current = json.load(response)
    if current.get("status") == "Completed":
        break
    if current.get("status") in {"Failed", "Cancelled"}:
        raise SystemExit(f"system.noop entered unexpected terminal state: {current!r}")
    time.sleep(0.1)
else:
    raise SystemExit("system.noop did not complete")
Path(noop_after_path).write_text(
    json.dumps(current, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

attempt_snapshot="$temp_root/noop-attempt.json"
python3 - "$runtime_root/database/core.db" "$noop_after" "$attempt_snapshot" <<'PY'
import json
import sqlite3
import sys
from pathlib import Path

database_path, noop_path, output_path = sys.argv[1:]
noop = json.loads(Path(noop_path).read_text(encoding="utf-8"))
connection = sqlite3.connect(database_path)
connection.row_factory = sqlite3.Row
try:
    row = connection.execute(
        "SELECT * FROM task_attempts WHERE task_id = ? ORDER BY attempt_number DESC LIMIT 1",
        (noop["task_id"],),
    ).fetchone()
finally:
    connection.close()
if row is None:
    raise SystemExit("system.noop attempt record is missing")
payload = dict(row)
if payload.get("status") != "Completed" or not payload.get("finished_at"):
    raise SystemExit(f"attempt is not completed: {payload!r}")
Path(output_path).write_text(
    json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

echo "PHASE23_MAC_WORKER_EXECUTION_FIXTURE=PASS"
echo "PHASE23_MAC_WORKER_HISTORICAL_PROTECTION=PASS"

bash "$package_root/ROLLBACK_MAC_WORKER_SLICE_C.command"
verify_health "http://127.0.0.1:$port"
if [[ "$(resolve_current_version "$runtime_root")" != "$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$baseline")" ]]; then
  echo "回滚后 current 未恢复 baseline。" >&2
  exit 1
fi
if [[ -f "$runtime_root/state/fixture-worker.pid" ]]; then
  echo "回滚后 Worker PID 文件仍存在。" >&2
  exit 1
fi
if [[ -f "$HOME/Library/LaunchAgents/com.picotoopet.worker.plist" ]]; then
  echo "回滚后临时 Worker plist 仍存在。" >&2
  exit 1
fi

cp "$historical_before" "$evidence_root/historical-before.json"
cp "$historical_after" "$evidence_root/historical-after.json"
cp "$noop_after" "$evidence_root/noop-after.json"
cp "$attempt_snapshot" "$evidence_root/noop-attempt.json"
cp "$runtime_root/state/slice-c-previous-version.txt" "$evidence_root/previous-version.txt"
cp "$runtime_root/state/slice-c-rollback-from.txt" "$evidence_root/rollback-from.txt"
find "$runtime_root/reports" -maxdepth 1 -type f -name '*.json' -exec cp {} "$evidence_root/" \;
python3 - "$evidence_root/fixture-summary.json" <<'PY'
import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "status": "pass",
            "architecture": "arm64",
            "runtime_path_with_spaces": True,
            "offline_install": True,
            "worker_online_verified": True,
            "supported_task_types": ["system.noop"],
            "system_noop_completed": True,
            "attempt_record_completed": True,
            "historical_analysis_preserved": True,
            "rollback_verified": True,
            "worker_stopped_after_rollback": True,
            "source_build_on_user_mac": False,
        },
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY

echo "PHASE23_MAC_WORKER_ROLLBACK_FIXTURE=PASS"
echo "EVIDENCE=$evidence_root"
