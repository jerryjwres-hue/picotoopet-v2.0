#!/bin/bash
# 回滚到安装前记录的 Mac Core 版本；不删除任何版本目录或数据。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=lib.sh
source "$script_dir/lib.sh"

runtime_root="$(phase23_runtime_root)"
previous_file="$runtime_root/state/previous-version.txt"
if [[ ! -f "$previous_file" ]]; then
  echo "未找到 previous-version.txt，无法确定安全回滚目标。" >&2
  exit 1
fi

previous_target="$(tr -d '\r\n' < "$previous_file")"
if [[ -z "$previous_target" || ! -d "$previous_target" ]]; then
  echo "回滚目标不存在：$previous_target" >&2
  exit 1
fi

python3 - "$runtime_root/versions" "$previous_target" <<'PY'
import sys
from pathlib import Path

versions = Path(sys.argv[1]).resolve()
target = Path(sys.argv[2]).resolve()
try:
    target.relative_to(versions)
except ValueError as exc:
    raise SystemExit(f"rollback target is outside versions: {target}") from exc
PY

current_target="$(resolve_current_version "$runtime_root")"
printf '%s\n' "$current_target" > "$runtime_root/state/rollback-from.txt"
port="$(read_existing_port "$runtime_root")"
token="$(read_api_token)"

atomic_switch_current "$runtime_root" "$previous_target"
if [[ "${PICOTOO_FIXTURE_MODE:-0}" == "1" ]]; then
  start_fixture_service \
    "$runtime_root" \
    "$runtime_root/current/.venv/bin/picotoopet-core" \
    "$port" \
    "$token"
else
  restart_user_agent "com.picotoopet.mac-core"
  wait_for_health "http://127.0.0.1:$port"
fi

# 回滚到另一个 Slice B 时验证完整合同；回滚到 2.2 时至少验证健康。
if ! verify_api_contract "http://127.0.0.1:$port" "$token"; then
  verify_health "http://127.0.0.1:$port"
fi

report="$(write_report \
  "$runtime_root" \
  "rollback" \
  "pass" \
  "previous" \
  "$previous_target" \
  "")"
echo "PHASE23_MAC_DELTA_ROLLBACK=PASS"
echo "REPORT=$report"
if [[ "${PICOTOO_FIXTURE_MODE:-0}" != "1" ]]; then
  open "$report"
fi
