#!/bin/bash
# 在临时目录中验证离线安装、API 合同、历史 Queued 保持和回滚。
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
temp_root="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-mac-fixture.XXXXXX")"
extract_root="$temp_root/package"
runtime_root="$temp_root/runtime"
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

cleanup() {
  stop_fixture_service "$runtime_root" || true
  rm -rf "$temp_root"
}
trap cleanup EXIT

baseline="$runtime_root/versions/baseline"
python3 -m venv "$baseline/.venv"
"$baseline/.venv/bin/python" -m pip install \
  --no-index \
  --find-links "$package_root/payload/wheelhouse" \
  "picotoopet-core==2.3.0.dev1"
ln -s "$baseline" "$runtime_root/current"

port="$(choose_free_port)"
printf '%s\n' "$port" > "$runtime_root/state/api-port.txt"
token="fixture-token-0123456789abcdef0123456789"
export PICOTOO_RUNTIME_ROOT_OVERRIDE="$runtime_root"
export PICOTOO_API_TOKEN="$token"
export PICOTOO_FIXTURE_MODE=1

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

after_snapshot="$temp_root/queued-after.json"
python3 - \
  "http://127.0.0.1:$port" \
  "$token" \
  "$before_snapshot" \
  "$after_snapshot" <<'PY'
import json
import sys
import urllib.request
from pathlib import Path

base, token, before_path, after_path = sys.argv[1:]
before = json.loads(Path(before_path).read_text(encoding="utf-8"))
request = urllib.request.Request(
    f"{base}/api/v1/tasks/{before['task_id']}",
    headers={"Authorization": f"Bearer {token}"},
)
with urllib.request.urlopen(request, timeout=5) as response:
    after = json.load(response)
Path(after_path).write_text(
    json.dumps(after, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
if after.get("status") != "Queued":
    raise SystemExit(f"historical task changed state: {after!r}")
if after.get("updated_at") != before.get("updated_at"):
    raise SystemExit("historical Queued task updated_at changed during verification")
PY

echo "PHASE23_MAC_DELTA_INSTALL_FIXTURE=PASS"
echo "PHASE23_MAC_DELTA_QUEUED_PRESERVATION=PASS"

bash "$package_root/ROLLBACK_MAC_CORE_SLICE_B.command"
start_fixture_service \
  "$runtime_root" \
  "$runtime_root/current/.venv/bin/picotoopet-core" \
  "$port" \
  "$token"
verify_health "http://127.0.0.1:$port"

cp "$before_snapshot" "$evidence_root/queued-before.json"
cp "$after_snapshot" "$evidence_root/queued-after.json"
cp "$runtime_root/state/previous-version.txt" "$evidence_root/previous-version.txt"
cp "$runtime_root/state/rollback-from.txt" "$evidence_root/rollback-from.txt"
find "$runtime_root/reports" -maxdepth 1 -type f -name '*.json' -exec cp {} "$evidence_root/" \;
python3 - "$evidence_root/fixture-summary.json" "$(uname -m)" <<'PY'
import json
import sys
from pathlib import Path

Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "status": "pass",
            "architecture": sys.argv[2],
            "offline_install": True,
            "queued_task_preserved": True,
            "rollback_verified": True,
            "worker_runtime_installed": False,
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
echo "EVIDENCE=$evidence_root"
