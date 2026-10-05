#!/bin/bash
# 校验安装包哈希、Manifest、隔离安装、Crawler 接线、运行时版本与卸载行为。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
output_root="${1:-$repo_root/artifacts/research-gateway}"
architecture="$(uname -m)"
version="$(tr -d '\r\n' < "$repo_root/research_gateway/VERSION")"
tarball="$output_root/PicotooPet-ResearchGateway-$version-$architecture.tar.gz"
sha_file="$tarball.sha256.txt"
evidence_dir="$output_root/fixture-evidence"

mkdir -p "$evidence_dir"
test -f "$tarball"
test -f "$sha_file"
(
  cd "$output_root"
  shasum -a 256 -c "$(basename "$sha_file")"
)

fixture_root="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-research-fixture.XXXXXX")"
cleanup() {
  rm -rf "$fixture_root"
}
trap cleanup EXIT

tar -xzf "$tarball" -C "$fixture_root"
package_root="$fixture_root/PicotooPet-ResearchGateway-$version-$architecture"

# 当前 Gateway 已依赖 crawler_adapter；正式包必须携带完整 package-owned 接线，不能只复制 gateway.py。
test -f "$package_root/payload/research_gateway/__init__.py"
test -f "$package_root/payload/research_gateway/crawler_adapter.py"
test -f "$package_root/payload/crawl4ai_runner.py"
test -f "$package_root/payload/CRAWL4AI_ADAPTER_VERSION"

python3 - "$package_root/release-manifest.json" "$version" "$architecture" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
root = manifest_path.parent
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
assert manifest["version"] == sys.argv[2]
assert manifest["architecture"] == sys.argv[3]
assert manifest["process_isolated_from_mac_core"] is True
assert manifest["read_only"] is True
assert manifest["xiaoyuzhou_enabled"] is False
assert manifest["browser_cookies_included"] is False
assert manifest["external_tools_bundled"] is False
for item in manifest["files"]:
    path = root / item["path"]
    assert path.is_file(), item["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
PY

# Fixture 安装：使用隔离根目录；跳过真实 Crawl4AI 下载，只验证接线文件与 Gateway 可启动。
install_root="$fixture_root/install-root"
PICOTOOPET_RESEARCH_INSTALL_ROOT="$install_root" \
PICOTOOPET_SKIP_CRAWL4AI_INSTALL=1 \
  bash "$package_root/INSTALL_RESEARCH_GATEWAY.command" \
  > "$evidence_dir/install.txt"

test -x "$install_root/bin/picotoopet-research-gateway"
test -f "$install_root/runtime/research_gateway/__init__.py"
test -f "$install_root/runtime/research_gateway/crawler_adapter.py"
"$install_root/bin/picotoopet-research-gateway" --health \
  > "$evidence_dir/health.txt"
python3 - "$evidence_dir/health.txt" <<'PY'
import json
import sys
from pathlib import Path

health = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert health["version"] == "2.3.27.1"
assert health["read_only"] is True
assert health["xiaoyuzhou_enabled"] is False
assert "crawl4ai" in health
PY

PICOTOOPET_RESEARCH_INSTALL_ROOT="$install_root" \
  bash "$package_root/UNINSTALL_RESEARCH_GATEWAY.command" \
  > "$evidence_dir/uninstall.txt"
test ! -e "$install_root"

echo "RESEARCH_GATEWAY_PACKAGE_FIXTURE=PASS"
