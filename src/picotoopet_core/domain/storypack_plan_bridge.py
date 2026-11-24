"""P0-2 read-only bridge: validated StoryPack -> immutable NON-EXECUTABLE plan proposal.

A StoryPack is not a signed Creative Package. Character/scene assets are not
per-shot first frames. No source here can create an executable ProductionPlan,
queue a worker, or approve GPU use. This projection is a reviewed next-step
contract for wiring the existing production compiler, not a second scheduler.
"""

from __future__ import annotations

import hashlib
import json
import re

from picotoopet_core.domain.storypack import (
    OUTPUT_PROFILES, StoryPackV1,
)
from picotoopet_core.domain.storypack_asset_registry import (
    is_core_artifact_id, storypack_expected_kinds,
)
from picotoopet_core.production.profile import frame_count_for_duration

_SHA = re.compile(r"^[0-9a-f]{64}$")
_BRIDGE_SCHEMA = "picotoo.storypack.production-bridge-proposal.v1"
_BRIDGE_VERSION = "storypack-bridge-preview-v1"


def _digest(data: object) -> str:
    """Hash the exact deterministic JSON representation of the proposal."""
    return hashlib.sha256(json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def build_storypack_bridge_proposal(
    pack: StoryPackV1,
    storypack_sha256: str,
    checks: list[dict],
) -> dict:
    """Bind checked asset IDs and preserve all StoryPack story/continuity facts.

    This is intentionally *not* ProductionPlan: that model requires the
    frozen approved Creative Package identity and trusted first-frame
    image(s), neither of which is established by the StoryPack import.
    """
    if _SHA.fullmatch(storypack_sha256) is None:
        raise ValueError("STORYPACK_BRIDGE_SOURCE_DIGEST_INVALID")

    # 01. Reject incomplete or ambiguous input checks; repeated refs must
    #     never silently override each other in a dict comprehension.
    by_ref: dict[str, dict] = {}
    for entry in checks:
        ref = entry.get("ref")
        if not isinstance(ref, str) or ref in by_ref:
            raise ValueError("STORYPACK_BRIDGE_ASSET_CHECKS_AMBIGUOUS")
        by_ref[ref] = entry

    expected_kinds = storypack_expected_kinds(pack)
    refs = tuple(sorted(expected_kinds))
    if set(by_ref) != set(refs):
        raise ValueError("STORYPACK_BRIDGE_ASSET_CHECKS_INCOMPLETE")

    # 02. Keep the 11-21 StoryPack's original profile, even when
    #     FLUX/LTX history is portrait. Never silently rewrite the source.
    width, height, fps, seconds = OUTPUT_PROFILES[pack.output_profile]
    frames_per_shot = frame_count_for_duration(seconds, fps)
    blockers: set[str] = set()
    asset_snapshots: list[dict] = []
    for ref in refs:
        check = by_ref[ref]
        expected = expected_kinds[ref]
        actual_kind = check.get("asset_kind")
        digest = check.get("recorded_sha256")
        approved = check.get("owner_approval_verified") is True
        core_verified = check.get("content_integrity_verified") is True
        provenance = check.get("byte_provenance")
        present = check.get("registry_record_status") != "RECORD_NOT_FOUND"
        canonical = is_core_artifact_id(ref)
        matches = (
            check.get("kind_check") == "KIND_MATCHES_SLOT"
            and actual_kind == expected
        )
        if not canonical:
            blockers.add("STORYPACK_REF_NOT_CANONICAL_CORE_ID")
        if not present:
            blockers.add("STORYPACK_ASSET_RECORD_NOT_FOUND")
        if not matches:
            blockers.add("STORYPACK_ASSET_KIND_MISMATCH")
        if not isinstance(digest, str) or _SHA.fullmatch(digest) is None:
            blockers.add("STORYPACK_ASSET_FULL_SHA_MISSING")
        if not approved:
            blockers.add("STORYPACK_ASSET_OWNER_APPROVAL_MISSING")
        if provenance == "CORE_HASHED_MANAGED_COPY" and not core_verified:
            blockers.add("STORYPACK_CORE_COPY_BYTES_NOT_VERIFIED")
        if provenance not in (
            "CORE_HASHED_MANAGED_COPY",
            "WINDOWS_CLIENT_CLAIM_NOT_CORE_HASHED",
        ):
            blockers.add("STORYPACK_ASSET_PROVENANCE_NOT_TRUSTED")
        # The Windows-only LoRA claim still needs a Windows byte check at
        # execution; Owner approval of metadata cannot replace that.
        asset_snapshots.append({
            "artifact_id": ref if canonical and present else None,
            "source_ref": ref,
            "expected_kind": expected,
            "recorded_kind": actual_kind,
            "sha256": digest if isinstance(digest, str) and _SHA.fullmatch(digest) else None,
            "byte_provenance": provenance,
            "core_verified_bytes": core_verified,
            "owner_approved": approved,
            "requires_windows_byte_check": True,
            "identity_rights_certified": False,
        })

    if pack.dynamic_motion is not None:
        blockers.add("STORYPACK_DYNAMIC_MOTION_REQUIRES_SEPARATE_OWNER_REVIEW")
    if len(pack.shots) != 3:
        blockers.add("STORYPACK_P0_THREE_SHOTS_REQUIRED")

    # 03. A character reference is not itself a rendered I2V first frame.
    #     Never set trusted_input_asset_ref from character_master here.
    shots: list[dict] = []
    for order, shot in enumerate(pack.shots, start=1):
        cast = [pack.character_ref] if shot.cast_refs is None else list(shot.cast_refs)
        if not cast:
            blockers.add("STORYPACK_P0_PET_IN_EVERY_SHOT_REQUIRED")
        shot_scene = shot.scene_ref or pack.scene_ref
        shots.append({
            "shot_id": shot.id,
            "order": order,
            "action": shot.action,
            "because": shot.because,
            "state_in": shot.state_in,
            "state_out": shot.state_out,
            "depends_on": list(shot.depends_on),
            "handoff": shot.handoff,
            "character_artifact_ids": cast,
            "scene_artifact_id": shot_scene,
            "style_artifact_id": pack.style_ref,
            "render_intent_proposed": "IMAGE_TO_VIDEO" if cast else "GENERATIVE_VIDEO",
            "trusted_first_frame_artifact_id": None,
            "execution_disposition": "NEEDS_HUMAN",
            "width": width,
            "height": height,
            "fps": fps,
            "frame_count": frames_per_shot,
            "target_duration_ms": seconds * 1000,
        })

    # 04. Explicit obligations remain even if all named assets are approved:
    #     per-shot first frames, formal package authority, compatible
    #     renderer and Owner review cannot be inferred from registry rows.
    blockers.update({
        "STORYPACK_FROZEN_CREATIVE_PACKAGE_NOT_ESTABLISHED",
        "STORYPACK_PER_SHOT_FIRST_FRAMES_NOT_BOUND",
        "STORYPACK_OWNER_EPISODE_REVIEW_NOT_ESTABLISHED",
        "STORYPACK_RENDERER_ADAPTER_NOT_VALIDATED",
    })

    # 05. Fingerprint the story and asset *snapshot*, including current
    #     approval state. Any edit or approval change alters the proposal
    #     identity, so it cannot silently reuse a stale review.
    frozen_content = {
        "schema": _BRIDGE_SCHEMA,
        "bridge_version": _BRIDGE_VERSION,
        "source_schema": pack.schema,
        "source_storypack_sha256": storypack_sha256,
        "episode_id": pack.episode_id,
        "title": pack.title,
        "output_profile": pack.output_profile,
        "output": {"width": width, "height": height, "fps": fps,
                   "frames_per_shot": frames_per_shot},
        "story": pack.story.model_dump(mode="json"),
        "assets": asset_snapshots,
        "shots": shots,
    }
    return {
        **frozen_content,
        "proposal_sha256": _digest(frozen_content),
        "bridge_status": "NEEDS_HUMAN",
        "blocking_reasons": sorted(blockers),
        "source_storypack_rewritten": False,
        "production_plan_created": False,
        "production_plan_executable": False,
        "creative_package_approved": False,
        "owner_episode_approved": False,
        "worker_admitted": False,
        "gpu_post_authorized": False,
        "can_queue": False,
        "next_step": "VERIFY_ASSETS_AND_FIRST_FRAMES_BEFORE_PRODUCTION_COMPILATION",
    }
