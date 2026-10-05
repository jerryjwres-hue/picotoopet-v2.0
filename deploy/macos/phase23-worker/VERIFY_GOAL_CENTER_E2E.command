#!/bin/bash
# 严格验证 Goal Center 自动链在当前 Mac 实机上已真正就绪；不创建 Goal、不访问外网。
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
  echo "Goal Center 验收失败：Mac Worker Manifest 产品版本不一致。" >&2
  exit 1
fi

port="$(read_existing_port "$runtime_root")"
token="$(read_api_token)"
base_url="http://127.0.0.1:$port"
state_path="$runtime_root/state/worker-status.json"

verify_worker_product_version "$runtime_root" "$expected_product_version"
wait_for_health "$base_url"
wait_for_worker_state "$runtime_root" "online"

# 动态能力只有在真实依赖健康后才进入 supported_task_types：
# discovery = Research Gateway readiness + 本地 Scout；synthesis = 本地模型；handoff = 本地确定性打包。
python3 - "$state_path" <<'PY'
import json
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
required = {
    "autonomous.discovery.v1",
    "autonomous.goal_synthesis.v1",
    "autonomous.goal_handoff.v1",
}
last_payload: dict[str, object] = {}
for _ in range(90):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        time.sleep(1)
        continue
    last_payload = payload if isinstance(payload, dict) else {}
    supported = last_payload.get("supported_task_types")
    if (
        last_payload.get("state") == "online"
        and last_payload.get("available") is True
        and isinstance(supported, list)
        and required <= set(supported)
    ):
        break
    time.sleep(1)
else:
    supported = last_payload.get("supported_task_types")
    present = set(supported) if isinstance(supported, list) else set()
    missing = sorted(required - present)
    raise SystemExit(
        "Goal Center 自动链尚未就绪；缺少动态任务类型："
        f"{missing!r}。请检查本地模型与 Research Gateway 健康状态。"
    )
PY

# 只检查 loopback Core 的真实 API 合同与模板；不提交测试 Goal，因此不会触发搜索或消耗外部额度。
python3 - "$base_url" "$token" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
token = sys.argv[2]


def get_json(path: str, *, authenticated: bool) -> object:
    headers = {"Authorization": f"Bearer {token}"} if authenticated else {}
    request = urllib.request.Request(f"{base}{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


openapi = get_json("/openapi.json", authenticated=False)
if not isinstance(openapi, dict):
    raise SystemExit("Goal Center OpenAPI 返回无效。")
paths = openapi.get("paths")
if not isinstance(paths, dict):
    raise SystemExit("Goal Center OpenAPI 缺少 paths。")
required_paths = {
    "/api/v1/autonomous/goals/templates",
    "/api/v1/autonomous/goals",
    "/api/v1/autonomous/goals/{goal_id}",
    "/api/v1/autonomous/goals/{goal_id}/handoff",
    "/api/v1/autonomous/goals/{goal_id}/handoff/download",
    "/api/v1/autonomous/goals/{goal_id}/handoff/prompt",
}
missing_paths = sorted(required_paths - set(paths))
if missing_paths:
    raise SystemExit(f"Goal Center API 路由缺失：{missing_paths!r}")

templates = get_json("/api/v1/autonomous/goals/templates", authenticated=True)
if not isinstance(templates, list):
    raise SystemExit("Goal Center 模板返回无效。")
required_goal_types = {
    "product.research",
    "consumer.pain_points",
    "business.opportunity",
    "video.creative",
    "product.research_to_video",
}
present_goal_types = {
    item.get("goal_type")
    for item in templates
    if isinstance(item, dict) and isinstance(item.get("goal_type"), str)
}
missing_goal_types = sorted(required_goal_types - present_goal_types)
if missing_goal_types:
    raise SystemExit(f"Goal Center 模板类型缺失：{missing_goal_types!r}")
PY

echo "PHASE23_GOAL_CENTER_E2E_READY=PASS"
echo "PRODUCT_VERSION=$expected_product_version"
echo "READY_CHAIN=GoalCenter->MacCore->MacWorker->ResearchGateway->LocalAnalysis->Handoff"
echo "NETWORK_RESEARCH_TRIGGERED=false"
echo "TEST_GOAL_CREATED=false"
