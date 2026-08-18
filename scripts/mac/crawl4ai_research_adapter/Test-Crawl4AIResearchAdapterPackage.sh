#!/bin/bash
# 验证正式包完整性、脚本语法与 scoped rollback；此脚本不伪装真实 crawler e2e。
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "用法：$0 <artifact-directory>" >&2
  exit 2
fi

artifact_root="$(cd "$1" && pwd)"
package_name="PicotooPet-Crawl4AI-Research-Adapter-Mac-arm64"
tarball="$artifact_root/$package_name.tar.gz"
sha_file="$tarball.sha256.txt"

if [[ ! -f "$tarball" || ! -f "$sha_file" ]]; then
  echo "缺少正式 tar.gz 或 SHA-256 文件。" >&2
  exit 1
fi
expected_sha="$(awk '{print tolower($1)}' "$sha_file")"
actual_sha="$(shasum -a 256 "$tarball" | awk '{print tolower($1)}')"
if [[ "$expected_sha" != "$actual_sha" ]]; then
  echo "包 SHA-256 不匹配。" >&2
  exit 1
fi

fixture_root="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-crawl4ai-package-test.XXXXXX")"
cleanup() {
  rm -rf "$fixture_root"
}
trap cleanup EXIT

tar -xzf "$tarball" -C "$fixture_root"
package_root="$fixture_root/$package_name"

# manifest 必须逐文件校验，不能只相信外层 tarball SHA。
python3 - "$package_root" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
assert manifest["target"] == "macos"
assert manifest["architecture"] == "arm64"
assert manifest["adapter_version"] == "2.3.27.1-crawl4ai.4"
assert manifest["fresh_crawl4ai_pin"] == "0.9.2"
assert manifest["crawler_provider_allowlist"] == ["crawl4ai", "scrapling"]
assert manifest["gateway_private_python_bootstrap"] is True
assert manifest["windows_payload_included"] is False
assert manifest["scrapling_bundled"] is False
assert manifest["captcha_bypass"] is False
assert manifest["chrome_profile_access"] is False
for entry in manifest["files"]:
    path = root / entry["path"]
    if not path.is_file():
        raise SystemExit(f"missing manifest file: {entry['path']}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry["sha256"]:
        raise SystemExit(f"manifest digest mismatch: {entry['path']}")
PY

for command in "$package_root"/*.command; do
  bash -n "$command"
done

# Scoped rollback fixture：只模拟安装后的文件所有权，不冒充 Crawl4AI 网络抓取成功。
fixture_home="$fixture_root/home"
gateway_root="$fixture_home/Library/Application Support/PicotooPet/ResearchGateway"
gateway_runtime="$gateway_root/runtime"
gateway_module_dir="$gateway_runtime/research_gateway"
adapter_root="$fixture_home/.local/share/picotoopet/research/crawl4ai"
worker_root="$fixture_home/Library/Application Support/PicotooPetV2"
scrapling_marker="$fixture_home/.local/bin/scrapling-mcp-local"
mkdir -p \
  "$gateway_runtime" \
  "$gateway_module_dir" \
  "$gateway_root/bin" \
  "$adapter_root/state" \
  "$adapter_root/runtime" \
  "$adapter_root/bin" \
  "$adapter_root/data" \
  "$worker_root" \
  "$(dirname "$scrapling_marker")"

printf 'ORIGINAL_GATEWAY\n' > "$adapter_root/state/gateway.py.pre-crawl4ai"
printf 'PATCHED_GATEWAY\n' > "$gateway_runtime/gateway.py"
cp "$package_root/payload/crawler_adapter.py" "$gateway_module_dir/crawler_adapter.py"
printf '2.3.27.1\n' > "$gateway_runtime/VERSION"
printf 'worker-preserve\n' > "$worker_root/fixture-worker-marker.txt"
printf '#!/bin/bash\nexit 0\n' > "$scrapling_marker"
chmod 755 "$scrapling_marker"
# 模拟用户实机：pre-Crawl4AI Gateway 本来就可能因旧系统 Python 不健康；这不能阻断恢复原状。
printf '#!/bin/bash\nexit 42\n' > "$gateway_root/bin/picotoopet-research-gateway"
chmod 755 "$gateway_root/bin/picotoopet-research-gateway"
printf '#!/bin/bash\nexit 0\n' > "$adapter_root/bin/picotoopet-crawl4ai-provider"
chmod 755 "$adapter_root/bin/picotoopet-crawl4ai-provider"
printf 'runtime\n' > "$adapter_root/runtime/crawl4ai_runner.py"
cat > "$adapter_root/state/install-state.json" <<'JSON'
{
  "schema_version": "1.0",
  "created_venv": false
}
JSON

HOME="$fixture_home" \
PICOTOOPET_CRAWL4AI_ROOT="$adapter_root" \
PICOTOOPET_RESEARCH_INSTALL_ROOT="$gateway_root" \
  "$package_root/ROLLBACK_CRAWL4AI_RESEARCH_ADAPTER.command"

grep -q '^ORIGINAL_GATEWAY$' "$gateway_runtime/gateway.py"
test ! -e "$gateway_module_dir/crawler_adapter.py"
test ! -e "$adapter_root/bin/picotoopet-crawl4ai-provider"
test -f "$worker_root/fixture-worker-marker.txt"
test -x "$scrapling_marker"
test -f "$gateway_runtime/VERSION"
python3 - "$adapter_root/state/install-state.json" <<'PY'
import json
import sys
from pathlib import Path

state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert state["adapter_version"] == "2.3.27.1-crawl4ai.4"
assert state["status"] == "rolled_back"
assert state["gateway_private_python_bootstrap"] is False
PY

echo "CRAWL4AI_RESEARCH_ADAPTER_PACKAGE_TEST=PASS"
echo "SHA256=$actual_sha"
