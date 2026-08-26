#!/bin/bash
# 验证 Gateway、Core/Worker 与 research.search；full 模式额外验证共享外部 Research 工具。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
gateway_root="$script_dir/gateway"
worker_root="$script_dir/worker"
install_root="${PICOTOOPET_RESEARCH_INSTALL_ROOT:-$HOME/Library/Application Support/PicotooPet/ResearchGateway}"
gateway="$install_root/bin/picotoopet-research-gateway"
verify_mode="full"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --mode)
      [[ "$#" -ge 2 ]] || { echo "--mode 缺少参数" >&2; exit 2; }
      verify_mode="$2"
      shift 2
      ;;
    *)
      echo "未知参数：$1" >&2
      exit 2
      ;;
  esac
done

case "$verify_mode" in
  full|install-contract) ;;
  *)
    echo "不支持的验证模式：$verify_mode；允许 full 或 install-contract。" >&2
    exit 2
    ;;
esac

if [[ ! -x "$gateway" ]]; then
  echo "Research Gateway 未安装：$gateway" >&2
  exit 1
fi

# 第一层：Core/Worker 属于 PicotooPet 自身安装合同，任何模式都必须通过。
bash "$worker_root/VERIFY_MAC_WORKER_SLICE_C.command"

# 第二层：research.search 必须由真实在线 Worker 注册，不能只存在于文件或 Gateway 代码里。
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

# 第三层：把同一验证模式传给 Gateway；install-contract 不要求共享 CLI、账号或在线平台健康。
bash "$gateway_root/VERIFY_RESEARCH_GATEWAY.command" --mode "$verify_mode"

echo "PICOTOOPET_RESEARCH_2_3_27_1_VERIFY=PASS"
if [[ "$verify_mode" == "full" ]]; then
  echo "PICOTOOPET_RESEARCH_TOOL_CALLS=PASS"
else
  echo "PICOTOOPET_RESEARCH_INSTALL_CONTRACT=PASS"
  echo "PICOTOOPET_RESEARCH_SHARED_HEALTH=NOT_REQUIRED"
fi
