"""Strict StoryPack handoff to the existing local pet-only Human Goal.

Managed bytes and a previously reviewed claim packet are separate from
OwnerPrincipal approval, MASTER registration, and production authorization.
"""
from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.autonomous.owner_subject_evidence import OwnerSubjectEvidencePacket
from picotoopet_core.creative.director import parse_goal_directives
from picotoopet_core.creative.dynamic_pet_story import build_dynamic_motion_proposal
from picotoopet_core.domain.storypack import StoryPackV1, storypack_preview
from picotoopet_core.domain.storypack_assets import inspect_recorded_asset_refs
from picotoopet_core.domain.storypack_goal_intake import build_storypack_goal_intake
from picotoopet_core.domain.storypack_owner_subject import build_owner_review_subject


class ScopedStoryGoalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    storypack: StoryPackV1
    project_id: str = Field(min_length=1, max_length=100)
    owner_subject_key: str = Field(pattern=r"^pet:[a-z0-9][a-z0-9-]{1,63}$")
    reviewed_packet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed_subject_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def prepare_scoped_story_goal(payload: ScopedStoryGoalRequest, services) -> tuple[dict, dict]:
    """Recheck actual Core bytes/claims, then prepare a frozen server-side Goal binding."""
    pack = payload.storypack
    preview = storypack_preview(pack)
    proposal = build_storypack_goal_intake(
        pack, preview["storypack_sha256"], scoped_dynamic=True,
    )
    if not proposal["ready_for_user_submission"]:
        raise ValueError("STORY_GOAL_NOT_READY")

    # 01. This bridge covers the existing single-pet / single-scene P0 route only.
    if (
        pack.supporting_character_refs or pack.additional_scene_refs or not pack.style_ref
        or any(
            shot.cast_refs not in (None, [pack.character_ref])
            or shot.scene_ref not in (None, pack.scene_ref)
            or (index > 0 and shot.handoff != "continuous")
            for index, shot in enumerate(pack.shots)
        )
    ):
        raise ValueError("STORY_GOAL_P0_SCOPE_UNSUPPORTED")
    directives = parse_goal_directives(proposal["objective"])
    if not directives.pet_only or directives.shot_count != 3 or directives.shot_seconds != 4:
        raise ValueError("STORY_GOAL_DIRECTIVES_CONFLICT")

    database = services.database
    project = database.fetchone(
        "SELECT status FROM projects WHERE project_id=?", (payload.project_id,)
    )
    if project is None or project["status"] != "Active":
        raise ValueError("STORY_GOAL_PROJECT_UNAVAILABLE")

    # 02. Recheck exact role, project, local-only policy and actual managed object bytes.
    role_refs = {"character": pack.character_ref, "scene": pack.scene_ref, "style": pack.style_ref}
    if len(set(role_refs.values())) != 3:
        raise ValueError("STORY_GOAL_ASSET_ROLE_COLLISION")
    checks = inspect_recorded_asset_refs(
        database, list(role_refs.values()), managed_objects_dir=services.settings.paths.objects_dir
    )
    by_ref = {item["ref"]: item for item in checks}
    assets = {}
    for role, ref in role_refs.items():
        row = database.fetchone(
            "SELECT project_id, artifact_type, sha256, cloud_policy FROM artifacts WHERE artifact_id=?",
            (ref,),
        )
        check = by_ref[ref]
        if (row is None or row["project_id"] != payload.project_id
            or row["artifact_type"] != f"storypack_{role}" or row["cloud_policy"] != "local_only"
            or check["content_integrity_verified"] is not True
            or row["sha256"] != check["recorded_sha256"]):
            raise ValueError("STORY_GOAL_ASSET_UNVERIFIED")
        assets[role] = {"artifact_id": ref, "sha256": row["sha256"]}

    subject = build_owner_review_subject(pack, preview["storypack_sha256"], checks)
    if (subject["status"] != "REVIEW_SUBJECT_PREPARED_UNAPPROVED"
        or subject["subject_sha256"] != payload.confirmed_subject_sha256):
        raise ValueError("STORY_GOAL_SUBJECT_MISMATCH")

    # 03. Select only an existing exact reviewed claim packet. Never manufacture
    # owner testimony from a draft, infer identity from filenames, or grant OwnerPrincipal.
    packets = reviewed_owner_packets(database, payload.owner_subject_key,
                                    assets["character"]["sha256"])
    matched_packet = next(
        (packet for packet in packets if packet["packet_digest"] == payload.reviewed_packet_sha256),
        None,
    )
    if matched_packet is None:
        raise ValueError("STORY_GOAL_OWNER_PACKET_INVALID")
    matched = matched_packet["evidence"]

    # 04. Bind immutable identities, not permissions. The subsequent structured
    # OwnerPrincipal review and all production authorizations remain mandatory.
    binding = {
        "schema": "picotoo.storypack.scoped-goal-binding.v1",
        "storypack_sha256": preview["storypack_sha256"],
        "subject_sha256": subject["subject_sha256"],
        "project_id": payload.project_id,
        "owner_subject_key": payload.owner_subject_key,
        "reviewed_packet_sha256": payload.reviewed_packet_sha256,
        "assets": assets,
        "owner_evidence": matched,
    }
    if pack.dynamic_motion is not None:
        # Preserve the full authored pack and deterministic motion digest, not merely text.
        motion = build_dynamic_motion_proposal(pack)
        binding["dynamic_storypack"] = pack.model_dump(mode="json")
        binding["dynamic_motion_digest"] = motion["motion_digest"]
    return proposal, binding



