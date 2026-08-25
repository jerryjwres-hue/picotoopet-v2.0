#!/bin/bash
# 验证 Gateway、Core/Worker、research.search 注册，以及所有已接入 Research 工具的真实只读调用。
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

# 第一层：验证 Core/Worker 安装生命周期、版本与固定能力边界。
bash "$worker_root/VERIFY_MAC_WORKER_SLICE_C.command"

# 第二层：research.search 必须由真实在线 Worker 注册，不能只存在于源代码或 Gateway 文件里。
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

# 第三层：复用 Gateway 正式实机验证器做限量真实调用。
# 包括 Exa、Crawl4AI、Scrapling、GitHub、YouTube 与已接入 OpenCLI 社媒渠道；
# Thunderbit 只验证绑定，不自动消耗 credits。任何失败都保留具体能力名供修复。
bash "$gateway_root/VERIFY_RESEARCH_GATEWAY.command"

echo "PICOTOOPET_RESEARCH_2_3_27_1_VERIFY=PASS"
echo "PICOTOOPET_RESEARCH_TOOL_CALLS=PASS"
