#!/bin/bash
set -euo pipefail
release_root="${1:-}"
if [[ -z "$release_root" || ! -d "$release_root" ]]; then echo "用法：$0 <release-root>" >&2; exit 2; fi
archive="$(find "$release_root" -maxdepth 1 -type f -name 'PicotooPet-MacCore-*.tar.gz' -print | sort | tail -n 1)"
[[ -n "$archive" ]] || { echo "未找到 Mac Core Slice D tar.gz。" >&2; exit 1; }
sha_file="$archive.sha256.txt"
[[ -f "$sha_file" ]] || { echo "缺少外层 SHA-256 文件。" >&2; exit 1; }
expected_sha="$(awk 'NR == 1 {print tolower($1)}' "$sha_file")"
actual_sha="$(shasum -a 256 "$archive" | awk '{print tolower($1)}')"
[[ "$expected_sha" == "$actual_sha" ]] || { echo "外层 SHA-256 不一致。" >&2; exit 1; }

temp_root="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-core-package-test.XXXXXX")"
trap 'rm -rf "$temp_root"' EXIT
python3 - "$archive" <<'PY'
import sys, tarfile
from pathlib import PurePosixPath
with tarfile.open(sys.argv[1], "r:gz") as bundle:
    members = bundle.getmembers()
    if not members:
        raise SystemExit("archive is empty")
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
            raise SystemExit(f"unsafe archive member: {member.name}")
PY

tar -xzf "$archive" -C "$temp_root"
[[ "$(find "$temp_root" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')" == "1" ]] || { echo "归档根目录数量错误。" >&2; exit 1; }
package_root="$(find "$temp_root" -mindepth 1 -maxdepth 1 -type d -print | head -n 1)"
source "$package_root/lib.sh"
verify_manifest_files "$package_root"
[[ "$(read_manifest "$package_root" architecture)" == "$(uname -m)" ]] || exit 1
[[ "$(read_manifest "$package_root" runtime_version)" == "2.3.0-slice-d-core" ]] || exit 1
[[ "$(read_manifest "$package_root" worker_runtime_included)" == "False" ]] || exit 1
[[ "$(read_manifest "$package_root" diagnostic_snapshot_api_included)" == "True" ]] || exit 1
[[ "$(read_manifest "$package_root" source_build_on_user_mac)" == "False" ]] || exit 1
package_version="$(read_manifest "$package_root" package_version)"
[[ -n "$package_version" ]] || exit 1
wheel_count="$(find "$package_root/payload/wheelhouse" -maxdepth 1 -type f -name "picotoopet_core-${package_version//-/_}-*.whl" | wc -l | tr -d ' ')"
[[ "$wheel_count" == "1" ]] || { echo "项目 wheel 与 package_version 不一致。" >&2; exit 1; }
for script in INSTALL_MAC_CORE_SLICE_B.command VERIFY_MAC_CORE_SLICE_B.command ROLLBACK_MAC_CORE_SLICE_B.command lib.sh; do bash -n "$package_root/$script"; done
! grep -Fq 'picotoopet-core==2.3.0.dev' "$package_root/INSTALL_MAC_CORE_SLICE_B.command"
grep -Fq '"picotoopet-core==$package_version"' "$package_root/INSTALL_MAC_CORE_SLICE_B.command"
echo "PHASE23_MAC_SLICE_D_CORE_PACKAGE_TEST=PASS"
