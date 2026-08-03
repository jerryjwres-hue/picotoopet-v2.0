#!/bin/bash
# 在原生 M4/arm64 macOS 上验证 Slice D Worker 包结构、哈希、清单与脚本边界。
set -euo pipefail

release_root="${1:-}"
if [[ -z "$release_root" || ! -d "$release_root" ]]; then
  echo "用法：$0 <release-root>" >&2
  exit 2
fi
if [[ "$(uname -m)" != "arm64" ]]; then
  echo "Slice D Worker 包级复验必须在原生 arm64 Runner 执行。" >&2
  exit 1
fi

archive="$(find "$release_root" -maxdepth 1 -type f \
  -name 'PicotooPet-MacWorker-*.tar.gz' -print | sort | tail -n 1)"
if [[ -z "$archive" ]]; then
  echo "未找到 Mac Worker Slice D tar.gz。" >&2
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

temp_root="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-worker-package-test.XXXXXX")"
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

if [[ "$(read_manifest "$package_root" architecture)" != "arm64" ]]; then
  echo "清单架构不是 arm64。" >&2
  exit 1
fi
if [[ "$(read_manifest "$package_root" runtime_version)" != "2.3.0-slice-d-worker" ]]; then
  echo "清单 runtime_version 不正确。" >&2
  exit 1
fi
worker_included="$(read_manifest "$package_root" worker_runtime_included)"
if [[ "$worker_included" != "True" && "$worker_included" != "true" ]]; then
  echo "清单未声明 Worker Runtime。" >&2
  exit 1
fi
if [[ "$(read_manifest "$package_root" worker_supported_task_types)" != '["system.diagnostic_snapshot", "system.noop"]' ]]; then
  echo "清单 Worker 类型不符合冻结合同。" >&2
  exit 1
fi
if [[ "$(read_manifest "$package_root" diagnostic_hard_timeout_seconds)" != "30" ]]; then
  echo "清单诊断硬超时不是 30 秒。" >&2
  exit 1
fi
if [[ "$(read_manifest "$package_root" diagnostic_termination_grace_seconds)" != "5" ]]; then
  echo "清单进程清理宽限不是 5 秒。" >&2
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

for script in \
  INSTALL_MAC_WORKER_SLICE_C.command \
  VERIFY_MAC_WORKER_SLICE_C.command \
  ROLLBACK_MAC_WORKER_SLICE_C.command \
  lib.sh \
  worker-lib.sh; do
  bash -n "$package_root/$script"
done

installer="$package_root/INSTALL_MAC_WORKER_SLICE_C.command"
if grep -Fq 'picotoopet-core==2.3.0.dev' "$installer"; then
  echo "安装器仍包含硬编码项目版本。" >&2
  exit 1
fi
if ! grep -Fq '"picotoopet-core==$package_version"' "$installer"; then
  echo "安装器没有使用 Manifest package_version。" >&2
  exit 1
fi
if ! grep -Fq 'python_version="$("$current_python" --version 2>&1)"' "$installer"; then
  echo "安装器缺少含空格路径引用回归修复。" >&2
  exit 1
fi

combined="$(cat \
  "$package_root/INSTALL_MAC_WORKER_SLICE_C.command" \
  "$package_root/VERIFY_MAC_WORKER_SLICE_C.command" \
  "$package_root/ROLLBACK_MAC_WORKER_SLICE_C.command" \
  "$package_root/worker-lib.sh")"
for forbidden in \
  "sudo " \
  "/Library/LaunchDaemons" \
  "security delete-generic-password" \
  "pfctl" \
  "socketfilterfw" \
  "dotnet build" \
  "pip wheel"; do
  if grep -Fq "$forbidden" <<< "$combined"; then
    echo "用户安装脚本包含禁止操作：$forbidden" >&2
    exit 1
  fi
done

echo "PHASE23_MAC_WORKER_PACKAGE_TEST=PASS"
echo "PHASE23_MAC_WORKER_SLICE_D_PACKAGE_TEST=PASS"
echo "PACKAGE=$archive"
