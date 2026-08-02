#!/bin/bash
# Picotoo Pet V2 Phase 2.3 Slice B Mac Core 增量安装器。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
package_root="$script_dir"
preflight_only=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --package-root)
      package_root="$(cd "$2" && pwd)"
      shift 2
      ;;
    --preflight-only)
      preflight_only=1
      shift
      ;;
    *)
      echo "未知参数：$1" >&2
      exit 2
      ;;
  esac
done

# shellcheck source=lib.sh
source "$package_root/lib.sh"

runtime_root="$(phase23_runtime_root)"
versions_root="$runtime_root/versions"
state_root="$runtime_root/state"
reports_root="$runtime_root/reports"
current_python="$runtime_root/current/.venv/bin/python"
label="com.picotoopet.mac-core"
version=""
new_version=""
previous_target=""
existing_port=""
api_token=""
candidate_pid=""
candidate_root=""
activated=0

mkdir -p "$versions_root" "$state_root" "$reports_root" "$runtime_root/logs"

cleanup_candidate() {
  if [[ -n "$candidate_pid" ]] && kill -0 "$candidate_pid" >/dev/null 2>&1; then
    kill "$candidate_pid" >/dev/null 2>&1 || true
    wait "$candidate_pid" >/dev/null 2>&1 || true
  fi
  candidate_pid=""
  if [[ -n "$candidate_root" && -d "$candidate_root" ]]; then
    rm -rf "$candidate_root"
  fi
  candidate_root=""
}

rollback_after_failed_activation() {
  if [[ "$activated" != "1" || -z "$previous_target" ]]; then
    return 0
  fi
  echo "激活后验证失败，正在恢复上一版本。" >&2
  atomic_switch_current "$runtime_root" "$previous_target"
  if [[ "${PICOTOO_FIXTURE_MODE:-0}" == "1" ]]; then
    stop_fixture_service "$runtime_root"
    start_fixture_service \
      "$runtime_root" \
      "$runtime_root/current/.venv/bin/picotoopet-core" \
      "$existing_port" \
      "$api_token"
  else
    restart_user_agent "$label"
    wait_for_health "http://127.0.0.1:$existing_port"
  fi
  activated=0
}

on_error() {
  local code=$?
  local failed_command="${BASH_COMMAND:-unknown command}"
  trap - ERR
  cleanup_candidate
  rollback_after_failed_activation || true
  local report
  report="$(write_report \
    "$runtime_root" \
    "install" \
    "fail" \
    "$version" \
    "$new_version" \
    "命令失败：$failed_command")" || true
  echo "安装失败。报告：$report" >&2
  exit "$code"
}
trap on_error ERR
trap cleanup_candidate EXIT

verify_manifest_files "$package_root"
version="$(read_manifest "$package_root" version)"
package_version="$(read_manifest "$package_root" package_version)"
package_arch="$(read_manifest "$package_root" architecture)"

if [[ "$package_version" != "2.3.0.dev1" ]]; then
  echo "包版本不符合 Slice B：$package_version" >&2
  exit 1
fi
if [[ "$package_arch" != "$(uname -m)" ]]; then
  echo "安装包架构 $package_arch 与本机 $(uname -m) 不一致。" >&2
  exit 1
fi
if [[ ! -x "$current_python" ]]; then
  echo "缺少现有运行时 Python：$current_python" >&2
  exit 1
fi
python_version="$("$current_python" --version 2>&1)"
if [[ "$python_version" != Python\ 3.12.* ]]; then
  echo "现有运行时不是 Python 3.12：$python_version" >&2
  exit 1
fi

previous_target="$(resolve_current_version "$runtime_root")"
existing_port="$(read_existing_port "$runtime_root")"
api_token="$(read_api_token)"
if [[ ${#api_token} -lt 16 ]]; then
  echo "现有 API 令牌无效；安装已停止。" >&2
  exit 1
fi

printf '%s\n' "$previous_target" > "$state_root/previous-version.txt"
new_version="$versions_root/${version}-${package_arch}"
if [[ -e "$new_version" ]]; then
  echo "目标版本已存在，拒绝覆盖：$new_version" >&2
  exit 1
fi
mkdir -p "$new_version"

"$current_python" -m venv "$new_version/.venv"
"$new_version/.venv/bin/python" -m pip install \
  --no-index \
  --find-links "$package_root/payload/wheelhouse" \
  "picotoopet-core==2.3.0.dev1"

candidate_root="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-slice-b-candidate.XXXXXX")"
candidate_port="$(choose_free_port)"
PICOTOO_RUNTIME_ROOT="$candidate_root" \
PICOTOO_API_HOST="127.0.0.1" \
PICOTOO_API_PORT="$candidate_port" \
PICOTOO_API_TOKEN="$api_token" \
  "$new_version/.venv/bin/picotoopet-core" serve \
    >"$candidate_root/candidate.stdout.log" \
    2>"$candidate_root/candidate.stderr.log" &
candidate_pid=$!

candidate_url="http://127.0.0.1:$candidate_port"
wait_for_health "$candidate_url"
verify_api_contract "$candidate_url" "$api_token"
cleanup_candidate

if [[ "$preflight_only" == "1" ]]; then
  report="$(write_report \
    "$runtime_root" \
    "install-preflight" \
    "pass" \
    "$version" \
    "$new_version" \
    "")"
  echo "PHASE23_MAC_DELTA_PREFLIGHT=PASS"
  echo "REPORT=$report"
  exit 0
fi

atomic_switch_current "$runtime_root" "$new_version"
activated=1

if [[ "${PICOTOO_FIXTURE_MODE:-0}" == "1" ]]; then
  start_fixture_service \
    "$runtime_root" \
    "$runtime_root/current/.venv/bin/picotoopet-core" \
    "$existing_port" \
    "$api_token"
else
  restart_user_agent "$label"
  wait_for_health "http://127.0.0.1:$existing_port"
fi

verify_api_contract "http://127.0.0.1:$existing_port" "$api_token"
activated=0

report="$(write_report \
  "$runtime_root" \
  "install" \
  "pass" \
  "$version" \
  "$new_version" \
  "")"
echo "PHASE23_MAC_DELTA_INSTALL=PASS"
echo "REPORT=$report"
if [[ "${PICOTOO_FIXTURE_MODE:-0}" != "1" ]]; then
  open "$report"
fi
