#!/bin/bash
# 安装独立 Research Gateway；外部联网工具保持在 Mac Core 虚拟环境之外。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
payload_dir="$script_dir/payload"
install_root="${PICOTOOPET_RESEARCH_INSTALL_ROOT:-$HOME/Library/Application Support/PicotooPet/ResearchGateway}"
runtime_dir="$install_root/runtime"
bin_dir="$install_root/bin"
skip_external="${PICOTOOPET_RESEARCH_SKIP_EXTERNAL_INSTALL:-0}"

if [[ ! -f "$payload_dir/gateway.py" || ! -f "$payload_dir/VERSION" ]]; then
  echo "安装包损坏：缺少 Research Gateway payload。" >&2
  exit 1
fi

mkdir -p "$runtime_dir" "$bin_dir"
install -m 0644 "$payload_dir/gateway.py" "$runtime_dir/gateway.py"
install -m 0644 "$payload_dir/VERSION" "$runtime_dir/VERSION"

cat > "$bin_dir/picotoopet-research-gateway" <<EOF
#!/bin/bash
exec python3 "$runtime_dir/gateway.py" "\$@"
EOF
chmod 755 "$bin_dir/picotoopet-research-gateway"

if [[ "$skip_external" != "1" ]]; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "缺少 Homebrew。请先安装 Homebrew 后重新双击本安装包。" >&2
    exit 1
  fi

  brew install pipx gh uv node
  pipx ensurepath >/dev/null 2>&1 || true
  export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

  if command -v agent-reach >/dev/null 2>&1; then
    pipx upgrade agent-reach || true
  else
    pipx install https://github.com/Panniantong/agent-reach/archive/main.zip
  fi

  npm install -g @jackwener/opencli@latest
  agent-reach install --env=auto --system \
    --channels=opencli,twitter,xueqiu,xiaohongshu,reddit,facebook,instagram,bilibili,linkedin
fi

"$bin_dir/picotoopet-research-gateway" --health
printf '\nResearch Gateway 2.3.27.1 已安装：\n%s\n' "$bin_dir/picotoopet-research-gateway"
printf '下一步：在 PicotooPet Research Chrome Profile 中完成各平台登录，再运行 VERIFY_RESEARCH_GATEWAY.command。\n'
