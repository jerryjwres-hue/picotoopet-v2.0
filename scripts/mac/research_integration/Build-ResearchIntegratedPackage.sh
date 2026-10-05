#!/bin/bash
# 组合经过验证的 Research Gateway 与预构建 Core/Worker，生成一个用户可直接安装的 Mac 包。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
output_root="$repo_root/artifacts/research-integration"
release_version="2.3.27.1"
expected_product_version="2.3.27.1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-root)
      output_root="$2"
      shift 2
      ;;
    *)
      echo "未知参数：$1" >&2
      exit 2
      ;;
  esac
done

product_version="$(tr -d '\r\n' < "$repo_root/src/picotoopet_core/product-version.txt")"
if [[ "$product_version" != "$expected_product_version" ]]; then
  echo "Research ${release_version} 必须叠加在产品基线 ${expected_product_version}：${product_version}" >&2
  exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "Mac 一体化 Research 包仅支持 Apple Silicon arm64。" >&2
  exit 1
fi

# build_commit 记录 Runner 实际 checkout 的树；source_commit 记录触发 Release 的源码提交。
build_commit="$(git -C "$repo_root" rev-parse HEAD)"
source_commit="${PICOTOOPET_RELEASE_SOURCE_COMMIT:-$build_commit}"
if [[ ! "$source_commit" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "Release source commit 非法：$source_commit" >&2
  exit 1
fi
source_commit="$(printf '%s' "$source_commit" | tr '[:upper:]' '[:lower:]')"
short_commit="${source_commit:0:12}"
work_root="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-research-integrated.XXXXXX")"
cleanup() {
  rm -rf "$work_root"
}
trap cleanup EXIT

component_root="$work_root/components"
gateway_output="$component_root/gateway-output"
worker_output="$component_root/worker-output"
mkdir -p "$gateway_output" "$worker_output" "$output_root"

# 组件构建：复用各自正式构建器，避免组合脚本复制或重新实现安全逻辑。
bash "$repo_root/scripts/mac/research_gateway/Build-ResearchGatewayPackage.sh" \
  --output-root "$gateway_output"
bash "$repo_root/scripts/mac/phase23-worker/Build-MacWorkerSliceC.sh" \
  --output-root "$worker_output" \
  --version-label "$release_version-research-$short_commit"

gateway_tar="$(find "$gateway_output" -maxdepth 1 -type f -name '*.tar.gz' -print -quit)"
worker_tar="$(find "$worker_output" -maxdepth 1 -type f -name '*.tar.gz' -print -quit)"
if [[ -z "$gateway_tar" || -z "$worker_tar" ]]; then
  echo "组合包构建失败：缺少 Gateway 或 Worker 组件归档。" >&2
  exit 1
fi

gateway_extract="$component_root/gateway-extract"
worker_extract="$component_root/worker-extract"
mkdir -p "$gateway_extract" "$worker_extract"
tar -xzf "$gateway_tar" -C "$gateway_extract"
tar -xzf "$worker_tar" -C "$worker_extract"
gateway_source="$(find "$gateway_extract" -mindepth 1 -maxdepth 1 -type d -print -quit)"
worker_source="$(find "$worker_extract" -mindepth 1 -maxdepth 1 -type d -print -quit)"
if [[ -z "$gateway_source" || -z "$worker_source" ]]; then
  echo "组合包构建失败：组件归档根目录无效。" >&2
  exit 1
fi

package_name="PicotooPet-Research-$release_version-Mac-arm64"
package_root="$work_root/$package_name"
mkdir -p "$package_root/gateway" "$package_root/worker"
cp -R "$gateway_source/." "$package_root/gateway/"
cp -R "$worker_source/." "$package_root/worker/"

for file in \
  INSTALL_PICOTOOPET_RESEARCH_2_3_27_1.command \
  VERIFY_PICOTOOPET_RESEARCH_2_3_27_1.command \
  ROLLBACK_PICOTOOPET_RESEARCH_2_3_27_1.command \
  README_INSTALL_CN.txt; do
  cp "$repo_root/deploy/macos/research_integration/$file" "$package_root/$file"
done
chmod 755 "$package_root"/*.command

# 外层 Manifest 同时记录源码提交、实际构建提交、产品基线与 Research 能力版本，并对全部内嵌文件做哈希。
python3 - "$package_root" "$source_commit" "$build_commit" "$release_version" "$product_version" <<'PY'
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
    "release_type": "picotoopet-research-integrated-update",
    "release_version": sys.argv[4],
    "product_version": sys.argv[5],
    "target": "macos",
    "architecture": "arm64",
    "commit": sys.argv[2],
    "source_commit": sys.argv[2],
    "build_commit": sys.argv[3],
    "gateway_included": True,
    "core_worker_update_included": True,
    "read_only": True,
    "windows_shell_access": False,
    "external_research_tools_bundled": False,
    "browser_cookies_included": False,
    "xiaoyuzhou_enabled": False,
    "direct_windows_task_types": ["research.search"],
    "files": files,
}
(root / "release-manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

rm -f "$output_root/$package_name.tar.gz" "$output_root/$package_name.tar.gz.sha256.txt"
tarball="$output_root/$package_name.tar.gz"
tar -czf "$tarball" -C "$work_root" "$package_name"
sha256="$(shasum -a 256 "$tarball" | awk '{print tolower($1)}')"
printf '%s  %s\n' "$sha256" "$(basename "$tarball")" > "$tarball.sha256.txt"

python3 - "$output_root/research-integrated-build-report.json" "$source_commit" "$build_commit" "$tarball" "$sha256" "$release_version" "$product_version" <<'PY'
import json
import sys
from pathlib import Path

report = {
    "status": "pass",
    "release_version": sys.argv[6],
    "product_version": sys.argv[7],
    "architecture": "arm64",
    "commit": sys.argv[2],
    "source_commit": sys.argv[2],
    "build_commit": sys.argv[3],
    "package": str(Path(sys.argv[4]).resolve()),
    "sha256": sys.argv[5],
    "gateway_included": True,
    "core_worker_update_included": True,
    "external_research_tools_bundled": False,
    "read_only": True,
}
Path(sys.argv[1]).write_text(
    json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

echo "PICOTOOPET_RESEARCH_INTEGRATED_BUILD=PASS"
echo "RELEASE_VERSION=$release_version"
echo "PRODUCT_VERSION=$product_version"
echo "SOURCE_COMMIT=$source_commit"
echo "BUILD_COMMIT=$build_commit"
echo "PACKAGE=$tarball"
echo "SHA256=$sha256"
