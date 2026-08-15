#!/bin/bash
# 验证独立 Research Gateway 运行时与外部研究工具；不会读取或导出浏览器 Cookie。
set -euo pipefail

install_root="${PICOTOOPET_RESEARCH_INSTALL_ROOT:-$HOME/Library/Application Support/PicotooPet/ResearchGateway}"
gateway="$install_root/bin/picotoopet-research-gateway"

if [[ ! -x "$gateway" ]]; then
  echo "Research Gateway 尚未安装：$gateway" >&2
  exit 1
fi

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
"$gateway" --health

missing=0
for tool in agent-reach opencli mcporter gh yt-dlp bili curl; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf 'OK   %s\n' "$tool"
  else
    printf 'MISS %s\n' "$tool"
    missing=1
  fi
done

if command -v opencli >/dev/null 2>&1; then
  opencli doctor || true
fi
if command -v agent-reach >/dev/null 2>&1; then
  agent-reach doctor || true
fi
if command -v gh >/dev/null 2>&1; then
  gh auth status || true
fi

if [[ "$missing" -ne 0 ]]; then
  echo "Research Gateway 本体已安装，但仍有外部工具缺失。请重新运行 INSTALL_RESEARCH_GATEWAY.command。" >&2
  exit 1
fi

echo "RESEARCH_GATEWAY_VERIFY=PASS"
