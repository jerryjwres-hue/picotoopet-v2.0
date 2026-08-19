#!/bin/bash
# 在原生 macOS 上验证 Mac Core Slice D 归档、清单、wheel 与脚本边界。
set -euo pipefail

release_root="${1:-}"
if [[ -z "$release_root" || ! -d "$release_root" ]]; then
  echo "用法：$0 <release-root>" >&2
  exit 2
fi

archive="$(find "$release_root" -maxdepth 1 -type f \
  -name 'PicotooPet-MacCore-*.tar.gz' -print | sort | tail -n 1)"
if [[ -z "$archive" ]]; then
  echo "未找到 Mac Core Slice D tar.gz。" >&2
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
  echo "外层 SHA-256 不一致。" >&2
  exit 1
fi

temp_root="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-core-package-test.XXXXXX")"
cleanup() {
  rm -rf "$temp_root"
}
trap cleanup EXIT

python3 - "$archive" <<'PY'
import sys
import tarfile
from pathlib import PurePosixPath

with tarfile.open(sys.argv[1], "r:gz") as bundle:
    members = bundle.getmembers()
    if not members:
        raise SystemExit("archive is empty")
    roots: set[str] = set()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"unsafe archive path: {member.name}")
        if member.issym() or member.islnk():
            raise SystemExit(f"archive links are forbidden: {member.name}")
        if path.parts:
            roots.add(path.parts[0])
    if len(roots) != 1:
        raise SystemExit(f"archive must contain one root: {sorted(roots)!r}")
PY

tar -xzf "$archive" -C "$temp_root"
package_root="$(find "$temp_root" -mindepth 1 -maxdepth 1 -type d -print | head -n 1)"
if [[ -z "$package_root" ]]; then
  echo "归档根目录缺失。" >&2
  exit 1
fi

# shellcheck source=/dev/null
source "$package_root/lib.sh"
verify_manifest_files "$package_root"

product_version="$(phase23_product_version "$package_root")"
if [[ "$(read_manifest "$package_root" product_version)" != "$product_version" ]]; then
  echo "清单 product_version 与包内唯一版本文件不一致。" >&2
  exit 1
fi
if [[ "$(basename "$archive")" != *"-$product_version-"* ]]; then
  echo "包名未包含产品版本：$product_version" >&2
  exit 1
fi
if [[ "$(read_manifest "$package_root" architecture)" != "$(uname -m)" ]]; then
  echo "清单架构与 Runner 不一致。" >&2
  exit 1
fi
if [[ "$(read_manifest "$package_root" runtime_version)" != "2.3.0-slice-d-core" ]]; then
  echo "清单 runtime_version 不正确。" >&2
  exit 1
fi
if [[ "$(read_manifest "$package_root" worker_runtime_included)" != "False" ]]; then
  echo "Core 包不得捆绑 Worker Runtime。" >&2
  exit 1
fi
if [[ "$(read_manifest "$package_root" diagnostic_snapshot_api_included)" != "True" ]]; then
  echo "清单未声明 Slice D 诊断 API。" >&2
  exit 1
fi
if [[ "$(read_manifest "$package_root" source_build_on_user_mac)" != "False" ]]; then
  echo "清单错误地要求用户端构建。" >&2
  exit 1
fi

package_version="$(read_manifest "$package_root" package_version)"
if [[ -z "$package_version" || ! "$package_version" =~ ^[A-Za-z0-9._+-]+$ ]]; then
  echo "清单 package_version 无效。" >&2
  exit 1
fi
wheelhouse="$package_root/payload/wheelhouse"
if [[ ! -d "$wheelhouse" ]]; then
  echo "wheelhouse 缺失。" >&2
  exit 1
fi
if find "$wheelhouse" -type f ! -name '*.whl' | grep -q .; then
  echo "wheelhouse 含非 wheel 文件。" >&2
  exit 1
fi
wheel_count="$(find "$wheelhouse" -maxdepth 1 -type f \
  -name "picotoopet_core-${package_version//-/_}-*.whl" | wc -l | tr -d ' ')"
if [[ "$wheel_count" != "1" ]]; then
  echo "项目 wheel 与 package_version 不一致。" >&2
  exit 1
fi
project_wheel="$(find "$wheelhouse" -maxdepth 1 -type f \
  -name "picotoopet_core-${package_version//-/_}-*.whl" -print | head -n 1)"
python3 - "$project_wheel" <<'PY'
import sys
import zipfile

required = {
    "picotoopet_core/api/routes/autonomous_goals.py",
    "picotoopet_core/api/routes/autonomous_intake.py",
    "picotoopet_core/autonomous/human_pipeline.py",
    "picotoopet_core/autonomous/intake_autopilot.py",
    "picotoopet_core/autonomous/legacy_import.py",
    "picotoopet_core/autonomous/browser_broker.py",
    "picotoopet_core/autonomous/goal_handoff_access.py",
    "picotoopet_core/autonomous/prompts/web_gpt_master_v1.txt",
}
with zipfile.ZipFile(sys.argv[1], "r") as wheel:
    names = set(wheel.namelist())
missing = sorted(required - names)
if missing:
    raise SystemExit(f"Goal Center Mac Core wheel content missing: {missing!r}")
PY
echo "PHASE23_MAC_CORE_GOAL_CENTER_CONTENT=PASS"

for script in \
  INSTALL_MAC_CORE_SLICE_B.command \
  VERIFY_MAC_CORE_SLICE_B.command \
  ROLLBACK_MAC_CORE_SLICE_B.command \
  lib.sh; do
  bash -n "$package_root/$script"
done

installer="$package_root/INSTALL_MAC_CORE_SLICE_B.command"
if grep -Fq 'picotoopet-core==2.3.0.dev' "$installer"; then
  echo "安装器仍包含硬编码项目版本。" >&2
  exit 1
fi
if ! grep -Fq '"picotoopet-core==$package_version"' "$installer"; then
  echo "安装器没有使用 Manifest package_version。" >&2
  exit 1
fi
if ! grep -Fq 'verify_api_contract "$candidate_url" "$api_token" "$product_version"' "$installer"; then
  echo "安装器没有校验候选 Core 的精确产品版本。" >&2
  exit 1
fi

combined="$(cat \
  "$package_root/INSTALL_MAC_CORE_SLICE_B.command" \
  "$package_root/VERIFY_MAC_CORE_SLICE_B.command" \
  "$package_root/ROLLBACK_MAC_CORE_SLICE_B.command" \
  "$package_root/lib.sh")"
for forbidden in \
  "sudo " \
  "/Library/LaunchDaemons" \
  "security delete-generic-password" \
  "pfctl" \
  "socketfilterfw" \
  "pip wheel" \
  "dotnet build"; do
  if grep -Fq "$forbidden" <<< "$combined"; then
    echo "用户安装脚本包含禁止操作：$forbidden" >&2
    exit 1
  fi
done

echo "PHASE23_MAC_DELTA_PACKAGE_TEST=PASS"
echo "PHASE23_MAC_SLICE_D_CORE_PACKAGE_TEST=PASS"
echo "PRODUCT_VERSION=$product_version"
echo "PACKAGE=$archive"
