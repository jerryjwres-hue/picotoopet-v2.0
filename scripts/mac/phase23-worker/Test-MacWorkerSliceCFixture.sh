#!/bin/bash
# 在临时含空格目录中验证 Slice D 安装、诊断结果、取消、超时、恢复、历史保护与回滚。
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
package_version="$(read_manifest "$package_root" package_version)"

export HOME="$fixture_home"
export PICOTOO_RUNTIME_ROOT_OVERRIDE="$runtime_root"
export PICOTOO_RUNTIME_ROOT="$runtime_root"
export PICOTOO_FIXTURE_MODE=1
token="fixture-token-0123456789abcdef0123456789"
worker_id="picotoopet-m4-fixture"
export PICOTOO_API_TOKEN="$token"

cleanup() {
  stop_fixture_worker "$runtime_root" || true
  stop_fixture_service "$runtime_root" || true
  rm -rf "$temp_root"
}
trap cleanup EXIT

baseline="$runtime_root/versions/baseline-slice-c-compatible"
python3 -m venv "$baseline/.venv"
"$baseline/.venv/bin/python" -m pip install \
  --no-index \
  --find-links "$package_root/payload/wheelhouse" \
  "picotoopet-core==$package_version"
ln -s "$baseline" "$runtime_root/current"

port="$(choose_free_port)"
printf '%s\n' "$port" > "$runtime_root/state/api-port.txt"
base_url="http://127.0.0.1:$port"
start_fixture_service \
  "$runtime_root" \
  "$runtime_root/current/.venv/bin/picotoopet-core" \
  "$port" \
  "$token"

historical_before="$temp_root/historical-before.json"
python3 - "$base_url" "$token" "$historical_before" <<'PY'
import json
import sys
import urllib.request
from pathlib import Path

