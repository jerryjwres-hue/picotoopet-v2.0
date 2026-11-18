#!/bin/bash
# 导出契约、运行测试并执行发布秘密扫描。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if ! command -v uv >/dev/null 2>&1; then
  echo "未找到 uv，请先运行 Mac 安装器。" >&2
  exit 1
fi
uv run python scripts/export_contracts.py
uv run pytest -q
uv run python scripts/verify_release.py
open "$ROOT/docs/phase1/RELEASE_VERIFICATION_REPORT.md" 2>/dev/null || true
