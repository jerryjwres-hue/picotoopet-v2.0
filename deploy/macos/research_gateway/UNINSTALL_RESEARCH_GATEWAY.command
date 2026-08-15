#!/bin/bash
# 仅移除 PicotooPet Research Gateway 本体；保留可能被其他工具共用的 Homebrew/pipx/npm 依赖。
set -euo pipefail

install_root="${PICOTOOPET_RESEARCH_INSTALL_ROOT:-$HOME/Library/Application Support/PicotooPet/ResearchGateway}"

if [[ -d "$install_root" ]]; then
  rm -rf "$install_root"
  printf '已移除 Research Gateway：%s\n' "$install_root"
else
  printf 'Research Gateway 已不存在：%s\n' "$install_root"
fi
