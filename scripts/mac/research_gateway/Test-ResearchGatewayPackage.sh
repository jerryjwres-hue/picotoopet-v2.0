#!/bin/bash
# 校验安装包哈希、Manifest、隔离安装、运行时版本与卸载行为。
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
for item in manifest["files"]:
    path = root / item["path"]
    assert path.is_file(), item["path"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
PY

install_root="$fixture_root/install-root"
PICOTOOPET_RESEARCH_INSTALL_ROOT="$install_root" \
PICOTOOPET_RESEARCH_SKIP_EXTERNAL_INSTALL=1 \
  bash "$package_root/INSTALL_RESEARCH_GATEWAY.command" \
  > "$evidence_dir/install.txt"

test -x "$install_root/bin/picotoopet-research-gateway"
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
PY

PICOTOOPET_RESEARCH_INSTALL_ROOT="$install_root" \
  bash "$package_root/UNINSTALL_RESEARCH_GATEWAY.command" \
  > "$evidence_dir/uninstall.txt"
test ! -e "$install_root"

echo "RESEARCH_GATEWAY_PACKAGE_FIXTURE=PASS"
