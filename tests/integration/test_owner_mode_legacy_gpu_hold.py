"""Native CPU-only checks: Owner mode cannot be bypassed via legacy GPU routes."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from picotoopet_core.api.app import create_app
from picotoopet_core.config.models import AppSettings
from picotoopet_core.config.paths import RuntimePaths
from picotoopet_core.domain.executor import ExecutorLease, GPU_TAG
from picotoopet_core.domain.models import TaskCreate
from picotoopet_core.security.owner_principal import (
    OwnerCredentialConfig,
    OwnerReviewRegistry,
    owner_token_fingerprint,
)

_API = "/api/v1"
_LEASE = {
    "worker_id": "existing-worker",
    "resource_tags": [GPU_TAG],
    "lease_seconds": 90,
}


def _episode() -> dict:
    # 合成的三镜头 StoryPack Episode 合同；仅用于入口拒绝测试，不执行 GPU。
    return {
        "episode_id": "MAOTAI_GATE_TEST",
        "title": "Synthetic three-shot episode",
        "target_seconds": 12.0,
        "characters": ["maotai_master_v1"],
        "shots": [
            {
                "shot_id": f"S{index:02}",
                "seconds": 4.0,
                "beat": "Walk toward dinner",
                "emotion": "curious",
                "camera": {"move": "tracking", "lens": 35.0, "speed": 1.0},
                "first_frame": {
                    "refs": ["maotai_master_v1"],
                    "prompt": "A synthetic unapproved reference",
                },
                "video": {
                    "prompt": "One continuous synthetic action",
                    "negative": "flicker",
                    "seeds": [index],
                },
                "audio": {"vocal_from": "none", "foley": []},
                "transition_out": {"type": "cut", "offset_s": 0.0},
            }
            for index in range(1, 4)
        ],
        "edit": {"fps": 24.0, "size": [832, 480], "loudness_lufs": -14.0},
    }


@pytest.fixture(params=["enabled", "disabled", "expired"])
def guarded(request, tmp_path):
    device = secrets.token_urlsafe(32)
    owner = secrets.token_urlsafe(32)
    status = request.param
    registry = OwnerReviewRegistry(credentials=(
        OwnerCredentialConfig(
            credential_id="gated-operator",
            actor_id="pet-owner",
            token_sha256=owner_token_fingerprint(owner),
            subject_keys=("pet:maotai",),
            permissions=("storypack.review", "asset_use.attest"),
            registry_revision=1,
            enabled=(status != "disabled"),
            expires_at=(
                datetime.now(UTC) - timedelta(minutes=1)
                if status == "expired" else datetime.now(UTC) + timedelta(hours=1)
            ),
        ),
    ))
    app = create_app(AppSettings(
        paths=RuntimePaths.from_root(tmp_path),
        api_token=device,
        owner_review_registry=registry,
    ))
    with TestClient(app, headers={"Authorization": f"Bearer {device}"}) as api:
        yield api


def _counts(client):
    db = client.app.state.services.database
    return {
        "episodes": db.scalar("SELECT COUNT(*) FROM production_episodes"),
        "tasks": db.scalar("SELECT COUNT(*) FROM tasks"),
        "approvals": db.scalar("SELECT COUNT(*) FROM approvals"),
    }


def _blocked(response):
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "STORYPACK_PRODUCTION_ADMISSION_REQUIRED"


def test_owner_mode_blocks_all_legacy_gpu_ingress_and_keeps_cpu_tasks(guarded):
    api = guarded
    before = _counts(api)
    preview = api.post(f"{_API}/episodes/budget/preview", json=_episode())
    assert preview.status_code == 200, preview.text
    assert preview.json()["read_only"] is True

    # 旧 Episode 创建和合成路径均不得通过设备 Bearer 直接发起生产。
    _blocked(api.post(f"{_API}/episodes", json=_episode()))
    _blocked(api.post(f"{_API}/episodes/MAOTAI_GATE_TEST/assemble"))

    # 不允许低层任务 API 绕开 Owner、MASTER、冻结 Plan 或 GPU HOLD。
    for task_type in ("gen.keyframe", "gen.video", "gen.foley", "qc.check", "edit.assemble"):
        _blocked(api.post(f"{_API}/tasks", json={
            "task_type": task_type,
            "payload": {"runner": "run_ltx_flf.py"},
            "resource_tag": GPU_TAG,
        }))
    _blocked(api.post(f"{_API}/tasks", json={
        "task_type": "analysis", "resource_tag": GPU_TAG,
    }))
    assert _counts(api) == before

    # 同一进程仍可创建普通 CPU 任务、查询状态以及取消任务。
    cpu = api.post(f"{_API}/tasks", json={"task_type": "analysis"})
    assert cpu.status_code == 201, cpu.text
    record_id = cpu.json()["task_id"]
    assert api.get(f"{_API}/tasks/{record_id}").status_code == 200
    assert api.post(f"{_API}/tasks/{record_id}/cancel").status_code == 200
    assert api.post(f"{_API}/tasks/{record_id}/retry").status_code == 200
    assert _counts(api)["episodes"] == 0
    assert _counts(api)["approvals"] == 0
    assert _counts(api)["tasks"] == 2


def test_owner_mode_denies_new_executor_lease_without_changing_queue(guarded):
    api = guarded
    before = _counts(api)
    assert api.post(f"{_API}/executors/lease", json=_LEASE).status_code == 204
    assert api.post(f"{_API}/executors/lease", json={
        **_LEASE, "resume_task_id": "not-present",
    }).status_code == 204
    assert _counts(api) == before


def test_existing_running_journal_can_resume_read_only_but_not_lease_next(guarded):
    api = guarded
    services = api.app.state.services

    # 种入一条既有运行中租约，以模拟新代码部署前 Windows 已有 Journal。
    # 不通过用户 HTTP 入队，不运行任何真实模型或 GPU。
    created = services.queue.create(TaskCreate(
        task_type="gen.keyframe",
        resource_tag=GPU_TAG,
        payload={
            "episode_id": "legacy-test",
            "shot_id": "S01",
            "runner": "run_qwen_edit.py",
            "jobs": {},
        },
    ))
    leased = services.executor.lease(ExecutorLease.model_validate(_LEASE), "preexisting")
    assert leased is not None and leased.task_id == created.task_id
    assert leased.attempt_count == 1
    counts = _counts(api)

    # 无 Resume ID 时绝不能发放新租约；仅同 Worker 的当前有效租约能恢复。
    assert api.post(f"{_API}/executors/lease", json=_LEASE).status_code == 204
    wrong_worker = {
        **_LEASE, "worker_id": "wrong-worker", "resume_task_id": created.task_id,
    }
    assert api.post(f"{_API}/executors/lease", json=wrong_worker).status_code == 204
    wrong_tag = {
        **_LEASE, "resource_tags": ["cpu-only"], "resume_task_id": created.task_id,
    }
    assert api.post(f"{_API}/executors/lease", json=wrong_tag).status_code == 204

    resumed = api.post(f"{_API}/executors/lease", json={
        **_LEASE, "resume_task_id": created.task_id,
    })
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["task_id"] == created.task_id
    assert resumed.json()["attempt_count"] == 1
    assert _counts(api) == counts

    # 已排队或租约过期的 Job 不能借 Journal 入口重开新 GPU POST。
    services.database.execute(
        "UPDATE tasks SET lease_expires_at = ? WHERE task_id = ?",
        ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), created.task_id),
    )
    expired = api.post(f"{_API}/executors/lease", json={
        **_LEASE, "resume_task_id": created.task_id,
    })
    assert expired.status_code == 204
    assert services.database.scalar(
        "SELECT attempt_count FROM tasks WHERE task_id = ?", (created.task_id,)
    ) == 1


def test_owner_mode_blocks_retries_of_existing_gpu_tasks(guarded):
    api = guarded
    services = api.app.state.services
    created = services.queue.create(TaskCreate(
        task_type="gen.video",
        resource_tag=GPU_TAG,
        payload={
            "episode_id": "legacy-test", "shot_id": "S01",
            "runner": "run_ltx_flf.py", "jobs": {},
        },
    ))
    cancelled = api.post(f"{_API}/tasks/{created.task_id}/cancel")
    assert cancelled.status_code == 200
    before = _counts(api)
    _blocked(api.post(f"{_API}/tasks/{created.task_id}/retry"))
    assert _counts(api) == before


def test_no_owner_registry_preserves_existing_legacy_contract(tmp_path):
    # 此隔离修复不改动旧版非 StoryPack 部署的默认 CPU/GPU 流程。
    token = secrets.token_urlsafe(32)
    app = create_app(AppSettings(
        paths=RuntimePaths.from_root(tmp_path), api_token=token,
    ))
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as api:
        response = api.post(f"{_API}/episodes", json=_episode())
        assert response.status_code == 201, response.text
        assert len(response.json()["tasks"]) == 9
        assert _counts(api)["episodes"] == 1
