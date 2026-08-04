#!/bin/bash
# 在临时含空格目录中验证 Slice D Core 离线安装、现有 Worker 保持、历史任务保护和回滚。
set -euo pipefail

release_root="${1:-}"
if [[ -z "$release_root" || ! -d "$release_root" ]]; then
  echo "用法：$0 <release-root>" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "$0")" && pwd)"
bash "$script_dir/Test-MacCoreSliceBDelta.sh" "$release_root"

archive="$(find "$release_root" -maxdepth 1 -type f \
  -name 'PicotooPet-MacCore-*.tar.gz' -print | sort | tail -n 1)"
temp_root="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-mac-core-fixture.XXXXXX")"
extract_root="$temp_root/package"
runtime_root="$temp_root/Application Support/PicotooPetV2"
evidence_root="$release_root/fixture-evidence"
mkdir -p \
  "$extract_root" \
  "$runtime_root/versions" \
  "$runtime_root/state" \
  "$runtime_root/logs" \
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
package_version="$(read_manifest "$package_root" package_version)"
product_version="$(phase23_product_version "$package_root")"
if [[ "$(read_manifest "$package_root" product_version)" != "$product_version" ]]; then
  echo "Fixture Manifest product_version 不一致。" >&2
  exit 1
fi

cleanup() {
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
token="fixture-token-0123456789abcdef0123456789"
export PICOTOO_RUNTIME_ROOT_OVERRIDE="$runtime_root"
export PICOTOO_API_TOKEN="$token"
export PICOTOO_FIXTURE_MODE=1

# 模拟用户已经安装并运行 Slice C Worker；Core 升级不得要求它不存在。
python3 - "$runtime_root/state/worker-status.json" <<'PY'
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

now = datetime.now(UTC).isoformat()
Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "schema_version": "2.3.0",
            "available": True,
            "state": "online",
            "reason": "idle",
            "worker_id": "picotoopet-m4-fixture",
            "supported_task_types": ["system.diagnostic_snapshot", "system.noop"],
            "active_task_id": None,
            "last_heartbeat_at": now,
            "observed_at": now,
        },
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY
cp "$runtime_root/state/worker-status.json" "$temp_root/worker-before.json"

start_fixture_service \
  "$runtime_root" \
  "$runtime_root/current/.venv/bin/picotoopet-core" \
  "$port" \
  "$token"

before_snapshot="$temp_root/queued-before.json"
python3 - "http://127.0.0.1:$port" "$token" "$before_snapshot" <<'PY'
import json
import sys
import urllib.request
from pathlib import Path

base, token, output = sys.argv[1:]
body = json.dumps(
    {"task_type": "analysis", "payload": {"fixture": True}},
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
    raise SystemExit(f"fixture task is not Queued: {task!r}")
Path(output).write_text(
    json.dumps(task, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

stop_fixture_service "$runtime_root"
bash "$package_root/INSTALL_MAC_CORE_SLICE_B.command" --package-root "$package_root"
bash "$package_root/VERIFY_MAC_CORE_SLICE_B.command"

active_product_version="$("$runtime_root/current/.venv/bin/python" - <<'PY'
from picotoopet_core import __version__
print(__version__)
PY
)"
if [[ "$active_product_version" != "$product_version" ]]; then
  echo "Fixture 激活 Core 产品版本不一致：expected=$product_version actual=$active_product_version" >&2
  exit 1
fi

after_snapshot="$temp_root/queued-after.json"
worker_after="$temp_root/worker-after.json"
python3 - \
  "http://127.0.0.1:$port" \
  "$token" \
  "$before_snapshot" \
  "$after_snapshot" \
  "$worker_after" <<'PY'
import json
import sys
import urllib.request
from pathlib import Path

base, token, before_path, after_path, worker_path = sys.argv[1:]
headers = {"Authorization": f"Bearer {token}"}
before = json.loads(Path(before_path).read_text(encoding="utf-8"))
request = urllib.request.Request(
    f"{base}/api/v1/tasks/{before['task_id']}",
    headers=headers,
)
with urllib.request.urlopen(request, timeout=5) as response:
    after = json.load(response)
if after.get("status") != "Queued":
    raise SystemExit(f"historical task changed state: {after!r}")
if after.get("updated_at") != before.get("updated_at"):
    raise SystemExit("historical Queued task updated_at changed during verification")
Path(after_path).write_text(
    json.dumps(after, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)

worker_request = urllib.request.Request(
    f"{base}/api/v1/workers/status",
    headers=headers,
)
with urllib.request.urlopen(worker_request, timeout=5) as response:
    worker = json.load(response)
if worker.get("state") != "online" or worker.get("available") is not True:
    raise SystemExit(f"existing Worker state was not preserved: {worker!r}")
if worker.get("worker_id") != "picotoopet-m4-fixture":
    raise SystemExit(f"existing Worker identity changed: {worker!r}")
Path(worker_path).write_text(
    json.dumps(worker, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

echo "PHASE23_MAC_DELTA_INSTALL_FIXTURE=PASS"
echo "PHASE23_MAC_DELTA_QUEUED_PRESERVATION=PASS"
echo "PHASE23_MAC_SLICE_D_CORE_WORKER_PRESERVATION=PASS"
echo "PHASE23_MAC_SLICE_D_CORE_PRODUCT_VERSION=PASS"

bash "$package_root/ROLLBACK_MAC_CORE_SLICE_B.command"
start_fixture_service \
  "$runtime_root" \
  "$runtime_root/current/.venv/bin/picotoopet-core" \
  "$port" \
  "$token"
verify_health "http://127.0.0.1:$port"

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

cp "$before_snapshot" "$evidence_root/queued-before.json"
cp "$after_snapshot" "$evidence_root/queued-after.json"
cp "$temp_root/worker-before.json" "$evidence_root/worker-before.json"
cp "$worker_after" "$evidence_root/worker-after.json"
cp "$runtime_root/state/previous-version.txt" "$evidence_root/previous-version.txt"
cp "$runtime_root/state/rollback-from.txt" "$evidence_root/rollback-from.txt"
find "$runtime_root/reports" -maxdepth 1 -type f -name '*.json' -exec cp {} "$evidence_root/" \;
python3 - \
  "$evidence_root/fixture-summary.json" \
  "$(uname -m)" \
  "$package_version" \
  "$product_version" <<'PY'
import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "status": "pass",
            "architecture": sys.argv[2],
            "package_version": sys.argv[3],
            "product_version": sys.argv[4],
            "runtime_version": "2.3.0-slice-d-core",
            "offline_install": True,
            "queued_task_preserved": True,
            "existing_worker_state_preserved": True,
            "diagnostic_api_verified": True,
            "active_product_version_verified": True,
            "rollback_verified": True,
            "runtime_path_with_spaces": True,
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

echo "PHASE23_MAC_DELTA_ROLLBACK_FIXTURE=PASS"
echo "PHASE23_MAC_SLICE_D_CORE_FIXTURE=PASS"
echo "PRODUCT_VERSION=$product_version"
echo "EVIDENCE=$evidence_root"
