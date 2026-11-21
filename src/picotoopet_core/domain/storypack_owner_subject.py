"""Fail-closed review subject for dynamic StoryPacks; never grants Owner authority.

This is an advisory, reproducible digest of story, verified managed bytes,
declared asset roles and proposed permissions. A future authenticated Owner
decision MUST recheck this digest and the underlying managed object bytes.
"""

from __future__ import annotations

import hashlib
import json
import re

from picotoopet_core.domain.storypack import StoryPackV1

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA = "picotoo.owner-review-subject.v1"
_PROPOSED_PERMISSIONS = [
    "use_bound_character_scene_style_assets",
    "approve_dynamic_storyboard",
    "compile_executable_episode",
    "request_gpu_generation",
]
_PENDING_GATES = [
    "OWNER_PRINCIPAL_AUTHENTICATED",
    "ASSET_RIGHTS_AND_MASTER_APPROVED",
    "DYNAMIC_STORY_POLICY_COMPATIBLE",
    "PRODUCTION_PARAMETERS_VALIDATED",
    "GPU_HOLD_SEPARATELY_RELEASED",
]


def _sha256_json(payload: dict) -> str:
    """Hash canonical, versioned JSON independent of YAML/JSON input encoding."""
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_owner_review_subject(
    pack: StoryPackV1,
    storypack_sha256: str,
    asset_checks: list[dict],
) -> dict:
    """Prepare a proposed review subject only if all managed asset bytes verify."""
    roles: dict[str, list[str]] = {}
    for role, refs in (
        ("character", [pack.character_ref, *pack.supporting_character_refs]),
        ("scene", [pack.scene_ref, *pack.additional_scene_refs]),
        ("style", [] if pack.style_ref is None else [pack.style_ref]),
    ):
        for ref in refs:
            roles.setdefault(ref, []).append(role)

    blockers: list[str] = []
    if pack.style_ref is None:
        blockers.append("STYLE_LOCK_MISSING")
    if not isinstance(storypack_sha256, str) or _HEX_SHA256.fullmatch(storypack_sha256) is None:
        blockers.append("STORYPACK_DIGEST_INVALID")

    checks_by_ref: dict[str, dict] = {}
    for check in asset_checks:
        ref = check.get("ref") if isinstance(check, dict) else None
        if not isinstance(ref, str) or ref not in roles or ref in checks_by_ref:
            blockers.append("ASSET_CHECK_SET_MISMATCH")
            continue
        checks_by_ref[ref] = check
    if set(checks_by_ref) != set(roles):
        blockers.append("ASSET_CHECK_SET_MISMATCH")

    assets = []
    for ref, role_list in roles.items():
        row = checks_by_ref.get(ref)
        digest = row.get("recorded_sha256") if row else None
        verified = (
            row is not None
            and isinstance(digest, str)
            and _HEX_SHA256.fullmatch(digest) is not None
            and row.get("sha256_recorded") is True
            and row.get("managed_object_integrity") == "CONTENT_VERIFIED_UNAPPROVED"
            and row.get("content_integrity_verified") is True
            and row.get("physical_file_verified") is True
        )
        if not verified:
            blockers.append(f"ASSET_CONTENT_UNVERIFIED:{ref}")
            continue
        assets.append(
            {
                "ref": ref,
                "roles": role_list,
                "sha256": digest,
                "artifact_type": row.get("artifact_type"),
            }
        )

    # No digest is offered when evidence is incomplete, even if DB rows exist.
    if blockers:
        return {
            "schema": _SCHEMA,
            "status": "BLOCKED_INCOMPLETE_EVIDENCE",
            "subject_sha256": None,
            "blocking_reasons": list(dict.fromkeys(blockers)),
            "proposed_permissions": _PROPOSED_PERMISSIONS,
            "pending_trust_gates": _PENDING_GATES,
            "owner_approved": False,
            "can_queue": False,
        }

    subject = {
        "schema": _SCHEMA,
        "storypack_sha256": storypack_sha256,
        "episode_id": pack.episode_id,
        "output_profile": pack.output_profile,
        "assets": assets,
        "shot_bindings": [
            {
                "shot_id": shot.id,
                "scene_ref": shot.scene_ref or pack.scene_ref,
                "cast_refs": [pack.character_ref] if shot.cast_refs is None else shot.cast_refs,
                "style_ref": pack.style_ref,
            }
            for shot in pack.shots
        ],
        "proposed_permissions": _PROPOSED_PERMISSIONS,
    }
    return {
        "schema": _SCHEMA,
        "status": "REVIEW_SUBJECT_PREPARED_UNAPPROVED",
        "subject_sha256": _sha256_json(subject),
        "subject": subject,
        "blocking_reasons": [],
        "proposed_permissions": _PROPOSED_PERMISSIONS,
        "pending_trust_gates": _PENDING_GATES,
        # A digest is not a signature, OwnerPrincipal decision, or GPU release.
        "requires_reverification_at_decision": True,
        "owner_approved": False,
        "can_queue": False,
    }
