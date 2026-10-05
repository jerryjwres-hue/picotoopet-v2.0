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
# shellcheck source=/dev/null
source "$package_root/worker-lib.sh"
verify_manifest_files "$package_root"

product_version="$(phase23_worker_product_version "$package_root")"
if [[ "$(read_manifest "$package_root" product_version)" != "$product_version" ]]; then
  echo "清单 product_version 与包内唯一版本文件不一致。" >&2
  exit 1
fi
if [[ "$(basename "$archive")" != *"-$product_version-"* ]]; then
  echo "包名未包含产品版本：$product_version" >&2
  exit 1
fi
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
autonomous_included="$(read_manifest "$package_root" autonomous_slice_c_included)"
if [[ "$autonomous_included" != "True" && "$autonomous_included" != "true" ]]; then
  echo "清单未声明 Autonomous Intelligence Slice C。" >&2
  exit 1
fi
if [[ "$(read_manifest "$package_root" autonomous_capabilities)" != '["content.discovery", "browser.capture.contract", "objective.query.planning"]' ]]; then
  echo "清单 Autonomous Intelligence 能力不符合冻结合同。" >&2
  exit 1
fi
goal_center_included="$(read_manifest "$package_root" goal_center_e2e_included)"
if [[ "$goal_center_included" != "True" && "$goal_center_included" != "true" ]]; then
  echo "清单未声明 Goal Center E2E 交付。" >&2
  exit 1
fi
if [[ "$(read_manifest "$package_root" goal_center_live_verifier)" != "VERIFY_GOAL_CENTER_E2E.command" ]]; then
  echo "清单 Goal Center 实机验收入口不正确。" >&2
  exit 1
fi
if [[ "$(read_manifest "$package_root" coding_provider_live_verifier)" != "VERIFY_CODING_PROVIDERS.command" ]]; then
  echo "清单 Coding Provider 实机验收入口不正确。" >&2
  exit 1
fi
if [[ "$(read_manifest "$package_root" goal_center_runtime_task_types)" != '["autonomous.discovery.v1", "autonomous.goal_synthesis.v1", "autonomous.goal_handoff.v1"]' ]]; then
  echo "清单 Goal Center 动态任务类型不符合冻结链路。" >&2
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
project_wheel="$(find "$wheelhouse" -maxdepth 1 -type f \
  -name "picotoopet_core-${package_version//-/_}-*.whl" -print | head -n 1)"
python3 - "$project_wheel" <<'PY'
import sys
import zipfile

required = {
    "picotoopet_core/autonomous/legacy_acquisition.py",
    "picotoopet_core/autonomous/discovery.py",
    "picotoopet_core/api/routes/autonomous_goals.py",
    "picotoopet_core/api/routes/autonomous_intake.py",
    "picotoopet_core/autonomous/human_pipeline.py",
    "picotoopet_core/autonomous/intake_autopilot.py",
    "picotoopet_core/autonomous/legacy_import.py",
    "picotoopet_core/autonomous/browser_broker.py",
    "picotoopet_core/autonomous/goal_handoff_access.py",
    "picotoopet_core/autonomous/prompts/web_gpt_master_v1.txt",
    "picotoopet_core/api/routes/frugal_escalation.py",
    "picotoopet_core/deep_ai/frugal.py",
    "picotoopet_core/deep_ai/frugal_repository.py",
    "picotoopet_core/providers/frugal_service.py",
    "picotoopet_core/worker/codex_adapter.py",
    "picotoopet_core/worker/claude_code_adapter.py",
}
with zipfile.ZipFile(sys.argv[1], "r") as wheel:
    names = set(wheel.namelist())
missing = sorted(required - names)
if missing:
    raise SystemExit(f"Goal Center Mac Worker wheel content missing: {missing!r}")
PY
echo "PHASE23_MAC_WORKER_GOAL_CENTER_CONTENT=PASS"

for script in \
  INSTALL_MAC_WORKER_SLICE_C.command \
  VERIFY_MAC_WORKER_SLICE_C.command \
  VERIFY_GOAL_CENTER_E2E.command \
  VERIFY_CODING_PROVIDERS.command \
  ROLLBACK_MAC_WORKER_SLICE_C.command \
  lib.sh \
  worker-lib.sh; do
  if [[ ! -f "$package_root/$script" ]]; then
    echo "包内缺少脚本：$script" >&2
    exit 1
  fi
  bash -n "$package_root/$script"
done

live_verifier="$package_root/VERIFY_GOAL_CENTER_E2E.command"
for marker in \
  "autonomous.discovery.v1" \
  "autonomous.goal_synthesis.v1" \
  "autonomous.goal_handoff.v1" \
  "/api/v1/autonomous/goals/templates" \
  "/api/v1/autonomous/goals" \
  "PHASE23_GOAL_CENTER_E2E_READY=PASS"; do
  if ! grep -Fq "$marker" "$live_verifier"; then
    echo "Goal Center 实机验收器缺少冻结标记：$marker" >&2
    exit 1
  fi
done
if grep -Fq "PICOTOO_FIXTURE_MODE" "$live_verifier"; then
  echo "Goal Center 实机验收器不得降级到 fixture 模式。" >&2
  exit 1
fi

echo "PHASE23_MAC_WORKER_GOAL_CENTER_LIVE_VERIFIER=PASS"

coding_verifier="$package_root/VERIFY_CODING_PROVIDERS.command"
for marker in \
  "/api/v1/providers/codex/status" \
  "/api/v1/providers/claude-code/status" \
  "CODEX_READINESS=" \
  "CLAUDE_CODE_READINESS=" \
  "AUTHENTICATION_USER_ACTION_REQUIRED=true" \
  "CODING_PROVIDER_PROBE_NETWORK_TRIGGERED=false" \
  "CODING_PROVIDER_EXECUTION_TRIGGERED=false"; do
  if ! grep -Fq "$marker" "$coding_verifier"; then
    echo "Coding Provider 实机验收器缺少冻结标记：$marker" >&2
    exit 1
  fi
done
if grep -Fq "PICOTOO_FIXTURE_MODE" "$coding_verifier"; then
  echo "Coding Provider 实机验收器不得降级到 fixture 模式。" >&2
  exit 1
fi

echo "PHASE23_MAC_WORKER_CODING_PROVIDER_VERIFIER=PASS"

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
if ! grep -Fq 'verify_worker_product_version "$runtime_root" "$product_version"' "$installer"; then
  echo "安装器没有验证激活 Worker 的产品版本。" >&2
  exit 1
fi

combined="$(cat \
  "$package_root/INSTALL_MAC_WORKER_SLICE_C.command" \
  "$package_root/VERIFY_MAC_WORKER_SLICE_C.command" \
  "$package_root/VERIFY_GOAL_CENTER_E2E.command" \
  "$package_root/VERIFY_CODING_PROVIDERS.command" \
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

echo "PHASE23_MAC_WORKER_AUTONOMOUS_SLICE_C=PASS"
echo "PHASE23_MAC_WORKER_PACKAGE_TEST=PASS"
echo "PHASE23_MAC_WORKER_SLICE_D_PACKAGE_TEST=PASS"
echo "PRODUCT_VERSION=$product_version"
echo "PACKAGE=$archive"
