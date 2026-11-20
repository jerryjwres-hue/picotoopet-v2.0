"""Real CPU-only Mac→Windows frame payload stage, with no network or GPU writes."""

from __future__ import annotations

import base64
import hashlib
import json
import warnings
import zipfile
from pathlib import Path

import pytest

from picotoopet_core.domain.episode import Episode
from picotoopet_core.domain.storypack import StoryPackV1, storypack_preview
from picotoopet_core.domain.storypack_episode_candidate import (
    complete_storypack_episode_preview,
)
from picotoopet_core.domain.storypack_frame_bundle import (
    FrameBundleError,
    export_frame_bundle,
)
from picotoopet_core.domain.storypack_frame_sources import inspect_frame_sources
from picotoopet_core.domain.storypack_owner_subject import build_owner_review_subject
from scripts.windows.stage_frame_bundle import FrameStageError, stage_frame_bundle

# 合成像素，无真实宠物素材、许可证、用户路径或 GPU 请求。
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
    "AAAAC0lEQVR42mP8/x8AAwMCAO+jRZcAAAAASUVORK5CYII="
)


@pytest.fixture
def staging(tmp_path):
    objects = tmp_path / "mac-managed" / "objects"
    windows = tmp_path / "windows-project"
    objects.mkdir(parents=True)
    windows.mkdir()
    pack = StoryPackV1.model_validate({
        "schema": "picotoo.storypack.v1",
        "episode_id": "MAOTAI_STAGING",
        "title": "Test dinner",
        "output_profile": "p0_landscape",
        "character_ref": "maotai_master_v1",
        "scene_ref": "yard_v1",
        "style_ref": "toon_v1",
        "story": {"goal": "Find dinner", "payoff": "Run home"},
        "shots": [{
            "id": "S01", "action": "Turn toward the dinner bell",
            "state_in": "Dog in yard", "state_out": "Dog at door",
            "because": "The owner calls",
        }],
    })
    refs = ("maotai_master_v1", "yard_v1", "toon_v1")
    checks = []
    hashes = {}
    for i, ref in enumerate(refs):
        # 生成不同的合成 PNG 字节以验证每个 ID 的独立 SHA。
        payload = _PNG + bytes([i])
        sha = hashlib.sha256(payload).hexdigest()
        hashes[ref] = sha
        folder = objects / sha[:2]
        folder.mkdir(exist_ok=True)
        (folder / sha[2:]).write_bytes(payload)
        checks.append({
            "ref": ref, "recorded_sha256": sha, "sha256_recorded": True,
            "managed_object_integrity": "CONTENT_VERIFIED_UNAPPROVED",
            "content_integrity_verified": True, "physical_file_verified": True,
            "artifact_type": "image",
        })

    sha = storypack_preview(pack)["storypack_sha256"]
    subject = build_owner_review_subject(pack, sha, checks)
    completion = {
        "edit": {"loudness_lufs": -14.0},
        "shots": [{
            "shot_id": "S01",
            "emotion": "curious",
            "camera": {"move": "locked-off", "lens": 35.0, "speed": 1.0},
            "first_frame": {
                "refs": ["maotai_master_v1", "yard_v1", "toon_v1"],
                "prompt": "Synthetic character and yard",
            },
            "video": {
                "prompt": "One camera move", "negative": "drift",
                "seeds": [123],
            },
            "audio": {"vocal_from": "none", "foley": []},
            "transition_out": {"type": "cut", "offset_s": 0.0},
        }],
    }
    candidate = complete_storypack_episode_preview(pack, sha, completion)
    episode = Episode.model_validate(candidate["episode"])
    preview = inspect_frame_sources(pack, episode, subject)
    assert preview["mac_managed_content_verified"] is True
    return objects, windows, hashes, preview, tmp_path / "bundle.zip"


def test_full_cpu_only_export_import_into_existing_worker_sandbox(staging):
    objects, windows, hashes, preview, bundle_path = staging

    exported = export_frame_bundle(objects, preview, bundle_path)
    assert exported["status"] == "SOURCE_BUNDLE_EXPORTED_NO_GPU_AUTHORITY"
    assert exported["object_count"] == 3
    assert exported["can_queue"] is False

    imported = stage_frame_bundle(
        bundle_path,
        expected_source_bindings_sha256=preview["source_bindings_sha256"],
        worker_root=windows,
    )
    assert imported["worker_local_bytes_verified"] is True
    assert imported["source_bindings_sha256"] == preview["source_bindings_sha256"]
    assert imported["can_queue"] is False
    assert imported["gpu_authorized"] is False
    assert len(imported["bindings"]) == 3
    assert set(imported["worker_ref_paths_by_digest"]) == set(hashes.values())
    # Worker 正常启动时会创建静态首帧板；这里使用相同的项目布局。
    board = windows / "17_静态首帧板V2"
    board.mkdir()
    for digest, ref in imported["worker_ref_paths_by_digest"].items():
        # 返回的相对路径与现有 Worker Bridge.board 的 _safe_path 兼容。
        from_board = board / ref
        assert from_board.resolve().is_relative_to(windows.resolve())
        assert hashlib.sha256(from_board.read_bytes()).hexdigest() == digest

    # 同一来源重复导入，应复用完全相同的内容寻址文件。
    repeated = stage_frame_bundle(
        bundle_path,
        expected_source_bindings_sha256=preview["source_bindings_sha256"],
        worker_root=windows,
    )
    assert imported == repeated


