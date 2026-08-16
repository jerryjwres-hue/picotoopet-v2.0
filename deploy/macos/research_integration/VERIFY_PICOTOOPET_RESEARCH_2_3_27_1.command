#!/bin/bash
# 验证 Gateway、Core/Worker 版本与 research.search 的真实注册状态。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
gateway_root="$script_dir/gateway"
worker_root="$script_dir/worker"
install_root="${PICOTOOPET_RESEARCH_INSTALL_ROOT:-$HOME/Library/Application Support/PicotooPet/ResearchGateway}"
gateway="$install_root/bin/picotoopet-research-gateway"

if [[ ! -x "$gateway" ]]; then
  echo "Research Gateway 未安装：$gateway" >&2
  exit 1
fi

# Gateway 验证只要求本次 research.search 真正依赖的只读边界与 mcporter；其他平台工具是可选能力。
health_file="$(mktemp "${TMPDIR:-/tmp}/picotoopet-research-health.XXXXXX")"
cleanup() {
  rm -f "$health_file"
}
trap cleanup EXIT
"$gateway" --health > "$health_file"
python3 - "$health_file" <<'PY'
import json
import sys
from pathlib import Path

health = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if health.get("version") != "2.3.27.1":
    raise SystemExit(f"unexpected gateway version: {health!r}")
if health.get("read_only") is not True:
    raise SystemExit("Research Gateway must remain read-only")
if health.get("xiaoyuzhou_enabled") is not False:
    raise SystemExit("Xiaoyuzhou must remain disabled")
tools = health.get("tools")
if not isinstance(tools, dict) or tools.get("mcporter") is not True:
    raise SystemExit("mcporter is required for research.search")
PY

# 复用正式 Worker 验证器验证 Core/Worker 安装生命周期、产品版本和已有能力边界。
bash "$worker_root/VERIFY_MAC_WORKER_SLICE_C.command"

# 组合包额外要求 research.search 必须真实出现在 Worker 状态中，否则不能声称“已经接入程序”。
# shellcheck source=/dev/null
source "$worker_root/lib.sh"
runtime_root="$(phase23_runtime_root)"
python3 - "$runtime_root/state/worker-status.json" <<'PY'
import json
import sys
from pathlib import Path

status = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
supported = status.get("supported_task_types")
if status.get("state") != "online" or status.get("available") is not True:
    raise SystemExit(f"Worker is not online: {status!r}")
if not isinstance(supported, list) or "research.search" not in supported:
    raise SystemExit(f"research.search is not registered: {status!r}")
PY

echo "PICOTOOPET_RESEARCH_2_3_27_1_VERIFY=PASS"
