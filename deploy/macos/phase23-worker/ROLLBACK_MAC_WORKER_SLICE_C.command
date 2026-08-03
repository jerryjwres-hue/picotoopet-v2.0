#!/bin/bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"; source "$script_dir/lib.sh"; source "$script_dir/worker-lib.sh"
root="$(phase23_runtime_root)"; state="$root/state"; previous_file="$state/slice-d-previous-version.txt"; present_file="$state/slice-d-previous-worker-present.txt"; backup="$state/slice-d-previous-worker.plist"; current="$(resolve_current_version "$root")"; port="$(read_existing_port "$root")"; token="$(read_api_token)"
on_error(){ code=$?; failed="${BASH_COMMAND:-unknown command}"; trap - ERR; report="$(write_worker_report "$root" rollback fail 2.3.0-slice-d-worker "$current" "命令失败：$failed" false)" || true; echo "回滚失败：$report" >&2; exit "$code"; }; trap on_error ERR
[[ -f "$previous_file" ]] || exit 1; previous="$(cat "$previous_file")"; [[ -d "$previous" ]] || exit 1; present=0; [[ ! -f "$present_file" ]] || present="$(tr -d '[:space:]' < "$present_file")"
stop_worker_agent; atomic_switch_current "$root" "$previous"
if [[ "${PICOTOO_FIXTURE_MODE:-0}" == 1 ]]; then stop_fixture_service "$root"; start_fixture_service "$root" "$root/current/.venv/bin/picotoopet-core" "$port" "$token"; else restart_user_agent com.picotoopet.mac-core; wait_for_health "http://127.0.0.1:$port"; fi
verify_health "http://127.0.0.1:$port"
plist="$(worker_plist_path)"; if [[ "$present" == 1 && -f "$backup" ]]; then cp "$backup" "$plist"; chmod 600 "$plist"; [[ "${PICOTOO_FIXTURE_MODE:-0}" == 1 ]] || { launchctl bootstrap "gui/$UID" "$plist"; launchctl kickstart -k "gui/$UID/$(worker_label)"; }; else rm -f "$plist" "$root/state/worker-status.json"; fi
printf '%s\n' "$current" > "$state/slice-d-rollback-from.txt"
report="$(write_worker_report "$root" rollback pass previous "$previous" "" false)"; echo "PHASE23_MAC_WORKER_SLICE_D_ROLLBACK=PASS"; echo "REPORT=$report"; [[ "${PICOTOO_FIXTURE_MODE:-0}" == 1 ]] || open "$report"
