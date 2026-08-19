#!/bin/bash
# 在原生 M4/arm64 macOS Runner 构建 Slice D Core + Worker 离线包。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
output_root="$repo_root/artifacts/mac-worker-slice-d/arm64"
version_label=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-root)
      output_root="$2"
      shift 2
      ;;
    --version-label)
      version_label="$2"
      shift 2
      ;;
    *)
      echo "未知参数：$1" >&2
      exit 2
      ;;
  esac
done

python_version="$(python3 --version 2>&1)"
if [[ "$python_version" != Python\ 3.12.* ]]; then
  echo "构建必须使用 Python 3.12：$python_version" >&2
  exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "Slice D Worker 用户交付仅支持 M4/Apple Silicon arm64。" >&2
  exit 1
fi

product_version_file="$repo_root/src/picotoopet_core/product-version.txt"
if [[ ! -f "$product_version_file" ]]; then
  echo "缺少唯一产品版本源：$product_version_file" >&2
  exit 1
fi
product_version="$(tr -d '\r\n' < "$product_version_file")"
if [[ ! "$product_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "产品版本必须是四段数字：$product_version" >&2
  exit 1
fi

commit="$(git -C "$repo_root" rev-parse HEAD 2>/dev/null || printf 'unknown')"
short_commit="${commit:0:12}"
if [[ -z "$version_label" ]]; then
  version_label="2.3.0-slice-d-worker-local-$short_commit"
fi
if [[ ! "$version_label" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "版本标签只能包含 ASCII 字母、数字、点、下划线和连字符。" >&2
  exit 1
fi

mkdir -p "$output_root"
staging_parent="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-worker-build.XXXXXX")"
package_name="PicotooPet-MacWorker-${product_version}-${version_label}-arm64"
package_root="$staging_parent/$package_name"
wheelhouse="$package_root/payload/wheelhouse"
cleanup() {
  rm -rf "$staging_parent"
}
trap cleanup EXIT

mkdir -p "$wheelhouse"
python3 -m pip wheel --wheel-dir "$wheelhouse" "$repo_root"
if find "$wheelhouse" -type f ! -name '*.whl' | grep -q .; then
  echo "wheelhouse 包含非 wheel 文件。" >&2
  exit 1
fi

package_version="$(python3 - "$repo_root/pyproject.toml" "$wheelhouse" <<'PY'
import sys
import tomllib
from pathlib import Path

pyproject = Path(sys.argv[1])
wheelhouse = Path(sys.argv[2])
version = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
wheels = sorted(wheelhouse.glob("picotoopet_core-*.whl"))
if len(wheels) != 1:
    raise SystemExit(f"expected exactly one picotoopet_core wheel, found {len(wheels)}")
expected_prefix = f"picotoopet_core-{version.replace('-', '_')}-"
if not wheels[0].name.startswith(expected_prefix):
    raise SystemExit(
        f"project version {version!r} does not match wheel {wheels[0].name!r}"
    )
print(version)
PY
)"

cp "$repo_root/deploy/macos/phase23/lib.sh" "$package_root/lib.sh"
for file in \
  INSTALL_MAC_WORKER_SLICE_C.command \
  VERIFY_MAC_WORKER_SLICE_C.command \
  VERIFY_GOAL_CENTER_E2E.command \
  ROLLBACK_MAC_WORKER_SLICE_C.command \
  worker-lib.sh \
  README_INSTALL_CN.txt; do
  cp "$repo_root/deploy/macos/phase23-worker/$file" "$package_root/$file"
done
cp "$product_version_file" "$package_root/product-version.txt"
chmod 755 \
  "$package_root/INSTALL_MAC_WORKER_SLICE_C.command" \
  "$package_root/VERIFY_MAC_WORKER_SLICE_C.command" \
  "$package_root/VERIFY_GOAL_CENTER_E2E.command" \
  "$package_root/ROLLBACK_MAC_WORKER_SLICE_C.command" \
  "$package_root/lib.sh" \
  "$package_root/worker-lib.sh"

python3 - \
  "$package_root" \
  "$version_label" \
  "$python_version" \
  "$commit" \
  "$package_version" \
  "$product_version" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
files = []
for path in sorted(item for item in root.rglob("*") if item.is_file()):
    relative = path.relative_to(root).as_posix()
    if relative == "release-manifest.json":
        continue
    content = path.read_bytes()
    files.append(
        {
            "path": relative,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
    )
manifest = {
    "schema_version": "1.0",
    "release_type": "prebuilt-offline-worker",
    "target": "macos",
    "version": sys.argv[2],
    "product_version": sys.argv[6],
    "package_version": sys.argv[5],
    "runtime_version": "2.3.0-slice-d-worker",
    "api_schema_version": "2.3.0",
    "architecture": "arm64",
    "python_version": sys.argv[3],
    "commit": sys.argv[4],
    "worker_runtime_included": True,
    "worker_supported_task_types": [
        "system.diagnostic_snapshot",
        "system.noop",
    ],
    "autonomous_slice_c_included": True,
    "autonomous_capabilities": [
        "content.discovery",
        "browser.capture.contract",
        "objective.query.planning",
    ],
    "goal_center_e2e_included": True,
    "goal_center_live_verifier": "VERIFY_GOAL_CENTER_E2E.command",
    "goal_center_runtime_task_types": [
        "autonomous.discovery.v1",
        "autonomous.goal_synthesis.v1",
        "autonomous.goal_handoff.v1",
    ],
    "diagnostic_hard_timeout_seconds": 30,
    "diagnostic_termination_grace_seconds": 5,
    "source_build_on_user_mac": False,
    "files": files,
}
(root / "release-manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

rm -f "$output_root"/PicotooPet-MacWorker-"$product_version"-"$version_label"-arm64.tar.gz*
tarball="$output_root/$package_name.tar.gz"
tar -czf "$tarball" -C "$staging_parent" "$package_name"
outer_sha="$(shasum -a 256 "$tarball" | awk '{print tolower($1)}')"
printf '%s  %s\n' "$outer_sha" "$(basename "$tarball")" > "$tarball.sha256.txt"

python3 - \
  "$output_root/mac-worker-build-report.json" \
  "$version_label" \
  "$python_version" \
  "$commit" \
  "$tarball" \
  "$outer_sha" \
  "$package_version" \
  "$product_version" <<'PY'
import json
import sys
from pathlib import Path

report = {
    "status": "pass",
    "version": sys.argv[2],
    "product_version": sys.argv[8],
    "runtime_version": "2.3.0-slice-d-worker",
    "package_version": sys.argv[7],
    "architecture": "arm64",
    "python_version": sys.argv[3],
    "commit": sys.argv[4],
    "package": str(Path(sys.argv[5]).resolve()),
    "sha256": sys.argv[6],
    "source_build_on_user_mac": False,
    "worker_runtime_included": True,
    "worker_supported_task_types": [
        "system.diagnostic_snapshot",
        "system.noop",
    ],
    "autonomous_slice_c_included": True,
    "autonomous_capabilities": [
        "content.discovery",
        "browser.capture.contract",
        "objective.query.planning",
    ],
    "goal_center_e2e_included": True,
    "goal_center_live_verifier": "VERIFY_GOAL_CENTER_E2E.command",
    "goal_center_runtime_task_types": [
        "autonomous.discovery.v1",
        "autonomous.goal_synthesis.v1",
        "autonomous.goal_handoff.v1",
    ],
    "diagnostic_hard_timeout_seconds": 30,
    "diagnostic_termination_grace_seconds": 5,
}
Path(sys.argv[1]).write_text(
    json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

echo "PHASE23_MAC_WORKER_BUILD=PASS"
echo "PHASE23_MAC_WORKER_SLICE_D_BUILD=PASS"
echo "PACKAGE=$tarball"
echo "SHA256=$outer_sha"
echo "PACKAGE_VERSION=$package_version"
echo "PRODUCT_VERSION=$product_version"
