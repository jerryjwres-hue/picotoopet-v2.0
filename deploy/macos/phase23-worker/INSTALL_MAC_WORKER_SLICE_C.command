#!/bin/bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
package_root="$script_dir"
while [[ $# -gt 0 ]]; do case "$1" in --package-root) package_root="$(cd "$2" && pwd)"; shift 2;; *) echo "未知参数：$1" >&2; exit 2;; esac; done
source "$package_root/lib.sh"
source "$package_root/worker-lib.sh"
runtime_root="$(phase23_runtime_root)"; versions_root="$runtime_root/versions"; state_root="$runtime_root/state"
current_python="$runtime_root/current/.venv/bin/python"; core_label="com.picotoopet.mac-core"
version=""; new_version=""; previous_target=""; existing_port=""; api_token=""; candidate_pid=""; candidate_root=""; activated=0; worker_started=0
previous_worker_present=0; backup_captured=0
previous_worker_backup="$state_root/slice-d-previous-worker.plist"; previous_version_file="$state_root/slice-d-previous-version.txt"; worker_present_file="$state_root/slice-d-previous-worker-present.txt"
worker_id="picotoopet-m4-$(id -u)"
mkdir -p "$versions_root" "$state_root" "$runtime_root/reports" "$runtime_root/logs"
cleanup_candidate(){ if [[ -n "$candidate_pid" ]] && kill -0 "$candidate_pid" >/dev/null 2>&1; then kill "$candidate_pid" || true; wait "$candidate_pid" || true; fi; candidate_pid=""; [[ -z "$candidate_root" ]] || rm -rf "$candidate_root"; candidate_root=""; }
restart_core(){ if [[ "${PICOTOO_FIXTURE_MODE:-0}" == 1 ]]; then stop_fixture_service "$runtime_root"; start_fixture_service "$runtime_root" "$runtime_root/current/.venv/bin/picotoopet-core" "$existing_port" "$api_token"; else restart_user_agent "$core_label"; wait_for_health "http://127.0.0.1:$existing_port"; fi; }
restore_worker(){ stop_worker_agent || true; plist="$(worker_plist_path)"; if [[ "$backup_captured" == 1 && "$previous_worker_present" == 1 && -f "$previous_worker_backup" ]]; then cp "$previous_worker_backup" "$plist"; chmod 600 "$plist"; [[ "${PICOTOO_FIXTURE_MODE:-0}" == 1 ]] || { launchctl bootstrap "gui/$UID" "$plist"; launchctl kickstart -k "gui/$UID/$(worker_label)"; }; else rm -f "$plist"; fi; }
rollback_failed(){ [[ "$worker_started" != 1 ]] || { stop_worker_agent || true; worker_started=0; }; if [[ "$activated" == 1 && -n "$previous_target" ]]; then atomic_switch_current "$runtime_root" "$previous_target"; restart_core; activated=0; fi; restore_worker || true; }
on_error(){ code=$?; failed="${BASH_COMMAND:-unknown command}"; trap - ERR; cleanup_candidate; rollback_failed || true; report="$(write_worker_report "$runtime_root" install fail "$version" "$new_version" "命令失败：$failed" false)" || true; echo "Slice D Worker 安装失败。报告：$report" >&2; exit "$code"; }
trap on_error ERR; trap cleanup_candidate EXIT
verify_manifest_files "$package_root"
version="$(read_manifest "$package_root" version)"; package_version="$(read_manifest "$package_root" package_version)"; runtime_version="$(read_manifest "$package_root" runtime_version)"; arch="$(read_manifest "$package_root" architecture)"; included="$(read_manifest "$package_root" worker_runtime_included)"; types="$(read_manifest "$package_root" worker_supported_task_types)"; timeout="$(read_manifest "$package_root" diagnostic_hard_timeout_seconds)"; grace="$(read_manifest "$package_root" diagnostic_termination_grace_seconds)"
[[ "$runtime_version" == 2.3.0-slice-d-worker ]] || { echo "runtime_version 错误。" >&2; exit 1; }
[[ "$arch" == arm64 && "$(uname -m)" == arm64 ]] || { echo "仅支持 arm64。" >&2; exit 1; }
[[ "$included" == True || "$included" == true ]] || exit 1
[[ "$types" == '["system.diagnostic_snapshot", "system.noop"]' ]] || { echo "支持类型不符合冻结合同。" >&2; exit 1; }
[[ "$timeout" == 30 && "$grace" == 5 ]] || { echo "超时合同错误。" >&2; exit 1; }
[[ -n "$package_version" ]] || exit 1
[[ "$(find "$package_root/payload/wheelhouse" -maxdepth 1 -type f -name "picotoopet_core-${package_version//-/_}-*.whl" | wc -l | tr -d ' ')" == 1 ]] || exit 1
[[ -x "$current_python" ]] || exit 1
[[ "$("$current_python" --version 2>&1)" == Python\ 3.12.* ]] || exit 1
previous_target="$(resolve_current_version "$runtime_root")"; existing_port="$(read_existing_port "$runtime_root")"; api_token="$(read_api_token)"
[[ ${#api_token} -ge 16 ]] || exit 1
printf '%s\n' "$previous_target" > "$previous_version_file"
plist="$(worker_plist_path)"; if [[ -f "$plist" ]]; then previous_worker_present=1; cp "$plist" "$previous_worker_backup"; else rm -f "$previous_worker_backup"; fi; printf '%s\n' "$previous_worker_present" > "$worker_present_file"; backup_captured=1
new_version="$versions_root/${version}-${arch}"; [[ ! -e "$new_version" ]] || { echo "目标版本已存在。" >&2; exit 1; }; mkdir -p "$new_version"
"$current_python" -m venv "$new_version/.venv"
"$new_version/.venv/bin/python" -m pip install --no-index --find-links "$package_root/payload/wheelhouse" "picotoopet-core==$package_version"
candidate_root="$(mktemp -d "${TMPDIR:-/tmp}/picotoopet-slice-d-worker-candidate.XXXXXX")"; candidate_port="$(choose_free_port)"
PICOTOO_RUNTIME_ROOT="$candidate_root" PICOTOO_API_HOST=127.0.0.1 PICOTOO_API_PORT="$candidate_port" PICOTOO_API_TOKEN="$api_token" "$new_version/.venv/bin/picotoopet-core" serve >"$candidate_root/stdout.log" 2>"$candidate_root/stderr.log" & candidate_pid=$!
wait_for_health "http://127.0.0.1:$candidate_port"; verify_slice_d_candidate_contract "http://127.0.0.1:$candidate_port" "$api_token"; cleanup_candidate
stop_worker_agent; atomic_switch_current "$runtime_root" "$new_version"; activated=1; restart_core; verify_slice_d_candidate_contract "http://127.0.0.1:$existing_port" "$api_token"
write_worker_plist "$runtime_root" "$worker_id"; start_worker_agent "$runtime_root" "$worker_id" "$api_token"; worker_started=1; wait_for_worker_state "$runtime_root" online; verify_worker_api_contract "http://127.0.0.1:$existing_port" "$api_token"
activated=0; worker_started=0
report="$(write_worker_report "$runtime_root" install pass "$version" "$new_version" "" true)"
echo "PHASE23_MAC_WORKER_SLICE_D_INSTALL=PASS"; echo "REPORT=$report"; [[ "${PICOTOO_FIXTURE_MODE:-0}" == 1 ]] || open "$report"
