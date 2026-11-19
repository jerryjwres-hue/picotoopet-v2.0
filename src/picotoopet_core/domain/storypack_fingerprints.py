"""Deterministic, non-authorizing StoryPack fingerprints for selective rechecks.

These SHA-256 identifiers describe inputs and dependency changes. They are NOT
proof of verified provenance, GPU admission, QC approval or a cache hit.
"""

from __future__ import annotations

import hashlib
import json

from picotoopet_core.domain.storypack import StoryPackV1


def _digest(value: object) -> str:
    # 统一哈希规范，确保 Windows/Mac、JSON/YAML 的同义结构不会产生不同 Key。
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_shot_fingerprints(
    pack: StoryPackV1,
    storypack_sha256: str,
    checks: list[dict],
) -> dict:
    """Propose stable shot-level input identities without accepting work for execution."""
    recorded = {row["ref"]: row for row in checks}
    asset_snapshot = {}
    for ref in sorted(recorded):
        row = recorded[ref]
        asset_snapshot[ref] = {
            "sha256": row.get("recorded_sha256"),
            "integrity": row.get("managed_object_integrity"),
            "content_integrity_verified": row.get("content_integrity_verified") is True,
        }

    shot_keys: dict[str, str] = {}
    shots = []
    for shot in pack.shots:
        cast = [pack.character_ref] if shot.cast_refs is None else shot.cast_refs
        scene = shot.scene_ref or pack.scene_ref
        refs = list(dict.fromkeys([
            *cast, scene, *([pack.style_ref] if pack.style_ref else []),
        ]))
        inputs = {
            "schema": "picotoo.shot-fingerprint.v1",
            "output_profile": pack.output_profile,
            "shot_id": shot.id,
            "state_in": shot.state_in,
            "action": shot.action,
            "state_out": shot.state_out,
            "because": shot.because,
            "scene_ref": scene,
            "cast_refs": cast,
            "style_ref": pack.style_ref,
            "handoff": shot.handoff,
            # 仅加入该镜头真实引用的素材，避免无关场景修改导致全部重算。
            "assets": {ref: asset_snapshot.get(ref) for ref in refs},
            "upstream_keys": [shot_keys[ref.casefold()] for ref in shot.depends_on],
        }
        fingerprint = _digest(inputs)
        shot_keys[shot.id.casefold()] = fingerprint
        shots.append({
            "shot_id": shot.id,
            "input_sha256": fingerprint,
            "depends_on": shot.depends_on,
            "input_assets": refs,
            "all_managed_bytes_verified": all(
                asset_snapshot.get(ref, {}).get("content_integrity_verified") is True
                for ref in refs
            ),
            # 本模块不能做可信 Owner 或 QC 决策，因此绝不直接授权复用/生成。
            "reusable_without_authority": False,
        })

    return {
        "schema": "picotoo.fingerprint-plan.v1",
        "storypack_sha256": storypack_sha256,
        "asset_snapshot_sha256": _digest(asset_snapshot),
        "story_review_sha256": _digest({
            "storypack": storypack_sha256,
            "asset_snapshot": asset_snapshot,
        }),
        "shots": shots,
        "can_reuse_for_generation": False,
        "can_queue": False,
        "note": "ADVISORY_IDENTITIES_ONLY_NOT_OWNER_OR_QC_APPROVAL",
    }
