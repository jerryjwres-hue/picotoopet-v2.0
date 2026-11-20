#!/bin/bash
# Mac 本地手动显示一次性配对信息；不向网络、文件或安装日志写入密钥。
set -euo pipefail

SERVICE="PicotooPetV3.WorkerAttestation"
ACCOUNT="$(id -un)"

if ! WORKER_KEY="$(security find-generic-password -a "$ACCOUNT" -s "$SERVICE" -w 2>/dev/null)"; then
  printf '找不到 Worker 配对密钥。请先使用最新版 INSTALL_MAC.command 安装。\n' >&2
  exit 2
fi
# macOS 内置 Bash 3.2 兼容：长度加字符白名单，不依赖正则量词。
if [ "${#WORKER_KEY}" -lt 43 ] || [ "${#WORKER_KEY}" -gt 256 ]; then
  printf 'Worker 配对密钥长度不正确，请停止配对。\\n' >&2
  exit 2
fi
case "$WORKER_KEY" in
  *[!a-zA-Z0-9_-]*)
    printf 'Worker 配对密钥包含非法字符，请停止配对。\\n' >&2
    exit 2
    ;;
esac

printf '\nPicotooPet | Mac 与 Windows Worker 首次配对\n'
printf 'Worker ID: edit-workstation\n'
printf 'Worker HMAC 密钥（仅在本机终端展示，请勿发送到聊天、截图或日志）：\n%s\n' "$WORKER_KEY"
unset WORKER_KEY

printf '\n在 Windows Studio 的「一次配对并启动 Worker」窗口填入以上两项。\n'
printf '注意：还需要安全的 Mac 连接、Owner/MASTER 审核和独立 GPU 放行。\n'
printf '按回车结束本地显示。\n'
read -r _ || true
