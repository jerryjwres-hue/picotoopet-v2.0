#!/bin/bash
# 安装 PicotooPet Research Gateway 接线层；只绑定现有研究工具，不修改外部工具链。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
payload_dir="$script_dir/payload"
install_root="${PICOTOOPET_RESEARCH_INSTALL_ROOT:-$HOME/Library/Application Support/PicotooPet/ResearchGateway}"
runtime_dir="$install_root/runtime"
bin_dir="$install_root/bin"
state_dir="$install_root/state"

if [[ ! -f "$payload_dir/gateway.py" || ! -f "$payload_dir/VERSION" ]]; then
  echo "安装包损坏：缺少 Research Gateway payload。" >&2
  exit 1
fi

mkdir -p "$runtime_dir" "$bin_dir" "$state_dir"
install -m 0644 "$payload_dir/gateway.py" "$runtime_dir/gateway.py"
install -m 0644 "$payload_dir/VERSION" "$runtime_dir/VERSION"

cat > "$bin_dir/picotoopet-research-gateway" <<EOF
#!/bin/bash
exec python3 "$runtime_dir/gateway.py" "\$@"
EOF
chmod 755 "$bin_dir/picotoopet-research-gateway"

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# 绑定状态：仅记录现有二进制/MCP 是否存在，不执行安装、升级或认证写操作。
agent_reach=0
opencli=0
mcporter=0
gh_cli=0
yt_dlp=0
bili=0
curl_cli=0
scrapling=0
thunderbit=0

if command -v agent-reach >/dev/null 2>&1; then agent_reach=1; fi
if command -v opencli >/dev/null 2>&1; then opencli=1; fi
if command -v mcporter >/dev/null 2>&1; then mcporter=1; fi
if command -v gh >/dev/null 2>&1; then gh_cli=1; fi
if command -v yt-dlp >/dev/null 2>&1; then yt_dlp=1; fi
if command -v bili >/dev/null 2>&1; then bili=1; fi
if command -v curl >/dev/null 2>&1; then curl_cli=1; fi
if [[ -x "$HOME/.local/bin/scrapling-mcp-local" ]]; then scrapling=1; fi
if [[ -d "$HOME/.codex/mcp-servers/thunderbit" ]]; then thunderbit=1; fi

cat > "$state_dir/bindings.json" <<EOF
{
  "agent_reach": $agent_reach,
  "opencli": $opencli,
  "mcporter": $mcporter,
  "gh": $gh_cli,
  "yt_dlp": $yt_dlp,
  "bili": $bili,
  "curl": $curl_cli,
  "scrapling_mcp_local": $scrapling,
  "thunderbit_mcp": $thunderbit
}
EOF

"$bin_dir/picotoopet-research-gateway" --health

printf '\nPicotooPet Research Gateway 2.3.27.1 接线层已更新：\n%s\n' "$bin_dir/picotoopet-research-gateway"
printf '已记录现有工具绑定：%s\n' "$state_dir/bindings.json"
printf '此更新包不会安装、升级或覆盖 Node、OpenCLI、Agent Reach、Scrapling、Thunderbit、Chrome 扩展或浏览器登录态。\n'
printf '请运行 VERIFY_RESEARCH_GATEWAY.command 验证当前可用能力。\n'
