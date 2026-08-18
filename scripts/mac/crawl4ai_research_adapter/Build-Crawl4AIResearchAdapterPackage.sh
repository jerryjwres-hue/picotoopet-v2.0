#!/bin/bash
# 构建独立 PicotooPet Crawl4AI Research Adapter Mac arm64 包、manifest 与 SHA-256。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
output_root="$repo_root/artifacts/crawl4ai-research-adapter"

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

architecture="$(uname -m)"
if [[ "$architecture" != "arm64" ]]; then
  echo "Crawl4AI Research Adapter 正式包只允许在 Mac arm64 构建；当前为 $architecture。" >&2
  exit 1
fi

adapter_version="$(tr -d '\r\n' < "$repo_root/research_gateway/CRAWL4AI_ADAPTER_VERSION")"
gateway_version="$(tr -d '\r\n' < "$repo_root/research_gateway/VERSION")"
if [[ "$gateway_version" != "2.3.27.1" ]]; then
  echo "Research Gateway 基线版本不匹配：$gateway_version" >&2
  exit 1
fi
if [[ "$adapter_version" != "2.3.27.1-crawl4ai.4" ]]; then
  echo "Crawl4AI adapter 版本不匹配：$adapter_version" >&2
  exit 1
fi

commit="$(git -C "$repo_root" rev-parse HEAD 2>/dev/null || printf 'unknown')"
package_name="PicotooPet-Crawl4AI-Research-Adapter-Mac-arm64"
staging_parent="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-crawl4ai-build.XXXXXX")"
package_root="$staging_parent/$package_name"
cleanup() {
  rm -rf "$staging_parent"
}
trap cleanup EXIT

mkdir -p "$package_root/payload" "$output_root"
for file in \
  INSTALL_CRAWL4AI_RESEARCH_ADAPTER.command \
  VERIFY_CRAWL4AI_RESEARCH_ADAPTER.command \
  ROLLBACK_CRAWL4AI_RESEARCH_ADAPTER.command \
  README_INSTALL_CN.txt; do
  cp "$repo_root/deploy/macos/crawl4ai_research_adapter/$file" "$package_root/$file"
done
for file in gateway.py crawler_adapter.py crawl4ai_runner.py VERSION CRAWL4AI_ADAPTER_VERSION; do
  cp "$repo_root/research_gateway/$file" "$package_root/payload/$file"
done
chmod 755 "$package_root"/*.command

python3 - "$package_root" "$adapter_version" "$gateway_version" "$commit" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
files = []
for path in sorted(item for item in root.rglob("*") if item.is_file()):
    relative = path.relative_to(root).as_posix()
    if relative == "manifest.json":
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
    "release_type": "crawl4ai-research-adapter",
    "target": "macos",
    "architecture": "arm64",
    "package_name": "PicotooPet-Crawl4AI-Research-Adapter-Mac-arm64",
    "adapter_version": sys.argv[2],
    "research_gateway_version": sys.argv[3],
    "commit": sys.argv[4],
    "fresh_crawl4ai_pin": "0.9.2",
    "compatible_existing_crawl4ai": "0.9.x",
    "crawler_provider_allowlist": ["crawl4ai", "scrapling"],
    "routing": ["crawl4ai", "scrapling_fallback_once"],
    "limits": {
        "max_pages": 3,
        "max_depth": 0,
        "timeout_seconds": 30,
        "max_content_bytes": 262144,
        "redirect_limit": 5,
        "concurrency": 2,
        "retry_limit": 1,
    },
    "gateway_private_python_bootstrap": True,
    "read_only": True,
    "account_write_capabilities": False,
    "captcha_bypass": False,
    "chrome_profile_access": False,
    "chrome_cookies_included": False,
    "scrapling_bundled": False,
    "scrapling_upgraded": False,
    "windows_payload_included": False,
    "install_log_generated": True,
    "rollback_preserves_gateway_worker_scrapling": True,
    "files": files,
}
(root / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

rm -f "$output_root/$package_name.tar.gz" "$output_root/$package_name.tar.gz.sha256.txt"
tarball="$output_root/$package_name.tar.gz"
tar -czf "$tarball" -C "$staging_parent" "$package_name"
sha256="$(shasum -a 256 "$tarball" | awk '{print tolower($1)}')"
printf '%s  %s\n' "$sha256" "$(basename "$tarball")" > "$tarball.sha256.txt"

python3 - "$output_root/crawl4ai-research-adapter-build-report.json" "$adapter_version" "$commit" "$tarball" "$sha256" <<'PY'
import json
import sys
from pathlib import Path

report = {
    "status": "pass",
    "target": "macos-arm64",
    "adapter_version": sys.argv[2],
    "commit": sys.argv[3],
    "package": str(Path(sys.argv[4]).resolve()),
    "sha256": sys.argv[5],
    "gateway_private_python_bootstrap": True,
    "read_only": True,
    "windows_payload_included": False,
    "scrapling_bundled": False,
}
Path(sys.argv[1]).write_text(
    json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

echo "CRAWL4AI_RESEARCH_ADAPTER_BUILD=PASS"
echo "PACKAGE=$tarball"
echo "SHA256=$sha256"
