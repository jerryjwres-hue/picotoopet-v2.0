"""Cross-device managed-ID -> Windows frame path contract. CPU-only, no GPU."""

from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy

import pytest

from scripts.windows.executor_bridge import Bridge, BridgeConfig, JobError


# 不使用私有狗狗素材：可重复的合成 PNG 用于验证本地字节摘要。
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
    "AAAAC0lEQVR42mP8/x8AAwMCAO+jRZcAAAAASUVORK5CYII="
)


def _hash(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _case(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    bridge = Bridge(
        BridgeConfig("http://127.0.0.1:8765", "managed-unit", root),
        session=None,
    )
    staged = bridge.state_dir / "staged_references"
    staged.mkdir()
    sha = hashlib.sha256(PNG).hexdigest()
    local = staged / f"{sha}.png"
    local.write_bytes(PNG)
    manifest = {
        "contract": "picotoo.frame-source-manifest.v1",
        "storypack_sha256": "a" * 64,
        "owner_subject_sha256": "b" * 64,
        "bindings": [
            {
                "shot_id": "S01", "role": "first",
                "asset_ref": "maotai_master_v1", "managed_sha256": sha,
            },
            {
                "shot_id": "S02", "role": "first",
                "asset_ref": "maotai_master_v1", "managed_sha256": sha,
            },
        ],
    }
    state = {
        "stem": "new_input",
        "task": {
            "task_id": "specific_S01_task",
            "task_type": "gen.keyframe",
            "attempt_count": 1,
            "timeout_seconds": 60,
            "payload": {
                "runner": "run_qwen_edit.py",
                "shot_id": "S01",
                "args": [],
                "jobs": {
                    "out": "$bridge.output",
                    "frame_source_manifest": manifest,
                    "source_bindings_sha256": _hash(manifest),
                    "jobs": [
                        {
                            "id": "S01_first",
                            "refs": ["maotai_master_v1"],
                            "prompt": "a synthetic static cartoon dog",
                            "seeds": [1],
                        },
                    ],
                },
            },
        },
    }
    return bridge, local, state


def _no_local_gpu(bridge):
    assert not list((bridge.queue / "inbox").glob("*.json"))
    assert not list(bridge.board.glob("jobs_*.json"))


def test_managed_frame_binds_exact_sha_and_removes_internal_manifest(tmp_path):
    bridge, local, state = _case(tmp_path)
    payload = bridge._jobs(state)
    assert payload["jobs"][0]["refs"] == [
        f"../_queue/executor_bridge/staged_references/{local.name}"
    ]
    assert "frame_source_manifest" not in payload
    assert "source_bindings_sha256" not in payload
    assert state["task"]["payload"]["jobs"]["jobs"][0]["refs"] == [
        "maotai_master_v1"
    ]
    _no_local_gpu(bridge)


@pytest.mark.parametrize("mutation,reason", [
    ("wrong_digest", "SHA"),
    ("missing_digest", "SHA"),
    ("other_shot", "镜头|绑定"),
    ("other_role", "role|首帧|镜头"),
    ("other_asset", "引用|清单"),
    ("duplicate_asset", "重复"),
    ("extra_source", "不完全一致"),
    ("missing_source", "清单|引用"),
])
def test_managed_frame_fail_closed_no_worker_write(tmp_path, mutation, reason):
    bridge, local, state = _case(tmp_path)
    jobs = state["task"]["payload"]["jobs"]
    manifest = jobs["frame_source_manifest"]
    entry = jobs["jobs"][0]
    if mutation == "wrong_digest":
        jobs["source_bindings_sha256"] = "f" * 64
    elif mutation == "missing_digest":
        jobs.pop("source_bindings_sha256")
    elif mutation == "other_shot":
        entry["id"] = "S02_first"
    elif mutation == "other_role":
        entry["id"] = "S01_last"
    elif mutation == "other_asset":
        entry["refs"] = ["undeclared_master_v1"]
    elif mutation == "duplicate_asset":
        entry["refs"].append("maotai_master_v1")
    elif mutation == "extra_source":
        manifest["bindings"].append({
            "shot_id": "S01", "role": "first", "asset_ref": "scene001",
            "managed_sha256": "a" * 64,
        })
    elif mutation == "missing_source":
        manifest["bindings"][0]["shot_id"] = "S03"
    if mutation not in ("wrong_digest", "missing_digest"):
        jobs["source_bindings_sha256"] = _hash(manifest)
    with pytest.raises(JobError, match=reason):
        bridge._work(state)
    _no_local_gpu(bridge)


def test_managed_frame_rechecks_actual_bytes_and_missing_file(tmp_path):
    bridge, local, state = _case(tmp_path)
    local.write_bytes(b"not the reviewed source bytes")
    with pytest.raises(JobError, match="SHA|图片格式"):
        bridge._work(state)
    _no_local_gpu(bridge)
    local.unlink()
    with pytest.raises(JobError, match="缺少"):
        bridge._work(state)
    _no_local_gpu(bridge)


def test_managed_frame_refuse_symlink_but_keep_legacy_task_contract(tmp_path):
    bridge, local, state = _case(tmp_path)
    outside = bridge.root / "other.png"
    outside.write_bytes(PNG)
    local.unlink()
    try:
        local.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("CI runner cannot create symlink")
    with pytest.raises(JobError, match="符号链接|目录"):
        bridge._jobs(state)
    _no_local_gpu(bridge)
    # 原有 legacy 任务没有受管理清单时不会强制猜测资产 ID。
    old = deepcopy(state)
    old["task"]["payload"]["jobs"].pop("frame_source_manifest")
    old["task"]["payload"]["jobs"].pop("source_bindings_sha256")
    old["task"]["payload"]["jobs"]["jobs"][0]["refs"] = ["old_local_frame.png"]
    assert bridge._jobs(old)["jobs"][0]["refs"] == ["old_local_frame.png"]


def test_self_consistent_manifest_is_only_data_not_gpu_authorization(tmp_path):
    bridge, _, state = _case(tmp_path)
    result = bridge._jobs(state)
    # 自校验的哈希不是 OWNER、MASTER 或冻结 Plan 的签名。
    # 本层只做本机数据映射，绝不能在 Core Owner HOLD 时使新任务获租约。
    assert "refs" in result["jobs"][0]
    _no_local_gpu(bridge)
