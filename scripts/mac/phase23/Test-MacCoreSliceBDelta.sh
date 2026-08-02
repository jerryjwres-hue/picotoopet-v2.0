#!/bin/bash
# 在原生 macOS 上验证 Mac Core Slice B 增量包结构、哈希与脚本语法。
set -euo pipefail

release_root="${1:-}"
if [[ -z "$release_root" || ! -d "$release_root" ]]; then
  echo "用法：$0 <release-root>" >&2
  exit 2
fi

archive="$(find "$release_root" -maxdepth 1 -type f \
  -name 'PicotooPet-MacCore-*.tar.gz' -print | sort | tail -n 1)"
if [[ -z "$archive" ]]; then
  echo "未找到 Mac Core Slice B tar.gz。" >&2
  exit 1
fi
sha_file="$archive.sha256.txt"
if [[ ! -f "$sha_file" ]]; then
  echo "缺少外层 SHA-256 文件。" >&2
  exit 1
fi
expected_sha="$(awk 'NR == 1 {print tolower($1)}' "$sha_file")"
actual_sha="$(shasum -a 256 "$archive" | awk '{print tolower($1)}')"
if [[ "$expected_sha" != "$actual_sha" ]]; then
  echo "外层 tar.gz SHA-256 不一致。" >&2
  exit 1
fi

temp_root="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-mac-package-test.XXXXXX")"
cleanup() {
  rm -rf "$temp_root"
}
trap cleanup EXIT

python3 - "$archive" <<'PY'
import sys
import tarfile
from pathlib import PurePosixPath

archive = sys.argv[1]
with tarfile.open(archive, "r:gz") as bundle:
    members = bundle.getmembers()
    if not members:
        raise SystemExit("archive is empty")
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"unsafe archive path: {member.name}")
        if member.issym() or member.islnk():
            raise SystemExit(f"archive links are forbidden: {member.name}")
PY

tar -xzf "$archive" -C "$temp_root"
root_count="$(find "$temp_root" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')"
if [[ "$root_count" != "1" ]]; then
  echo "归档必须只包含一个根目录。" >&2
  exit 1
fi
package_root="$(find "$temp_root" -mindepth 1 -maxdepth 1 -type d -print | head -n 1)"

# shellcheck source=/dev/null
source "$package_root/lib.sh"
verify_manifest_files "$package_root"

manifest_arch="$(read_manifest "$package_root" architecture)"
if [[ "$manifest_arch" != "$(uname -m)" ]]; then
  echo "清单架构与 Runner 不一致：$manifest_arch" >&2
  exit 1
fi
if [[ "$(read_manifest "$package_root" worker_runtime_included)" != "False" ]]; then
  echo "增量包不得包含 Worker runtime。" >&2
  exit 1
fi

wheelhouse="$package_root/payload/wheelhouse"
if [[ ! -d "$wheelhouse" ]]; then
  echo "wheelhouse 缺失。" >&2
  exit 1
fi
if ! find "$wheelhouse" -maxdepth 1 -type f -name '*.whl' | grep -q .; then
  echo "wheelhouse 为空。" >&2
  exit 1
fi
if find "$wheelhouse" -type f ! -name '*.whl' | grep -q .; then
  echo "wheelhouse 含非 wheel 文件。" >&2
  exit 1
fi

for script in \
  INSTALL_MAC_CORE_SLICE_B.command \
  VERIFY_MAC_CORE_SLICE_B.command \
  ROLLBACK_MAC_CORE_SLICE_B.command \
  lib.sh; do
  bash -n "$package_root/$script"
done

echo "PHASE23_MAC_DELTA_PACKAGE_TEST=PASS"
echo "PACKAGE=$archive"