def reviewed_owner_packets(database, subject_key: str, photo_sha256: str) -> list[dict]:
    """Reconstruct exact reviewed packets, including original claim order and digest."""
    rows = database.fetchall(
        "SELECT evidence_id,evidence_type,text_value,raw_hash,trust_level,"
        "provenance_json,origin_ref,captured_at "
        "FROM canonical_evidence WHERE subject_key=? AND source='owner_attestation' "
        "AND origin_kind='manual' ORDER BY evidence_id LIMIT 5001",
        (subject_key,),
    )
    if len(rows) > 5000:
        raise ValueError("STORY_GOAL_EVIDENCE_LIMIT")
    groups: dict[str, list] = {}
    for row in rows:
        try:
            provenance = json.loads(row["provenance_json"])
        except (ValueError, TypeError):
            continue
        digest = provenance.get("reviewed_packet_sha256") if isinstance(provenance, dict) else None
        if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
            groups.setdefault(digest, []).append((row, provenance))

    packets = []
    for digest, members in groups.items():
        indexed = {}
        evidence = []
        for row, provenance in members:
            prefix = f"pet-owner:{digest}:claim:"
            origin = row["origin_ref"]
            ordinal = origin[len(prefix):] if isinstance(origin, str) and origin.startswith(prefix) else ""
            text = row["text_value"]
            kind = row["evidence_type"].removeprefix("pet.owner.")
            if (
                re.fullmatch(r"0[1-9]|10", ordinal) is None
                or int(ordinal) in indexed
                or provenance.get("owner_reviewed") is not True
                or provenance.get("photo_bytes_verified") is not False
                or provenance.get("photo_sha256_claim") != photo_sha256
                or kind not in {"visible_identity", "visible_scene", "creative_intent"}
                or row["evidence_type"] != f"pet.owner.{kind}"
                or row["trust_level"] != ("E" if kind == "creative_intent" else "D")
                or not isinstance(text, str) or text != text.strip()
                or hashlib.sha256(text.encode("utf-8")).hexdigest() != row["raw_hash"]
            ):
                break
            indexed[int(ordinal)] = {"kind": kind, "statement": text}
            evidence.append({
                "evidence_id": row["evidence_id"], "kind": row["evidence_type"],
                "raw_hash": row["raw_hash"],
            })
        else:
            if sorted(indexed) != list(range(1, len(indexed) + 1)):
                continue
            try:
                packet = OwnerSubjectEvidencePacket.model_validate({
                    "subject_key": subject_key, "photo_sha256_claim": photo_sha256,
                    "claims": [indexed[index] for index in sorted(indexed)],
                })
            except ValueError:
                continue
            if packet.digest() != digest:
                continue
            packets.append({
                "packet_digest": digest,
                "packet": packet.model_dump(mode="json"),
                "evidence": sorted(evidence, key=lambda item: item["evidence_id"]),
                "captured_at": max(row["captured_at"] for row, _ in members),
            })
    return sorted(packets, key=lambda packet: (packet["captured_at"], packet["packet_digest"]),
                  reverse=True)


