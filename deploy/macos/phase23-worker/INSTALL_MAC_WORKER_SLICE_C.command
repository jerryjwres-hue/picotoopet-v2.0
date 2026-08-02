#!/bin/bash
# Picotoo Pet V2 Phase 2.3 Slice C Mac Worker 离线安装器。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
package_root="$script_dir"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --package-root)
      package_root="$(cd "$2" && pwd)"
      shift 2
      ;;
    *)
      echo "未知参数：$1" >&2
      exit 2
      ;;
  esac
done

# shellcheck source=/dev/null
source "$package_root/lib.sh"
# shellcheck source=/dev/null
source "$package_root/worker-lib.sh"

runtime_root="$(phase23_runtime_root)"
versions_root="$runtime_root/versions"
state_root="$runtime_root/state"
current_python="$runtime_root/current/.venv/bin/python"
core_label="com.picotoopet.mac-core"
version=""
new_version=""
previous_target=""
existing_port=""
api_token=""
candidate_pid=""
candidate_root=""
activated=0
worker_started=0
previous_worker_present=0
previous_worker_backup="$state_root/slice-c-previous-worker.plist"
previous_version_file="$state_root/slice-c-previous-version.txt"
worker_present_file="$state_root/slice-c-previous-worker-present.txt"
worker_id="picotoopet-m4-$(id -u)"

mkdir -p "$versions_root" "$state_root" "$runtime_root/reports" "$runtime_root/logs"

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

restart_core_runtime() {
  if [[ "${PICOTOO_FIXTURE_MODE:-0}" == "1" ]]; then
    stop_fixture_service "$runtime_root"
    start_fixture_service \
      "$runtime_root" \
      "$runtime_root/current/.venv/bin/picotoopet-core" \
      "$existing_port" \
      "$api_token"
  else
    restart_user_agent "$core_label"
    wait_for_health "http://127.0.0.1:$existing_port"
  fi
}

restore_previous_worker_definition() {
  stop_worker_agent
  local plist
  plist="$(worker_plist_path)"
  if [[ "$previous_worker_present" == "1" && -f "$previous_worker_backup" ]]; then
    cp "$previous_worker_backup" "$plist"
    chmod 600 "$plist"
    if [[ "${PICOTOO_FIXTURE_MODE:-0}" != "1" ]]; then
      launchctl bootstrap "gui/$UID" "$plist"
      launchctl kickstart -k "gui/$UID/$(worker_label)"
    fi
  else
    rm -f "$plist"
  fi
}

rollback_after_failed_activation() {
  if [[ "$worker_started" == "1" ]]; then
    stop_worker_agent || true
    worker_started=0
  fi
  if [[ "$activated" == "1" && -n "$previous_target" ]]; then
    echo "Slice C 激活失败，正在恢复上一 Core/Worker 组合。" >&2
    atomic_switch_current "$runtime_root" "$previous_target"
    restart_core_runtime
    activated=0
  fi
  restore_previous_worker_definition || true
}

on_error() {
  local code=$?
  local failed_command="${BASH_COMMAND:-unknown command}"
  trap - ERR
  cleanup_candidate
  rollback_after_failed_activation || true
  local report
  report="$(write_worker_report \
    "$runtime_root" \
    "install" \
    "fail" \
    "$version" \
    "$new_version" \
    "命令失败：$failed_command")" || true
  echo "Slice C Worker 安装失败。报告：$report" >&2
  exit "$code"
}
trap on_error ERR
trap cleanup_candidate EXIT

verify_manifest_files "$package_root"
version="$(read_manifest "$package_root" version)"
package_version="$(read_manifest "$package_root" package_version)"
runtime_version="$(read_manifest "$package_root" runtime_version)"
package_arch="$(read_manifest "$package_root" architecture)"
worker_included="$(read_manifest "$package_root" worker_runtime_included)"

if [[ "$package_version" != "2.3.0.dev2" ]]; then
  echo "包版本不符合 Slice C：$package_version" >&2
  exit 1
fi
if [[ "$runtime_version" != "2.3.0-slice-c" ]]; then
  echo "运行时版本不符合 Slice C：$runtime_version" >&2
  exit 1
fi
if [[ "$package_arch" != "arm64" || "$package_arch" != "$(uname -m)" ]]; then
  echo "安装包仅支持 M4/Apple Silicon arm64；本机为 $(uname -m)。" >&2
  exit 1
fi
if [[ "$worker_included" != "True" && "$worker_included" != "true" ]]; then
  echo "发布清单未声明 Worker Runtime。" >&2
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

printf '%s\n' "$previous_target" > "$previous_version_file"
plist="$(worker_plist_path)"
if [[ -f "$plist" ]]; then
  previous_worker_present=1
  cp "$plist" "$previous_worker_backup"
else
  previous_worker_present=0
  rm -f "$previous_worker_backup"
fi
printf '%s\n' "$previous_worker_present" > "$worker_present_file"

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
  "picotoopet-core==2.3.0.dev2"

candidate_root="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-slice-c-candidate.XXXXXX")"
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
verify_slice_c_candidate_contract "$candidate_url" "$api_token"
cleanup_candidate

stop_worker_agent
atomic_switch_current "$runtime_root" "$new_version"
activated=1
restart_core_runtime
verify_slice_c_candidate_contract "http://127.0.0.1:$existing_port" "$api_token"

write_worker_plist "$runtime_root" "$worker_id"
start_worker_agent "$runtime_root" "$worker_id" "$api_token"
worker_started=1
wait_for_worker_state "$runtime_root" "online"
verify_worker_api_contract "http://127.0.0.1:$existing_port" "$api_token"

activated=0
worker_started=0
report="$(write_worker_report \
  "$runtime_root" \
  "install" \
  "pass" \
  "$version" \
  "$new_version" \
  "")"
echo "PHASE23_MAC_WORKER_INSTALL=PASS"
echo "REPORT=$report"
if [[ "${PICOTOO_FIXTURE_MODE:-0}" != "1" ]]; then
  open "$report"
fi
