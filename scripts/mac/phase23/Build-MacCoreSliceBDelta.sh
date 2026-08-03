#!/bin/bash
# 在原生 macOS Runner 构建架构专属、离线可安装的 Mac Core Slice D 增量包。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
output_root="$repo_root/artifacts/mac-slice-b"
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

architecture="$(uname -m)"
case "$architecture" in
  arm64|x86_64) ;;
  *)
    echo "不支持的 Mac 架构：$architecture" >&2
    exit 1
    ;;
esac

commit="$(git -C "$repo_root" rev-parse HEAD 2>/dev/null || printf 'unknown')"
short_commit="${commit:0:12}"
if [[ -z "$version_label" ]]; then
  version_label="2.3.0-slice-d-core-local-$short_commit"
fi
if [[ ! "$version_label" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "版本标签只能包含 ASCII 字母、数字、点、下划线和连字符。" >&2
  exit 1
fi

mkdir -p "$output_root"
staging_parent="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-mac-build.XXXXXX")"
package_name="PicotooPet-MacCore-${version_label}-${architecture}"
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
if [[ -z "$package_version" ]]; then
  echo "无法从 pyproject.toml 解析项目版本。" >&2
  exit 1
fi

for file in \
  INSTALL_MAC_CORE_SLICE_B.command \
  VERIFY_MAC_CORE_SLICE_B.command \
  ROLLBACK_MAC_CORE_SLICE_B.command \
  lib.sh \
  README_INSTALL_CN.txt; do
  cp "$repo_root/deploy/macos/phase23/$file" "$package_root/$file"
done
chmod 755 \
  "$package_root/INSTALL_MAC_CORE_SLICE_B.command" \
  "$package_root/VERIFY_MAC_CORE_SLICE_B.command" \
  "$package_root/ROLLBACK_MAC_CORE_SLICE_B.command" \
  "$package_root/lib.sh"

python3 - \
  "$package_root" \
  "$version_label" \
  "$architecture" \
  "$python_version" \
  "$commit" \
  "$package_version" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
version = sys.argv[2]
architecture = sys.argv[3]
python_version = sys.argv[4]
commit = sys.argv[5]
package_version = sys.argv[6]
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
    "release_type": "prebuilt-offline-delta",
    "target": "macos",
    "version": version,
    "package_version": package_version,
    "runtime_version": "2.3.0-slice-d-core",
    "api_schema_version": "2.3.0",
    "architecture": architecture,
    "python_version": python_version,
    "commit": commit,
    "worker_runtime_included": False,
    "diagnostic_snapshot_api_included": True,
    "source_build_on_user_mac": False,
    "files": files,
}
(root / "release-manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

rm -f "$output_root"/PicotooPet-MacCore-"$version_label"-"$architecture".tar.gz
rm -f "$output_root"/PicotooPet-MacCore-"$version_label"-"$architecture".tar.gz.sha256.txt

tarball="$output_root/$package_name.tar.gz"
tar -czf "$tarball" -C "$staging_parent" "$package_name"
outer_sha="$(shasum -a 256 "$tarball" | awk '{print tolower($1)}')"
printf '%s  %s\n' "$outer_sha" "$(basename "$tarball")" \
  > "$tarball.sha256.txt"

python3 - \
  "$output_root/mac-build-report.json" \
  "$version_label" \
  "$architecture" \
  "$python_version" \
  "$commit" \
  "$tarball" \
  "$outer_sha" \
  "$package_version" <<'PY'
import json
import sys
from pathlib import Path

report = {
    "status": "pass",
    "version": sys.argv[2],
    "runtime_version": "2.3.0-slice-d-core",
    "package_version": sys.argv[8],
    "architecture": sys.argv[3],
    "python_version": sys.argv[4],
    "commit": sys.argv[5],
    "package": str(Path(sys.argv[6]).resolve()),
    "sha256": sys.argv[7],
    "source_build_on_user_mac": False,
    "worker_runtime_included": False,
    "diagnostic_snapshot_api_included": True,
}
Path(sys.argv[1]).write_text(
    json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

echo "PHASE23_MAC_DELTA_BUILD=PASS"
echo "PACKAGE=$tarball"
echo "SHA256=$outer_sha"
echo "PACKAGE_VERSION=$package_version"
