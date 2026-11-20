"""Read-only first/last frame source contracts; never grant worker or GPU access.

A Mac managed asset ID and SHA are NOT Windows-local filesystem paths. This
preflight detects unsafe, unknown and cross-shot references before a later
trusted staging implementation can map their bytes to the worker sandbox.
"""

from __future__ import annotations

import hashlib
import json

from picotoopet_core.domain.episode import Episode
from picotoopet_core.domain.storypack import StoryPackV1, storypack_preview


def _digest(payload: dict) -> str:
    # 使用与 StoryPack 一致的确定性序列化；本摘要只用于后续对账。
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def inspect_frame_sources(
    pack: StoryPackV1,
    episode: Episode,
    owner_review_subject: dict,
) -> dict:
    """Check exact managed asset IDs per shot; refuse to infer a Windows mount."""
    source_sha = storypack_preview(pack)["storypack_sha256"]
    subject_sha = owner_review_subject.get("subject_sha256")
    content_bound = (
        isinstance(subject_sha, str)
        and len(subject_sha) == 64
        and isinstance(owner_review_subject.get("subject"), dict)
        and owner_review_subject["subject"].get("storypack_sha256") == source_sha
    )
    evidence = (
        owner_review_subject["subject"]["assets"]
        if content_bound else []
    )
    assets = {
        asset["ref"]: asset
        for asset in evidence
        if isinstance(asset, dict)
        and isinstance(asset.get("ref"), str)
        and isinstance(asset.get("sha256"), str)
    }
    reasons: list[str] = []
    if not content_bound:
        reasons.append("FRAME_MASTER_CONTENT_UNVERIFIED")

    bindings: list[dict] = []
    if len(pack.shots) != len(episode.shots):
        reasons.append("FRAME_SHOT_COUNT_MISMATCH")
    for shot, finished in zip(pack.shots, episode.shots, strict=False):
        if shot.id != finished.shot_id:
            reasons.append("FRAME_SHOT_ORDER_MISMATCH")
            continue
        # 与原 StoryPack 中逐镜演员、场景及风格锁定完全一致。
        allowed = {
            *([pack.character_ref] if shot.cast_refs is None else shot.cast_refs),
            shot.scene_ref or pack.scene_ref,
        }
        if pack.style_ref:
            allowed.add(pack.style_ref)

        for role, frame in (
            ("first", finished.first_frame),
            ("last", finished.last_frame),
        ):
            if frame is None:
                continue
            if role == "first" and not frame.refs:
                reasons.append(f"FRAME_REFS_REQUIRED:{shot.id}:{role}")
            if len(frame.refs) > 32:
                reasons.append(f"FRAME_REF_COUNT_EXCEEDED:{shot.id}:{role}")
                continue
            visited: set[str] = set()
            for ref in frame.refs:
                # 旧 Worker 把 refs 当 Windows 本地路径，绝不可把 LLM
                # 粘贴的相对/绝对路径当作已批准的 MASTER 资产。
                if any(char in ref for char in ("/", "\\", ":")) or ref in (".", ".."):
                    reasons.append(f"FRAME_PATH_NOT_A_MANAGED_ID:{shot.id}:{role}")
                    continue
                if ref in visited:
                    reasons.append(f"FRAME_DUPLICATE_REFERENCE:{shot.id}:{role}")
                    continue
                visited.add(ref)
                if ref not in allowed:
                    reasons.append(f"FRAME_REFERENCE_UNDECLARED_FOR_SHOT:{shot.id}:{role}")
                    continue
                asset = assets.get(ref)
                if not content_bound or asset is None:
                    reasons.append(f"FRAME_MANAGED_ASSET_UNVERIFIED:{shot.id}:{role}")
                    continue
                bindings.append({
                    "shot_id": shot.id,
                    "role": role,
                    "asset_ref": ref,
                    "managed_sha256": asset["sha256"],
                })

    manifest = {
        "contract": "picotoo.frame-source-manifest.v1",
        "storypack_sha256": source_sha,
        "owner_subject_sha256": subject_sha if content_bound else None,
        "bindings": bindings,
    }
    manifest_sha = _digest(manifest) if not reasons else None

    # 即使 Mac 内容均对得上，Windows 本机仍未做同哈希文件暂存。
    # 不生成可被 Worker 误认为是路径的字段或授权令牌。
    return {
        "contract": manifest["contract"],
        "status": (
            "MAC_CONTENT_BOUND_WORKER_STAGING_REQUIRED"
            if manifest_sha is not None else "FRAME_REFERENCE_BLOCKED"
        ),
        "storypack_sha256": source_sha,
        "owner_subject_sha256": subject_sha if content_bound else None,
        "source_bindings_sha256": manifest_sha,
        # 与 Mac ZIP 的 manifest.json 完全相同的规范化内容，供冻结 Plan 绑定。
        # 注意：返回清单不代表可排队；当前仍需独立 MASTER/Owner/GPU 放行。
        "frame_source_manifest": manifest if manifest_sha is not None else None,
        "bindings": bindings,
        "mac_managed_content_verified": manifest_sha is not None,
        "worker_local_bytes_verified": False,
        "worker_reference_paths_resolved": False,
        "blocking_reasons": list(dict.fromkeys([
            *reasons, "FRAME_WORKER_STAGING_AND_HASH_REQUIRED",
        ])),
        "read_only": True,
        "can_queue": False,
        "gpu_authorized": False,
    }
