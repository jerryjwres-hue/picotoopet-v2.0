"""CPU-only Worker dispatch tests: staged bytes and old Journal cannot bypass HOLD."""

from __future__ import annotations

import base64
import hashlib
import json
from unittest.mock import Mock

import pytest
from requests import Response

from scripts.windows.executor_bridge import Bridge, BridgeConfig, JobError


# 完全合成的 1×1 PNG；不访问真实茅台素材、视频模型或 ComfyUI。
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
    "AAAAC0lEQVR42mP8/x8AAwMCAO+jRZcAAAAASUVORK5CYII="
)


def _staged(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    bridge = Bridge(BridgeConfig("http://127.0.0.1:8765", "unit", root), Mock())
    stage = bridge.state_dir / "staged_references"
    stage.mkdir()
    digest = hashlib.sha256(PNG).hexdigest()
    image = stage / f"{digest}.png"
    image.write_bytes(PNG)
    ref = f"../_queue/executor_bridge/staged_references/{image.name}"
    state = {
        "stem": "staged_1",
        "task": {
            "task_id": "staged_task_1",
            "task_type": "gen.keyframe",
            "timeout_seconds": 60,
            "payload": {
                "runner": "run_qwen_edit.py",
                "shot_id": "S01",
                "args": [],
                "jobs": {
                    "out": "$bridge.output",
                    "jobs": [{"id": "S01_first", "refs": [ref], "prompt": "test"}],
                },
            },
        },
    }
    return bridge, image, ref, state


def test_staged_frame_rehashed_on_each_worker_dispatch(tmp_path):
    bridge, image, ref, state = _staged(tmp_path)
    assert bridge._jobs(state)["jobs"][0]["refs"] == [ref]
    image.write_bytes(b"tampered after Windows staging")
    with pytest.raises(JobError, match="SHA|图片格式"):
        bridge._jobs(state)
    assert not list((bridge.queue / "inbox").iterdir())


def test_staged_frame_wrong_name_is_not_trusted(tmp_path):
    bridge, image, _, state = _staged(tmp_path)
    new_name = image.with_name("unverified.png")
    image.rename(new_name)
    state["task"]["payload"]["jobs"]["jobs"][0]["refs"] = [
        f"../_queue/executor_bridge/staged_references/{new_name.name}"
    ]
    with pytest.raises(JobError, match="SHA-256"):
        bridge._jobs(state)
    assert not list((bridge.queue / "inbox").iterdir())


def test_nested_path_inside_staged_reference_dir_cannot_bypass_hash(tmp_path):
    bridge, image, _, state = _staged(tmp_path)
    nested = image.parent / "untrusted-subfolder"
    nested.mkdir()
    nested_file = nested / "unverified.png"
    nested_file.write_bytes(PNG)
    state["task"]["payload"]["jobs"]["jobs"][0]["refs"] = [
        f"../_queue/executor_bridge/staged_references/{nested.name}/{nested_file.name}"
    ]
    with pytest.raises(JobError, match="符号链接|SHA-256"):
        bridge._jobs(state)
    assert not list((bridge.queue / "inbox").glob("*.json"))


def test_staged_frame_symlink_never_used_for_gpu(tmp_path):
    bridge, image, ref, state = _staged(tmp_path)
    other = bridge.root / "outside.png"
    other.write_bytes(PNG)
    image.unlink()
    try:
        image.symlink_to(other)
    except (OSError, NotImplementedError):
        pytest.skip("CI runner cannot create test symlink")
    with pytest.raises(JobError, match="符号链接"):
        bridge._jobs(state)
    assert not list((bridge.queue / "inbox").iterdir())


def test_staged_bytes_unchanged_legacy_references_still_work(tmp_path):
    bridge, _, _, state = _staged(tmp_path)
    legacy = bridge.board / "traditional-frame.png"
    legacy.write_bytes(b"older locally managed picture")
    state["task"]["payload"]["jobs"]["jobs"][0]["refs"] = [legacy.name]
    assert bridge._jobs(state)["jobs"][0]["refs"] == [legacy.name]


def test_no_worker_inbox_when_staged_frame_is_tampered(tmp_path):
    bridge, image, _, state = _staged(tmp_path)
    image.write_bytes(b"corrupted on disk")
    with pytest.raises(JobError, match="SHA|图片格式"):
        bridge._work(state)
    assert not list((bridge.queue / "inbox").glob("*.json"))
    assert not list(bridge.board.glob("jobs_*.json"))


def test_owner_hold_heartbeat_reject_then_resume_204_keeps_journal_without_post(tmp_path):
    root = tmp_path / "worker"
    root.mkdir()
    requests_seen = []

    class HoldSession:
        def request(self, method, url, **kwargs):
            requests_seen.append((method, url))
            response = Response()
            response.url = url
            if url.endswith("/heartbeat"):
                response.status_code = 409
                response._content = json.dumps({
                    "error": {"code": "STORYPACK_PRODUCTION_ADMISSION_REQUIRED"},
                }).encode("utf-8")
            elif url.endswith("/executors/lease"):
                response.status_code = 204
                response._content = b""
            elif url.endswith("/tasks/old_task"):
                response.status_code = 200
                response._content = b'{"status":"Running"}'
            else:
                raise AssertionError("Unexpected HTTP while Owner HOLD active")
            return response

    bridge = Bridge(
        BridgeConfig("http://127.0.0.1:8765", "old-worker", root),
        HoldSession(),
    )
    task = {
        "task_id": "old_task",
        "task_type": "gen.video",
        "attempt_count": 1,
        "timeout_seconds": 60,
        "payload": {
            "runner": "run_ltx_flf.py", "shot_id": "S01",
            "args": [], "jobs": {"jobs": [{"id": "S01", "prompt": "held"}]},
        },
    }
    # 历史租约已经 RUNNING，但没有任何本地 submitted 凭据。
    bridge._new_state(task)
    bridge.step()
    assert bridge.journal.exists()
    assert not list((bridge.queue / "inbox").glob("*.json"))
    assert not list(bridge.board.glob("jobs_*.json"))
    assert [url.rsplit("/", 1)[-1] for _, url in requests_seen] == [
        "heartbeat", "lease", "old_task",
    ]
