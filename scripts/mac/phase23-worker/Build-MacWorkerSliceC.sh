#!/bin/bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
output_root="$repo_root/artifacts/mac-worker-slice-d/arm64"
version_label=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-root) output_root="$2"; shift 2 ;;
    --version-label) version_label="$2"; shift 2 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done
python_version="$(python3 --version 2>&1)"
[[ "$python_version" == Python\ 3.12.* ]] || { echo "构建必须使用 Python 3.12：$python_version" >&2; exit 1; }
[[ "$(uname -m)" == "arm64" ]] || { echo "Slice D Worker 只支持 arm64。" >&2; exit 1; }
commit="$(git -C "$repo_root" rev-parse HEAD 2>/dev/null || printf unknown)"
[[ -n "$version_label" ]] || version_label="2.3.0-slice-d-worker-local-${commit:0:12}"
[[ "$version_label" =~ ^[A-Za-z0-9._-]+$ ]] || exit 1
mkdir -p "$output_root"
staging_parent="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-worker-build.XXXXXX")"
trap 'rm -rf "$staging_parent"' EXIT
package_name="PicotooPet-MacWorker-${version_label}-arm64"
package_root="$staging_parent/$package_name"
wheelhouse="$package_root/payload/wheelhouse"
mkdir -p "$wheelhouse"
python3 -m pip wheel --wheel-dir "$wheelhouse" "$repo_root"
package_version="$(python3 - "$repo_root/pyproject.toml" "$wheelhouse" <<'PY'
import sys, tomllib
from pathlib import Path
version = tomllib.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["project"]["version"]
wheels = list(Path(sys.argv[2]).glob("picotoopet_core-*.whl"))
if len(wheels) != 1 or not wheels[0].name.startswith(f"picotoopet_core-{version.replace('-', '_')}-"):
    raise SystemExit("project wheel/version mismatch")
print(version)
PY
)"
cp "$repo_root/deploy/macos/phase23/lib.sh" "$package_root/lib.sh"
for file in INSTALL_MAC_WORKER_SLICE_C.command VERIFY_MAC_WORKER_SLICE_C.command ROLLBACK_MAC_WORKER_SLICE_C.command worker-lib.sh README_INSTALL_CN.txt; do cp "$repo_root/deploy/macos/phase23-worker/$file" "$package_root/$file"; done
chmod 755 "$package_root"/*.command "$package_root"/*.sh
python3 - "$package_root" "$version_label" "$python_version" "$commit" "$package_version" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
files=[]
for path in sorted(p for p in root.rglob("*") if p.is_file()):
    rel=path.relative_to(root).as_posix()
    if rel == "release-manifest.json": continue
    raw=path.read_bytes(); files.append({"path":rel,"sha256":hashlib.sha256(raw).hexdigest(),"size_bytes":len(raw)})
manifest={
 "schema_version":"1.0","release_type":"prebuilt-offline-worker","target":"macos",
 "version":sys.argv[2],"package_version":sys.argv[5],"runtime_version":"2.3.0-slice-d-worker",
 "api_schema_version":"2.3.0","architecture":"arm64","python_version":sys.argv[3],"commit":sys.argv[4],
 "worker_runtime_included":True,"worker_supported_task_types":["system.diagnostic_snapshot","system.noop"],
 "diagnostic_hard_timeout_seconds":30,"diagnostic_termination_grace_seconds":5,
 "source_build_on_user_mac":False,"files":files}
(root/"release-manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
PY
rm -f "$output_root"/PicotooPet-MacWorker-"$version_label"-arm64.tar.gz*
tarball="$output_root/$package_name.tar.gz"
tar -czf "$tarball" -C "$staging_parent" "$package_name"
sha="$(shasum -a 256 "$tarball" | awk '{print tolower($1)}')"
printf '%s  %s\n' "$sha" "$(basename "$tarball")" > "$tarball.sha256.txt"
python3 - "$output_root/mac-worker-build-report.json" "$version_label" "$python_version" "$commit" "$tarball" "$sha" "$package_version" <<'PY'
import json, sys
from pathlib import Path
report={"status":"pass","version":sys.argv[2],"runtime_version":"2.3.0-slice-d-worker","package_version":sys.argv[7],"architecture":"arm64","python_version":sys.argv[3],"commit":sys.argv[4],"package":str(Path(sys.argv[5]).resolve()),"sha256":sys.argv[6],"source_build_on_user_mac":False,"worker_runtime_included":True,"worker_supported_task_types":["system.diagnostic_snapshot","system.noop"],"diagnostic_hard_timeout_seconds":30,"diagnostic_termination_grace_seconds":5}
Path(sys.argv[1]).write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")
PY
echo "PHASE23_MAC_WORKER_SLICE_D_BUILD=PASS"
echo "PACKAGE=$tarball"
echo "SHA256=$sha"
