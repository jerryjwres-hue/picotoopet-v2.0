from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from picotoopet_core.creative.state_spine import (
    AuthorityKind,
    StateFactsReadiness,
    StateFactsV1,
    canonical_sha256,
    seal_state_facts,
    state_facts_readiness,
)


def _binding(path: str, value: object, *, authority: str = "OWNER_ATTESTATION") -> dict:
    return {
        "field_path": path,
        "evidence_id": "evidence-synthetic-owner-001",
        "authority_kind": authority,
        "owner_confirmed": True,
        "review_digest": "a" * 64,
        "value_digest": canonical_sha256(value),
    }


def state_facts_payload() -> dict:
    subject = {
        "subject_id": "mochi",
        "species": "cat",
        "breed_or_type": "domestic-short-hair",
        "coat_or_appearance": "white short coat, amber eyes",
        "distinguishing_marks": ["teal scarf", "amber eyes"],
    }
    pose = {
        "pose_lock_id": "pose-seated-forward",
        "body_pose": "seated upright with all four paws supported",
        "head_direction": "head facing forward",
        "support_surface": "cream cushion on a low wooden bench",
        "fixed": True,
    }
    scene = {
        "scene_lock_id": "scene-window-bench",
        "environment": "quiet reading nook beside one window",
        "lighting": "soft daylight from camera left",
        "temporary_accessories": ["teal scarf"],
    }
    camera = {
        "camera_lock_id": "camera-static-medium",
        "movement": "STATIC",
        "allowed_framings": ["locked medium shot", "locked medium close-up"],
    }

    def bindings(prefix: str, values: dict) -> list[dict]:
        return [_binding(f"{prefix}.{key}", value) for key, value in values.items()]

    return {
        "schema_version": "state_facts.v1",
        "facts_id": "state-facts-mochi-v1",
        "facts_version": 1,
        "creative_profile": "creative.content_plan.v2",
        "pet_only": True,
        "new_job_only": True,
        "subject_key": "pet:synthetic-mochi",
        "source_set_digest": "1" * 64,
        "objective_digest": "2" * 64,
        "subject_lock": {
            **subject,
            "evidence_bindings": bindings("subject_lock", subject),
        },
        "pose_lock": {
            **pose,
            "evidence_bindings": bindings("pose_lock", pose),
        },
        "scene_lock": {
            **scene,
            "evidence_bindings": bindings("scene_lock", scene),
        },
        "camera_lock": {
            **camera,
            "evidence_bindings": bindings("camera_lock", camera),
        },
        "allowed_events": ["BLINK_AND_REOPEN", "SUBTLE_BREATHING"],
    }


def test_state_facts_canonical_digest_is_stable_and_self_verified() -> None:
    payload = state_facts_payload()
    first = seal_state_facts(payload)
    second = seal_state_facts(dict(reversed(list(payload.items()))))

    assert first == second
    assert first.facts_digest == canonical_sha256(first.model_dump(mode="json"), "facts_digest")
    assert StateFactsV1.model_validate(first.model_dump(mode="json")) == first


def test_state_facts_rejects_unbound_or_changed_locked_value() -> None:
    payload = state_facts_payload()
    payload["pose_lock"]["body_pose"] = "standing"

    with pytest.raises(ValidationError, match="STATE_FACT_BINDING_VALUE_MISMATCH"):
        seal_state_facts(payload)


def test_identity_taxonomy_cannot_be_backed_by_creative_intent() -> None:
    payload = state_facts_payload()
    binding = next(
        item
        for item in payload["subject_lock"]["evidence_bindings"]
        if item["field_path"] == "subject_lock.species"
    )
    binding["authority_kind"] = AuthorityKind.OWNER_CREATIVE_INTENT.value

    with pytest.raises(ValidationError, match="STATE_FACT_IDENTITY_AUTHORITY_INVALID"):
        seal_state_facts(payload)


def test_contract_is_strict_and_rejects_model_owned_lock_fields() -> None:
    payload = state_facts_payload()
    payload["subject_lock"]["model_guess"] = "probably a cat"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        seal_state_facts(payload)


def test_missing_or_unreviewed_source_stops_before_model_boundary() -> None:
    assert state_facts_readiness(None) == StateFactsReadiness(
        outcome="NEEDS_HUMAN",
        reason_codes=("STATE_FACTS_MISSING",),
        model_calls=0,
    )

    payload = state_facts_payload()
    payload["scene_lock"]["evidence_bindings"][0]["owner_confirmed"] = False
    assert state_facts_readiness(payload) == StateFactsReadiness(
        outcome="NEEDS_HUMAN",
        reason_codes=("STATE_FACTS_INVALID",),
        model_calls=0,
    )


def test_digest_detects_post_seal_mutation() -> None:
    sealed = seal_state_facts(state_facts_payload()).model_dump(mode="json")
    corrupted = deepcopy(sealed)
    corrupted["source_set_digest"] = "f" * 64

    with pytest.raises(ValidationError, match="STATE_FACTS_DIGEST_MISMATCH"):
        StateFactsV1.model_validate(corrupted)
