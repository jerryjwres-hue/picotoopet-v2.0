#!/bin/bash
# 修复流程先备份数据库，再重新执行同版本幂等安装。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"$SCRIPT_DIR/BACKUP_MAC.command" || true
"$SCRIPT_DIR/INSTALL_MAC.command"