def list_scoped_reviewed_packets(services, project_id: str, character_ref: str,
                                 subject_key: str) -> dict:
    """Return at most 10 exact matching, local-only attestation packets; no authority."""
    database = services.database
    row = database.fetchone(
        "SELECT a.sha256, a.artifact_type, a.cloud_policy, p.status "
        "FROM artifacts a JOIN projects p ON p.project_id=a.project_id "
        "WHERE a.artifact_id=? AND a.project_id=?",
        (character_ref, project_id),
    )
    if (row is None or row["status"] != "Active"
        or row["artifact_type"] != "storypack_character" or row["cloud_policy"] != "local_only"):
        raise ValueError("STORY_GOAL_ASSET_UNVERIFIED")
    check = inspect_recorded_asset_refs(
        database, [character_ref], managed_objects_dir=services.settings.paths.objects_dir,
    )[0]
    if check["content_integrity_verified"] is not True or row["sha256"] != check["recorded_sha256"]:
        raise ValueError("STORY_GOAL_ASSET_UNVERIFIED")
    candidates = reviewed_owner_packets(database, subject_key, row["sha256"])
    return {
        "contract": "picotoo.storypack.reviewed-owner-packets.v1",
        "project_id": project_id, "character_ref": character_ref,
        "subject_key": subject_key, "character_sha256": row["sha256"],
        "packets": [
            {"packet_digest": item["packet_digest"], "claims": item["packet"]["claims"],
             "captured_at": item["captured_at"]}
            for item in candidates[:10]
        ],
        "owner_approved": False,
        "production_approval_granted": False,
        "can_queue": False,
    }


def load_bound_dynamic_storypack(binding: dict) -> StoryPackV1 | None:
    """Reconstruct exact dynamic scope; absent legacy motion never grants new authority."""
    if not isinstance(binding, dict):
        raise ValueError("DYNAMIC_SCOPE_INVALID")
    if "dynamic_storypack" not in binding and "dynamic_motion_digest" not in binding:
        return None
    try:
        pack = StoryPackV1.model_validate(binding["dynamic_storypack"])
        if pack.dynamic_motion is None:
            raise ValueError("DYNAMIC_SCOPE_INVALID")
        motion = build_dynamic_motion_proposal(pack)
        if (
            motion["motion_digest"] != binding.get("dynamic_motion_digest")
            or motion["storypack_sha256"] != binding.get("storypack_sha256")
            or any(
                pack_ref != binding["assets"][role]["artifact_id"]
                for role, pack_ref in (
                    ("character", pack.character_ref),
                    ("scene", pack.scene_ref),
                    ("style", pack.style_ref),
                )
            )
        ):
            raise ValueError("DYNAMIC_SCOPE_DIGEST_MISMATCH")
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("DYNAMIC_SCOPE_INVALID") from error
    return pack


def reverify_scoped_story_assets(database, objects_dir, binding: dict) -> None:
    """Check the submitted assets again before each trusted creative execution."""
    # Existing unscoped Goals are handled by the caller, never by a fallback here.
    if not isinstance(binding, dict) or binding.get("schema") != (
        "picotoo.storypack.scoped-goal-binding.v1"
    ):
        raise ValueError("STORY_GOAL_ASSET_SCOPE_INVALID")
    assets = binding.get("assets")
    project_id = binding.get("project_id")
    if not isinstance(assets, dict) or set(assets) != {"character", "scene", "style"}:
        raise ValueError("STORY_GOAL_ASSET_SCOPE_INVALID")
    if not isinstance(project_id, str) or not project_id:
        raise ValueError("STORY_GOAL_ASSET_SCOPE_INVALID")
    project = database.fetchone(
        "SELECT status FROM projects WHERE project_id=?", (project_id,)
    )
    if project is None or project["status"] != "Active":
        raise ValueError("STORY_GOAL_PROJECT_UNAVAILABLE")

    refs = []
    for asset in assets.values():
        if (
            not isinstance(asset, dict)
            or not isinstance(asset.get("artifact_id"), str)
            or not isinstance(asset.get("sha256"), str)
        ):
            raise ValueError("STORY_GOAL_ASSET_SCOPE_INVALID")
        refs.append(asset["artifact_id"])
    if len(set(refs)) != 3:
        raise ValueError("STORY_GOAL_ASSET_SCOPE_INVALID")

    checked = {
        item["ref"]: item for item in inspect_recorded_asset_refs(
            database, refs, managed_objects_dir=objects_dir
        )
    }
    for role, asset in assets.items():
        ref = asset["artifact_id"]
        row = database.fetchone(
            "SELECT project_id, artifact_type, cloud_policy FROM artifacts WHERE artifact_id=?",
            (ref,),
        )
        if (
            row is None or row["project_id"] != project_id
            or row["artifact_type"] != f"storypack_{role}"
            or row["cloud_policy"] != "local_only"
            or checked[ref]["recorded_sha256"] != asset["sha256"]
            or checked[ref]["content_integrity_verified"] is not True
        ):
            raise ValueError("STORY_GOAL_PINNED_ASSET_CHANGED")
