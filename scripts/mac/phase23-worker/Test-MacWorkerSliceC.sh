#!/bin/bash
set -euo pipefail
root="${1:-}"; [[ -d "$root" ]] || { echo "用法：$0 <release-root>" >&2; exit 2; }
[[ "$(uname -m)" == arm64 ]] || exit 1
archive="$(find "$root" -maxdepth 1 -type f -name 'PicotooPet-MacWorker-*.tar.gz' -print | sort | tail -n1)"; [[ -n "$archive" ]] || exit 1
expected="$(awk 'NR==1{print tolower($1)}' "$archive.sha256.txt")"; actual="$(shasum -a 256 "$archive"|awk '{print tolower($1)}')"; [[ "$expected" == "$actual" ]] || exit 1
tmp="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-worker-package.XXXXXX")"; trap 'rm -rf "$tmp"' EXIT
python3 - "$archive" <<'PY'
import sys,tarfile
from pathlib import PurePosixPath
with tarfile.open(sys.argv[1],'r:gz') as b:
 for m in b.getmembers():
  p=PurePosixPath(m.name)
  if p.is_absolute() or '..' in p.parts or m.issym() or m.islnk(): raise SystemExit(m.name)
PY
tar -xzf "$archive" -C "$tmp"; package="$(find "$tmp" -mindepth 1 -maxdepth 1 -type d -print|head -n1)"
source "$package/lib.sh"; verify_manifest_files "$package"
[[ "$(read_manifest "$package" architecture)" == arm64 ]] || exit 1
[[ "$(read_manifest "$package" runtime_version)" == 2.3.0-slice-d-worker ]] || exit 1
[[ "$(read_manifest "$package" worker_runtime_included)" == True ]] || exit 1
[[ "$(read_manifest "$package" worker_supported_task_types)" == '["system.diagnostic_snapshot", "system.noop"]' ]] || exit 1
[[ "$(read_manifest "$package" diagnostic_hard_timeout_seconds)" == 30 ]] || exit 1
[[ "$(read_manifest "$package" diagnostic_termination_grace_seconds)" == 5 ]] || exit 1
version="$(read_manifest "$package" package_version)"; [[ -n "$version" ]] || exit 1
[[ "$(find "$package/payload/wheelhouse" -maxdepth 1 -type f -name "picotoopet_core-${version//-/_}-*.whl"|wc -l|tr -d ' ')" == 1 ]] || exit 1
for script in INSTALL_MAC_WORKER_SLICE_C.command VERIFY_MAC_WORKER_SLICE_C.command ROLLBACK_MAC_WORKER_SLICE_C.command lib.sh worker-lib.sh; do bash -n "$package/$script"; done
! grep -Fq 'picotoopet-core==2.3.0.dev' "$package/INSTALL_MAC_WORKER_SLICE_C.command"
grep -Fq '"picotoopet-core==$package_version"' "$package/INSTALL_MAC_WORKER_SLICE_C.command"
echo "PHASE23_MAC_WORKER_SLICE_D_PACKAGE_TEST=PASS"