def test_export_rejects_changed_or_symlinked_mac_source(staging):
    objects, _, hashes, preview, bundle = staging
    digest = hashes["maotai_master_v1"]
    path = objects / digest[:2] / digest[2:]
    path.write_bytes(b"changed after story approval")
    with pytest.raises(FrameBundleError, match="FRAME_BUNDLE_SOURCE_CHANGED"):
        export_frame_bundle(objects, preview, bundle)
    assert not bundle.exists()

    original = _PNG + b"\0"
    path.write_bytes(original)
    outside = objects.parent / "different.png"
    outside.write_bytes(original)
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(FrameBundleError, match="FRAME_BUNDLE_SOURCE_SYMLINK"):
        export_frame_bundle(objects, preview, bundle)
    assert not bundle.exists()


def test_worker_rejects_wrong_expected_plan_hash_before_writing(staging):
    objects, windows, _, preview, bundle = staging
    export_frame_bundle(objects, preview, bundle)
    with pytest.raises(FrameStageError, match="FRAME_STAGE_EXPECTED_SOURCE_SHA_MISMATCH"):
        stage_frame_bundle(
            bundle, expected_source_bindings_sha256="a" * 64,
            worker_root=windows,
        )
    assert not (windows / "_queue").exists()


def test_worker_rejects_modified_zip_object_and_extra_path(staging):
    objects, windows, hashes, preview, bundle = staging
    export_frame_bundle(objects, preview, bundle)
    original = tmp = bundle.parent / "original.zip"
    bundle.replace(tmp)
    modified = next(iter(hashes.values()))
    with zipfile.ZipFile(tmp) as original_archive, zipfile.ZipFile(
        bundle, "w", compression=zipfile.ZIP_STORED,
    ) as tampered:
        for name in original_archive.namelist():
            data = original_archive.read(name)
            tampered.writestr(
                name, b"spoofed" if name == f"objects/{modified}" else data
            )
        tampered.writestr("../../unsafe.txt", b"not allowed")
    with pytest.raises(FrameStageError, match="FRAME_STAGE_ARCHIVE_CONTENTS_UNEXPECTED"):
        stage_frame_bundle(
            bundle,
            expected_source_bindings_sha256=preview["source_bindings_sha256"],
            worker_root=windows,
        )
    assert not (windows / "_queue").exists()

    # 即使删除多余文件，只修改内容也必须触发 SHA 不匹配。
    with zipfile.ZipFile(tmp) as original_archive, zipfile.ZipFile(
        bundle, "w", compression=zipfile.ZIP_STORED,
    ) as tampered:
        for name in original_archive.namelist():
            data = original_archive.read(name)
            tampered.writestr(
                name, b"spoofed" if name == f"objects/{modified}" else data
            )
    with pytest.raises(FrameStageError, match="FRAME_STAGE_OBJECT_SHA_MISMATCH"):
        stage_frame_bundle(
            bundle,
            expected_source_bindings_sha256=preview["source_bindings_sha256"],
            worker_root=windows,
        )


def test_worker_rejects_preexisting_corrupted_staging_file(staging):
    objects, windows, hashes, preview, bundle = staging
    export_frame_bundle(objects, preview, bundle)
    digest = hashes["maotai_master_v1"]
    folder = windows / "_queue" / "executor_bridge" / "staged_references"
    folder.mkdir(parents=True)
    path = folder / f"{digest}.png"
    path.write_bytes(b"not the expected hash")
    with pytest.raises(FrameStageError, match="FRAME_STAGE_EXISTING_SHA_MISMATCH"):
        stage_frame_bundle(
            bundle,
            expected_source_bindings_sha256=preview["source_bindings_sha256"],
            worker_root=windows,
        )
    assert path.read_bytes() == b"not the expected hash"


def test_worker_rejects_symlinked_staging_directory(staging):
    objects, windows, _, preview, bundle = staging
    export_frame_bundle(objects, preview, bundle)
    try:
        (windows / "_queue").symlink_to(objects, target_is_directory=True)
    except OSError:
        # 个别 Windows Runner 未授予创建链接特权；Mac 用例仍覆盖此拒绝路径。
        pytest.skip("CI runner cannot create directory symlinks")
    with pytest.raises(FrameStageError, match="FRAME_STAGE_STAGING_SYMLINK"):
        stage_frame_bundle(
            bundle,
            expected_source_bindings_sha256=preview["source_bindings_sha256"],
            worker_root=windows,
        )


def test_source_bundle_rejects_modified_authority_fields(staging):
    objects, _, _, preview, bundle = staging
    forged = dict(preview)
    forged["owner_subject_sha256"] = "f" * 64
    with pytest.raises(FrameBundleError, match="FRAME_BUNDLE_MANIFEST_CHANGED"):
        export_frame_bundle(objects, forged, bundle)
    assert not bundle.exists()