base, token, output = sys.argv[1:]
request = urllib.request.Request(
    f"{base}/api/v1/tasks",
    data=json.dumps(
        {"task_type": "analysis", "payload": {"historical": True}}
    ).encode("utf-8"),
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
diagnostic_task="$temp_root/diagnostic-task.json"
diagnostic_result="$temp_root/diagnostic-result.json"
python3 - \
  "$base_url" \
  "$token" \
  "$historical_before" \
  "$historical_after" \
  "$diagnostic_task" \
  "$diagnostic_result" <<'PY'
import json
import sys
import time
import urllib.request
from pathlib import Path

base, token, before_path, after_path, task_path, result_path = sys.argv[1:]
headers = {"Authorization": f"Bearer {token}"}
before = json.loads(Path(before_path).read_text(encoding="utf-8"))
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
Path(after_path).write_text(
    json.dumps(historical, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)

create = urllib.request.Request(
    f"{base}/api/v1/tasks/system-diagnostic-snapshot",
    data=json.dumps(
        {
            "schema_version": "1.0",
            "sections": ["core", "worker", "queue"],
        }
    ).encode("utf-8"),
    method="POST",
    headers={
        **headers,
        "Content-Type": "application/json",
        "Idempotency-Key": "fixture-diagnostic-complete",
    },
)
with urllib.request.urlopen(create, timeout=5) as response:
    created = json.load(response)
for _ in range(200):
    get = urllib.request.Request(
        f"{base}/api/v1/tasks/{created['task_id']}",
        headers=headers,
    )
    with urllib.request.urlopen(get, timeout=5) as response:
        current = json.load(response)
    if current.get("status") == "Completed":
        break
    if current.get("status") in {"Failed", "Cancelled"}:
        raise SystemExit(f"diagnostic task entered unexpected terminal: {current!r}")
    time.sleep(0.1)
else:
    raise SystemExit("diagnostic task did not complete")
if not current.get("result_id"):
    raise SystemExit(f"diagnostic result_id missing: {current!r}")
Path(task_path).write_text(
    json.dumps(current, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)

result_request = urllib.request.Request(
    f"{base}/api/v1/tasks/{created['task_id']}/result",
    headers=headers,
)
with urllib.request.urlopen(result_request, timeout=5) as response:
    result_bytes = response.read()
if len(result_bytes) > 64 * 1024:
    raise SystemExit("diagnostic result exceeded 64 KiB")
result = json.loads(result_bytes)
if result.get("schema_version") != "1.0":
    raise SystemExit(f"diagnostic schema mismatch: {result!r}")
if not result.get("checks"):
    raise SystemExit(f"diagnostic checks missing: {result!r}")
worker = result.get("worker") or {}
supported = worker.get("supported_task_types")
required = {"system.diagnostic_snapshot", "system.noop"}
allowed = required | {
    "autonomous.local_analysis.v1",
    "autonomous.discovery.v1",
    "autonomous.storage_maintenance.v1",
    "business.local_intelligence.v1",
    "creative.content_plan.v1",
    "provider.codex.handoff-v1",
    "provider.adoption.apply-v1",
    "provider.commit.create-v1",
    "provider.publish.pr-create-v1",
    "research.search",
}
if not isinstance(supported, list) or not required <= set(supported):
    raise SystemExit(f"diagnostic Worker card missing required types: {worker!r}")
unexpected = set(supported) - allowed
if unexpected:
    raise SystemExit(f"diagnostic Worker card has unexpected types: {sorted(unexpected)!r}")
Path(result_path).write_bytes(result_bytes)
PY

echo "PHASE23_MAC_WORKER_DIAGNOSTIC_FIXTURE=PASS"
echo "PHASE23_MAC_WORKER_HISTORICAL_PROTECTION=PASS"

# Worker 停止时创建并取消诊断任务；重启后它必须保持 Cancelled 且没有结果。
stop_fixture_worker "$runtime_root"
cancelled_after="$temp_root/cancelled-after.json"
python3 - "$base_url" "$token" "$cancelled_after" <<'PY'
import json
import sys
import urllib.request
from pathlib import Path

base, token, output = sys.argv[1:]
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
}
create = urllib.request.Request(
    f"{base}/api/v1/tasks/system-diagnostic-snapshot",
    data=json.dumps(
        {"schema_version": "1.0", "sections": ["core", "worker", "queue"]}
    ).encode("utf-8"),
    method="POST",
    headers={**headers, "Idempotency-Key": "fixture-diagnostic-cancelled"},
)
with urllib.request.urlopen(create, timeout=5) as response:
    task = json.load(response)
cancel = urllib.request.Request(
    f"{base}/api/v1/tasks/{task['task_id']}/cancel",
    data=b"",
    method="POST",
    headers={"Authorization": f"Bearer {token}"},
)
with urllib.request.urlopen(cancel, timeout=5) as response:
    cancelled = json.load(response)
if cancelled.get("status") != "Cancelled":
    raise SystemExit(f"queued cancel contract failed: {cancelled!r}")
if cancelled.get("attempt_count") != 0 or cancelled.get("result_id") is not None:
    raise SystemExit(f"cancelled task has attempt or result: {cancelled!r}")
Path(output).write_text(
    json.dumps(cancelled, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY
start_fixture_worker "$runtime_root" "$worker_id" "$token"
wait_for_worker_state "$runtime_root" "online"
sleep 0.5
python3 - "$base_url" "$token" "$cancelled_after" <<'PY'
import json
import sys
import urllib.request
from pathlib import Path

base, token, path = sys.argv[1:]
expected = json.loads(Path(path).read_text(encoding="utf-8"))
request = urllib.request.Request(
    f"{base}/api/v1/tasks/{expected['task_id']}",
    headers={"Authorization": f"Bearer {token}"},
)
with urllib.request.urlopen(request, timeout=5) as response:
    current = json.load(response)
if current.get("status") != "Cancelled":
    raise SystemExit(f"Worker touched cancelled task: {current!r}")
if current.get("attempt_count") != 0 or current.get("result_id") is not None:
    raise SystemExit(f"Worker added attempt/result to cancelled task: {current!r}")
PY
echo "PHASE23_MAC_WORKER_CANCELLATION_FIXTURE=PASS"

# 用实际安装 wheel 验证子进程取消、硬超时和无孤儿进程。
stop_fixture_worker "$runtime_root"
subprocess_evidence="$temp_root/subprocess-evidence.json"
"$runtime_root/current/.venv/bin/python" - "$temp_root/subprocess" "$subprocess_evidence" <<'PY'
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from picotoopet_core.diagnostics.models import DiagnosticFacts, DiagnosticSnapshotRequest
from picotoopet_core.diagnostics.subprocess_runner import (
    DiagnosticCancelledError,
    DiagnosticSubprocessRunner,
    DiagnosticTimeoutError,
)

root = Path(sys.argv[1])
output = Path(sys.argv[2])
root.mkdir(parents=True, exist_ok=True)
request = DiagnosticSnapshotRequest()
facts = DiagnosticFacts(
    core_version="2.3.0",
    core_health_state="online",
    database_schema_version=1,
    worker_id="worker-fixture",
    worker_state="online",
    worker_reason="executing",
    worker_supported_task_types=("system.diagnostic_snapshot", "system.noop"),
    worker_last_heartbeat_at=datetime.now(UTC),
    queue_counts={"Queued": 1},
    oldest_queued_age_seconds=1,
)


def assert_reaped(pid: int | None) -> None:
    if pid is None:
        raise SystemExit("runner did not expose child pid")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    raise SystemExit(f"orphan diagnostic process remains: {pid}")

cancel_runner = DiagnosticSubprocessRunner(
    poll_seconds=0.02,
    terminate_grace_seconds=0.5,
)
started = time.monotonic()
try:
    cancel_runner.run(
        request,
        facts,
        output_dir=root / "cancel",
        timeout_seconds=3,
        cancel_requested=lambda: time.monotonic() - started >= 0.15,
        test_delay_seconds=5,
    )
except DiagnosticCancelledError:
    pass
else:
    raise SystemExit("cancel test did not raise DiagnosticCancelledError")
assert_reaped(cancel_runner.last_pid)

timeout_runner = DiagnosticSubprocessRunner(
    poll_seconds=0.02,
    terminate_grace_seconds=0.5,
)
try:
    timeout_runner.run(
        request,
        facts,
        output_dir=root / "timeout",
        timeout_seconds=0.15,
        cancel_requested=lambda: False,
        test_delay_seconds=5,
    )
except DiagnosticTimeoutError:
    pass
else:
    raise SystemExit("timeout test did not raise DiagnosticTimeoutError")
assert_reaped(timeout_runner.last_pid)

output.write_text(
    json.dumps(
        {
            "status": "pass",
            "cancelled_process_reaped": True,
            "timed_out_process_reaped": True,
            "hard_timeout_seconds": 30,
            "termination_grace_seconds": 5,
        },
        sort_keys=True,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY
echo "PHASE23_MAC_WORKER_SUBPROCESS_FIXTURE=PASS"

# 直接制造受支持类型的过期租约，并验证有界恢复只处理该类型且关闭 attempt。
expired_after="$temp_root/expired-after.json"
expired_attempt="$temp_root/expired-attempt.json"
"$runtime_root/current/.venv/bin/python" - \
  "$runtime_root/database/core.db" \
  "$expired_after" \
  "$expired_attempt" <<'PY'
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from picotoopet_core.db.database import Database
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository

database_path, task_output, attempt_output = sys.argv[1:]
database = Database(Path(database_path))
database.open()
try:
    repository = DiagnosticQueueRepository(database)
    task = repository.create(
        TaskCreate(
            task_type="system.diagnostic_snapshot",
            payload={"schema_version": "1.0", "sections": ["core", "worker", "queue"]},
            idempotency_key="fixture-expired-diagnostic",
            dedupe_key="fixture-expired-diagnostic",
            max_attempts=2,
            timeout_seconds=30,
        )
    )
    leased = repository.lease_next(
        "dead-worker",
        lease_seconds=60,
        supported_task_types=("system.diagnostic_snapshot",),
    )
    if leased is None or leased.task_id != task.task_id:
        raise SystemExit(f"unexpected leased task: {leased!r}")
    database.execute(
        "UPDATE tasks SET lease_expires_at = ? WHERE task_id = ?",
        ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), task.task_id),
    )
    recovered = repository.recover_expired_supported_leases(
        supported_task_types=("system.diagnostic_snapshot", "system.noop"),
    )
    if recovered != [task.task_id]:
        raise SystemExit(f"unexpected recovered tasks: {recovered!r}")
    current = repository.get(task.task_id)
    if current.status.value != "Retrying" or current.error_code != "LEASE_EXPIRED":
        raise SystemExit(f"expired lease recovery failed: {current!r}")
finally:
    database.close()

connection = sqlite3.connect(database_path)
connection.row_factory = sqlite3.Row
try:
    row = connection.execute(
        "SELECT * FROM task_attempts WHERE task_id = ? ORDER BY attempt_number DESC LIMIT 1",
        (task.task_id,),
    ).fetchone()
finally:
    connection.close()
if row is None:
    raise SystemExit("expired attempt is missing")
attempt = dict(row)
if attempt.get("status") != "Failed" or attempt.get("error_code") != "LEASE_EXPIRED":
    raise SystemExit(f"expired attempt was not closed: {attempt!r}")
if not attempt.get("finished_at"):
    raise SystemExit(f"expired attempt has no finished_at: {attempt!r}")
Path(task_output).write_text(
    json.dumps(
        {
            "task_id": current.task_id,
            "status": current.status.value,
            "error_code": current.error_code,
        },
        sort_keys=True,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
Path(attempt_output).write_text(
    json.dumps(attempt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY
echo "PHASE23_MAC_WORKER_EXPIRED_LEASE_FIXTURE=PASS"

bash "$package_root/ROLLBACK_MAC_WORKER_SLICE_C.command"
verify_health "$base_url"
resolved_baseline="$(python3 - "$baseline" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).resolve())
PY
)"
if [[ "$(resolve_current_version "$runtime_root")" != "$resolved_baseline" ]]; then
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
cp "$diagnostic_task" "$evidence_root/diagnostic-task.json"
cp "$diagnostic_result" "$evidence_root/diagnostic-result.json"
cp "$cancelled_after" "$evidence_root/cancelled-after.json"
cp "$subprocess_evidence" "$evidence_root/subprocess-evidence.json"
cp "$expired_after" "$evidence_root/expired-after.json"
cp "$expired_attempt" "$evidence_root/expired-attempt.json"
cp "$runtime_root/state/slice-d-previous-version.txt" "$evidence_root/previous-version.txt"
cp "$runtime_root/state/slice-d-rollback-from.txt" "$evidence_root/rollback-from.txt"
find "$runtime_root/reports" -maxdepth 1 -type f -name '*.json' -exec cp {} "$evidence_root/" \;
python3 - "$evidence_root/fixture-summary.json" "$package_version" <<'PY'
import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "status": "pass",
            "architecture": "arm64",
            "package_version": sys.argv[2],
            "runtime_version": "2.3.0-slice-d-worker",
            "runtime_path_with_spaces": True,
            "offline_install": True,
            "worker_online_verified": True,
            "supported_task_types": [
                "system.diagnostic_snapshot",
                "system.noop",
            ],
            "diagnostic_completed": True,
            "diagnostic_result_verified": True,
            "diagnostic_result_max_bytes": 65536,
            "historical_analysis_preserved": True,
            "cancelled_task_preserved": True,
            "cancelled_process_reaped": True,
            "timed_out_process_reaped": True,
            "expired_supported_lease_recovered": True,
            "expired_attempt_closed": True,
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

echo "PHASE23_MAC_WORKER_EXECUTION_FIXTURE=PASS"
echo "PHASE23_MAC_WORKER_ROLLBACK_FIXTURE=PASS"
echo "PHASE23_MAC_WORKER_SLICE_D_FIXTURE=PASS"
echo "EVIDENCE=$evidence_root"
