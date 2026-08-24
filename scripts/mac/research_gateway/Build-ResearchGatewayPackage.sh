#!/bin/bash
# 构建架构专属 Research Gateway 安装包与 SHA-256 证据。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
output_root="$repo_root/artifacts/research-gateway"

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

version="$(tr -d '\r\n' < "$repo_root/research_gateway/VERSION")"
if [[ "$version" != "2.3.27.1" ]]; then
  echo "Research Gateway 版本必须是 2.3.27.1：$version" >&2
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
mkdir -p "$output_root"
staging_parent="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-research-build.XXXXXX")"
package_name="PicotooPet-ResearchGateway-$version-$architecture"
package_root="$staging_parent/$package_name"
cleanup() {
  rm -rf "$staging_parent"
}
trap cleanup EXIT

# 打包 PicotooPet 自有 Gateway/Crawler 接线与 runner；共享研究工具和浏览器状态仍不进入包。
mkdir -p "$package_root/payload/research_gateway"
for file in INSTALL_RESEARCH_GATEWAY.command VERIFY_RESEARCH_GATEWAY.command UNINSTALL_RESEARCH_GATEWAY.command README_INSTALL_CN.txt; do
  cp "$repo_root/deploy/macos/research_gateway/$file" "$package_root/$file"
done
cp "$repo_root/research_gateway/gateway.py" "$package_root/payload/gateway.py"
cp "$repo_root/research_gateway/VERSION" "$package_root/payload/VERSION"
cp "$repo_root/research_gateway/__init__.py" "$package_root/payload/research_gateway/__init__.py"
cp "$repo_root/research_gateway/crawler_adapter.py" "$package_root/payload/research_gateway/crawler_adapter.py"
cp "$repo_root/research_gateway/crawl4ai_runner.py" "$package_root/payload/crawl4ai_runner.py"
cp "$repo_root/research_gateway/CRAWL4AI_ADAPTER_VERSION" "$package_root/payload/CRAWL4AI_ADAPTER_VERSION"
chmod 755 "$package_root"/*.command

python3 - "$package_root" "$version" "$architecture" "$commit" <<'PY'
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
    "schema_version": "1.1",
    "release_type": "research-gateway-bootstrap",
    "target": "macos",
    "version": sys.argv[2],
    "architecture": sys.argv[3],
    "commit": sys.argv[4],
    "process_isolated_from_mac_core": True,
    "read_only": True,
    "xiaoyuzhou_enabled": False,
    "browser_cookies_included": False,
    "external_tools_bundled": False,
    "package_owned_crawl4ai_seed_included": True,
    "files": files,
}
(root / "release-manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

rm -f "$output_root"/PicotooPet-ResearchGateway-"$version"-"$architecture".tar.gz*
tarball="$output_root/$package_name.tar.gz"
tar -czf "$tarball" -C "$staging_parent" "$package_name"
sha256="$(shasum -a 256 "$tarball" | awk '{print tolower($1)}')"
printf '%s  %s\n' "$sha256" "$(basename "$tarball")" > "$tarball.sha256.txt"

python3 - "$output_root/research-gateway-build-report.json" "$version" "$architecture" "$commit" "$tarball" "$sha256" <<'PY'
import json
import sys
from pathlib import Path

report = {
    "status": "pass",
    "version": sys.argv[2],
    "architecture": sys.argv[3],
    "commit": sys.argv[4],
    "package": str(Path(sys.argv[5]).resolve()),
    "sha256": sys.argv[6],
    "process_isolated_from_mac_core": True,
    "read_only": True,
    "external_tools_bundled": False,
    "package_owned_crawl4ai_seed_included": True,
}
Path(sys.argv[1]).write_text(
    json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

echo "RESEARCH_GATEWAY_BUILD=PASS"
echo "PACKAGE=$tarball"
echo "SHA256=$sha256"
