"""Core-owned state locks for new pet-only v2 Creative jobs.

The module is deliberately pure.  It defines and validates a source-bound contract but does not
read owner evidence, persist facts, call a model, or activate a production stage.  Those actions
remain blocked until the authenticated owner review flow can capture the structured fields.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

STATE_FACTS_SCHEMA_VERSION = "state_facts.v1"
STATE_SPINE_TEMPLATE_VERSION = "video-bible-pet-only-v1.1.0"
_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_ID_PATTERN = r"^[A-Za-z0-9_.-]+$"


def canonical_json(value: object, excluded_key: str | None = None) -> bytes:
    """Return the controller-approved compact, sorted UTF-8 representation."""

    body = value
    if excluded_key is not None and isinstance(value, dict):
        body = {key: item for key, item in value.items() if key != excluded_key}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def canonical_sha256(value: object, excluded_key: str | None = None) -> str:
    return hashlib.sha256(canonical_json(value, excluded_key)).hexdigest()


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthorityKind(StrEnum):
    OWNER_ATTESTATION = "OWNER_ATTESTATION"
    APPROVED_REFERENCE = "APPROVED_REFERENCE"
    OWNER_CREATIVE_INTENT = "OWNER_CREATIVE_INTENT"


class AllowedEvent(StrEnum):
    BLINK_AND_REOPEN = "BLINK_AND_REOPEN"
    SUBTLE_BREATHING = "SUBTLE_BREATHING"


class EvidenceBindingV1(_Strict):
    field_path: str = Field(min_length=3, max_length=160)
    evidence_id: str = Field(min_length=3, max_length=160)
    authority_kind: AuthorityKind
    owner_confirmed: Literal[True]
    review_digest: str = Field(pattern=_DIGEST_PATTERN)
    value_digest: str = Field(pattern=_DIGEST_PATTERN)


class _BoundLock(_Strict):
    evidence_bindings: list[EvidenceBindingV1] = Field(min_length=1, max_length=32)

    def _validate_bindings(self, prefix: str, values: dict[str, object]) -> None:
        expected = {f"{prefix}.{name}": value for name, value in values.items()}
        bindings = {item.field_path: item for item in self.evidence_bindings}
        if len(bindings) != len(self.evidence_bindings) or set(bindings) != set(expected):
            raise ValueError("STATE_FACT_BINDING_COVERAGE_INVALID")
        for path, value in expected.items():
            if bindings[path].value_digest != canonical_sha256(value):
                raise ValueError(f"STATE_FACT_BINDING_VALUE_MISMATCH:{path}")


class SubjectLockV1(_BoundLock):
    subject_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    species: str = Field(min_length=1, max_length=80)
    breed_or_type: str = Field(min_length=1, max_length=120)
    coat_or_appearance: str = Field(min_length=1, max_length=240)
    distinguishing_marks: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _bindings_match(self) -> SubjectLockV1:
        values = self.model_dump(mode="json", exclude={"evidence_bindings"})
        self._validate_bindings("subject_lock", values)
        taxonomy = {
            "subject_lock.subject_id",
            "subject_lock.species",
            "subject_lock.breed_or_type",
            "subject_lock.coat_or_appearance",
            "subject_lock.distinguishing_marks",
        }
        for binding in self.evidence_bindings:
            if (
                binding.field_path in taxonomy
                and binding.authority_kind is AuthorityKind.OWNER_CREATIVE_INTENT
            ):
                raise ValueError(
                    f"STATE_FACT_IDENTITY_AUTHORITY_INVALID:{binding.field_path}"
                )
        return self


class PoseLockV1(_BoundLock):
    pose_lock_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    body_pose: str = Field(min_length=1, max_length=240)
    head_direction: str = Field(min_length=1, max_length=160)
    support_surface: str = Field(min_length=1, max_length=200)
    fixed: Literal[True]

    @model_validator(mode="after")
    def _bindings_match(self) -> PoseLockV1:
        self._validate_bindings(
            "pose_lock", self.model_dump(mode="json", exclude={"evidence_bindings"})
        )
        return self


class SceneLockV1(_BoundLock):
    scene_lock_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    environment: str = Field(min_length=1, max_length=300)
    lighting: str = Field(min_length=1, max_length=200)
    temporary_accessories: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _bindings_match(self) -> SceneLockV1:
        self._validate_bindings(
            "scene_lock", self.model_dump(mode="json", exclude={"evidence_bindings"})
        )
        return self


class CameraLockV1(_BoundLock):
    camera_lock_id: str = Field(pattern=_ID_PATTERN, max_length=80)
    movement: Literal["STATIC"]
    allowed_framings: list[str] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _bindings_match(self) -> CameraLockV1:
        self._validate_bindings(
            "camera_lock", self.model_dump(mode="json", exclude={"evidence_bindings"})
        )
        return self


class StateFactsV1(_Strict):
    schema_version: Literal["state_facts.v1"] = STATE_FACTS_SCHEMA_VERSION
    facts_id: str = Field(pattern=_ID_PATTERN, max_length=100)
    facts_version: int = Field(ge=1)
    creative_profile: Literal["creative.content_plan.v2"]
    pet_only: Literal[True]
    new_job_only: Literal[True]
    subject_key: str = Field(pattern=r"^pet:[a-z0-9][a-z0-9-]{1,63}$", max_length=68)
    source_set_digest: str = Field(pattern=_DIGEST_PATTERN)
    objective_digest: str = Field(pattern=_DIGEST_PATTERN)
    subject_lock: SubjectLockV1
    pose_lock: PoseLockV1
    scene_lock: SceneLockV1
    camera_lock: CameraLockV1
    allowed_events: list[AllowedEvent] = Field(min_length=1, max_length=8)
    facts_digest: str = Field(pattern=_DIGEST_PATTERN)

    @model_validator(mode="after")
    def _digest_matches(self) -> StateFactsV1:
        document = self.model_dump(mode="json")
        if self.facts_digest != canonical_sha256(document, "facts_digest"):
            raise ValueError("STATE_FACTS_DIGEST_MISMATCH")
        if len(set(self.allowed_events)) != len(self.allowed_events):
            raise ValueError("STATE_FACTS_DUPLICATE_ALLOWED_EVENT")
        return self


def seal_state_facts(payload: dict[str, Any]) -> StateFactsV1:
    document = {key: value for key, value in payload.items() if key != "facts_digest"}
    document["facts_digest"] = canonical_sha256(document)
    return StateFactsV1.model_validate(document)


@dataclass(frozen=True, slots=True)
class StateFactsReadiness:
    outcome: Literal["READY", "NEEDS_HUMAN"]
    reason_codes: tuple[str, ...]
    model_calls: Literal[0] = 0


def state_facts_readiness(payload: StateFactsV1 | dict[str, Any] | None) -> StateFactsReadiness:
    """A pure pre-model gate; invalid or absent owner facts always make zero calls."""

    if payload is None:
        return StateFactsReadiness("NEEDS_HUMAN", ("STATE_FACTS_MISSING",))
    try:
        if isinstance(payload, StateFactsV1):
            facts = payload
        else:
            facts = StateFactsV1.model_validate(payload)
    except (ValidationError, ValueError):
        return StateFactsReadiness("NEEDS_HUMAN", ("STATE_FACTS_INVALID",))
    return StateFactsReadiness("READY", ()) if facts else StateFactsReadiness(
        "NEEDS_HUMAN", ("STATE_FACTS_INVALID",)
    )

