#!/bin/bash
# PicotooPet 2.3.27.1 Research 一体化安装：先绑定 Gateway，再原子升级 Core/Worker。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
gateway_root="$script_dir/gateway"
worker_root="$script_dir/worker"

for required in \
  "$gateway_root/INSTALL_RESEARCH_GATEWAY.command" \
  "$worker_root/INSTALL_MAC_WORKER_SLICE_C.command"; do
  if [[ ! -f "$required" ]]; then
    echo "安装包损坏：缺少 $required" >&2
    exit 1
  fi
done

# 顺序边界：Gateway 必须先就绪，新的 Worker 启动时才会安全注册 research.search。
bash "$gateway_root/INSTALL_RESEARCH_GATEWAY.command"
bash "$worker_root/INSTALL_MAC_WORKER_SLICE_C.command" --package-root "$worker_root"

# 最终验收由组合验证器确认 Worker 已真实宣告 research.search，而不是只装了文件。
# 安装阶段验收：只验证 PicotooPet 自身安装合同，不把共享外部服务健康度当作安装成败。
bash "$script_dir/VERIFY_PICOTOOPET_RESEARCH_2_3_27_1.command" --mode install-contract

echo "PICOTOOPET_RESEARCH_2_3_27_1_INSTALL=PASS"
