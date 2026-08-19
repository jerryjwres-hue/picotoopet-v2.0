#!/bin/bash
# 只读检查 Codex / Claude Code readiness；不执行 Provider、不登录、不访问外网。
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$script_dir/lib.sh"
# shellcheck source=/dev/null
source "$script_dir/worker-lib.sh"

runtime_root="$(phase23_runtime_root)"
expected_product_version="$(phase23_worker_product_version "$script_dir")"
manifest_product_version="$(read_manifest "$script_dir" product_version)"
if [[ "$manifest_product_version" != "$expected_product_version" ]]; then
  echo "Coding Provider 验收失败：Mac Worker Manifest 产品版本不一致。" >&2
  exit 1
fi

port="$(read_existing_port "$runtime_root")"
token="$(read_api_token)"
base_url="http://127.0.0.1:$port"

verify_worker_product_version "$runtime_root" "$expected_product_version"
wait_for_health "$base_url"
wait_for_worker_state "$runtime_root" "online"

python3 - "$base_url" "$token" <<'PY'
import json
import sys
import urllib.error
import urllib.request

base = sys.argv[1].rstrip("/")
token = sys.argv[2]
allowed = {"ready", "not_authenticated", "unavailable", "policy_blocked"}
providers = (
    ("codex", "/api/v1/providers/codex/status", "CODEX_READINESS"),
    ("claude_code", "/api/v1/providers/claude-code/status", "CLAUDE_CODE_READINESS"),
)


def get_json(path: str) -> object:
    request = urllib.request.Request(
        f"{base}{path}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status != 200:
                raise SystemExit(f"Coding Provider readiness HTTP {response.status}: {path}")
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise SystemExit(
            f"Coding Provider readiness 路由失败：{path} HTTP {error.code}"
        ) from error


for provider, path, marker in providers:
    payload = get_json(path)
    if not isinstance(payload, dict):
        raise SystemExit(f"Coding Provider readiness 返回无效：{path}")
    if payload.get("provider") != provider:
        raise SystemExit(f"Coding Provider readiness provider 不匹配：{path}")
    readiness = payload.get("readiness")
    if readiness not in allowed:
        raise SystemExit(f"Coding Provider readiness 状态无效：{provider}={readiness!r}")
    if payload.get("real_execution_default") is not False:
        raise SystemExit(f"Coding Provider 不得默认开启真实执行：{provider}")
    if payload.get("usage_machine_readable") is not False:
        raise SystemExit(f"Coding Provider 不得读取账号 Usage/余额：{provider}")
    if payload.get("execution_host") != "mac-worker":
        raise SystemExit(f"Coding Provider execution_host 不正确：{provider}")
    print(f"{marker}={readiness}")
PY

echo "PHASE23_CODING_PROVIDER_READINESS_CHECK=PASS"
echo "AUTHENTICATION_USER_ACTION_REQUIRED=true"
echo "CODING_PROVIDER_PROBE_NETWORK_TRIGGERED=false"
echo "CODING_PROVIDER_EXECUTION_TRIGGERED=false"
echo "PROVIDER_USAGE_OR_BALANCE_READ=false"
echo "PRODUCT_VERSION=$expected_product_version"
