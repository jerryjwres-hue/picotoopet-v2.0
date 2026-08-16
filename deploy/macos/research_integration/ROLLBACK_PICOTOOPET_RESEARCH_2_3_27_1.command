#!/bin/bash
# 回滚 PicotooPet Core/Worker 到安装前版本；保留独立 Gateway 与用户现有研究工具链。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
worker_root="$script_dir/worker"

if [[ ! -f "$worker_root/ROLLBACK_MAC_WORKER_SLICE_C.command" ]]; then
  echo "安装包损坏：缺少 Worker 回滚器。" >&2
  exit 1
fi

# 安全边界：Gateway 可能在本次升级之前就已存在，回滚程序不得误删共享研究环境。
bash "$worker_root/ROLLBACK_MAC_WORKER_SLICE_C.command"

echo "PICOTOOPET_RESEARCH_2_3_27_1_ROLLBACK=PASS"
echo "Research Gateway 与 Agent Reach/OpenCLI/Scrapling/Thunderbit 等现有工具均已保留。"
