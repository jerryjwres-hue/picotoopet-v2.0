#!/bin/bash
# 验证 Mac 一体化包的外层哈希、Manifest、双组件结构和不修改共享外部工具链的边界。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
output_root="${1:-$repo_root/artifacts/research-integration}"
package_name="PicotooPet-Research-2.3.27.1-Mac-arm64"
tarball="$output_root/$package_name.tar.gz"
sha_file="$tarball.sha256.txt"

test -f "$tarball"
test -f "$sha_file"
(
  cd "$output_root"
  shasum -a 256 -c "$(basename "$sha_file")"
)

# CI 使用临时目录展开归档；Runner 生命周期结束后由系统回收。
fixture_root="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-research-integrated-test.XXXXXX")"
cleanup() {
  rm -rf "$fixture_root"
}
trap cleanup EXIT

tar -xzf "$tarball" -C "$fixture_root"
package_root="$fixture_root/$package_name"

python3 - "$package_root" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
manifest = json.loads((root / "release-manifest.json").read_text(encoding="utf-8"))
assert manifest["release_version"] == "2.3.27.1"
assert manifest["product_version"] == "2.3.26.1"
assert manifest["architecture"] == "arm64"
assert manifest["gateway_included"] is True
assert manifest["core_worker_update_included"] is True
assert manifest["read_only"] is True
assert manifest["windows_shell_access"] is False
assert manifest["external_research_tools_bundled"] is False
assert manifest["browser_cookies_included"] is False
assert manifest["xiaoyuzhou_enabled"] is False
assert manifest["direct_windows_task_types"] == ["research.search"]

required = {
    "INSTALL_PICOTOOPET_RESEARCH_2_3_27_1.command",
    "VERIFY_PICOTOOPET_RESEARCH_2_3_27_1.command",
    "ROLLBACK_PICOTOOPET_RESEARCH_2_3_27_1.command",
    "README_INSTALL_CN.txt",
    "gateway/INSTALL_RESEARCH_GATEWAY.command",
    "gateway/VERIFY_RESEARCH_GATEWAY.command",
    "gateway/payload/gateway.py",
    "gateway/payload/research_gateway/__init__.py",
    "gateway/payload/research_gateway/crawler_adapter.py",
    "gateway/payload/crawl4ai_runner.py",
    "gateway/payload/CRAWL4AI_ADAPTER_VERSION",
    "worker/INSTALL_MAC_WORKER_SLICE_C.command",
    "worker/VERIFY_MAC_WORKER_SLICE_C.command",
    "worker/ROLLBACK_MAC_WORKER_SLICE_C.command",
    "worker/release-manifest.json",
}
actual = {item["path"] for item in manifest["files"]}
missing = sorted(required - actual)
assert not missing, missing

for item in manifest["files"]:
    path = root / item["path"]
    assert path.is_file(), item["path"]
    content = path.read_bytes()
    assert len(content) == item["size_bytes"], item["path"]
    assert hashlib.sha256(content).hexdigest() == item["sha256"], item["path"]
PY

# 共享工具安装边界：Gateway 可以安装 PicotooPet 自有 Crawl4AI 私有 venv，
# 但不能安装/升级 Agent Reach、OpenCLI、Scrapling、Thunderbit 或其它共享工具链。
installer="$package_root/gateway/INSTALL_RESEARCH_GATEWAY.command"
for forbidden in \
  "brew install" \
  "npm install" \
  "pipx install" \
  "pipx upgrade" \
  "agent-reach install" \
  "opencli install" \
  "scrapling-mcp-local install"; do
  if grep -Fq "$forbidden" "$installer"; then
    echo "组合包违反 shared-tool bind-only 安装边界：$forbidden" >&2
    exit 1
  fi
done
grep -Fq 'crawl4ai==0.9.2' "$installer"
grep -Fq 'PLAYWRIGHT_BROWSERS_PATH' "$installer"
grep -Fq '不会安装、升级或覆盖' "$installer"

# Shell 静态验收：顶层与两个内层安装生命周期脚本均必须通过 Bash 语法检查。
for command_file in \
  "$package_root"/*.command \
  "$package_root/gateway"/*.command \
  "$package_root/worker"/*.command; do
  bash -n "$command_file"
done

echo "PICOTOOPET_RESEARCH_INTEGRATED_PACKAGE=PASS"
