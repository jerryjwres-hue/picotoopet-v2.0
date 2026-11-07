"""Authenticated, source-bound owner review for the pure ``state_facts.v1`` contract."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

from picotoopet_core.creative.director import parse_goal_directives
from picotoopet_core.creative.source import NormalizedCreativeSourceSet
from picotoopet_core.creative.state_spine import (
    AuthorityKind,
    StateFactsV1,
    canonical_sha256,
    seal_state_facts,
)
from picotoopet_core.db.database import Database
from picotoopet_core.security.owner_principal import (
    OwnerAuthFailure,
    OwnerPrincipal,
    require_owner_actor,
    require_owner_scope,
)

_DIGEST = r"^[0-9a-f]{64}$"
_REQUIRED_FIELD_PATHS = (
    "subject_lock.subject_id",
    "subject_lock.species",
    "subject_lock.breed_or_type",
    "subject_lock.coat_or_appearance",
    "subject_lock.distinguishing_marks",
    "pose_lock.body_pose",
    "pose_lock.head_direction",
    "pose_lock.support_surface",
    "scene_lock.environment",
    "scene_lock.lighting",
    "scene_lock.temporary_accessories",
    "camera_lock.allowed_framings",
    "allowed_events",
)
_DERIVED_VALUES = {
    "pose_lock.fixed": True,
    "camera_lock.movement": "STATIC",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OwnerStructuredReviewError(RuntimeError):
    """Stable service error translated by the owner-review API only."""

    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


class ReviewDecision(StrEnum):
    CONFIRM = "CONFIRM"
    CORRECT = "CORRECT"
    UNKNOWN = "UNKNOWN"


class ProposalFieldStatus(StrEnum):
    EXPLICIT = "EXPLICIT"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"


class OwnerStructuredFieldDecision(_Strict):
    field_path: str
    decision: ReviewDecision
    corrected_value: JsonValue | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> OwnerStructuredFieldDecision:
        if self.field_path not in _REQUIRED_FIELD_PATHS:
            raise ValueError("OWNER_REVIEW_FIELD_PATH_INVALID")
        if self.decision is ReviewDecision.CORRECT and self.corrected_value is None:
            raise ValueError("OWNER_REVIEW_CORRECTION_VALUE_REQUIRED")
        if self.decision is not ReviewDecision.CORRECT and self.corrected_value is not None:
            raise ValueError("OWNER_REVIEW_UNEXPECTED_CORRECTION_VALUE")
        return self


class OwnerStructuredReviewPreviewRequest(_Strict):
    goal_id: str = Field(min_length=1, max_length=128)
    review_actor_id: str = Field(min_length=1, max_length=80)
    proposal_digest: str = Field(pattern=_DIGEST)
    decisions: list[OwnerStructuredFieldDecision] = Field(max_length=64)

    @model_validator(mode="after")
    def unique_fields(self) -> OwnerStructuredReviewPreviewRequest:
        paths = [item.field_path for item in self.decisions]
        if len(paths) != len(set(paths)):
            raise ValueError("OWNER_REVIEW_DECISION_FIELDS_DUPLICATE")
        return self


class OwnerEvidenceSummary(_Strict):
    evidence_id: str
    evidence_type: str
    source: str
    trust_level: str
    raw_hash: str = Field(pattern=_DIGEST)
    authority_kind: AuthorityKind | None = None
    photo_bytes_verified: bool


class OwnerStructuredFieldProposal(_Strict):
    field_path: str
    status: ProposalFieldStatus
    value: JsonValue | None = None
    evidence_id: str | None = None
    authority_kind: AuthorityKind | None = None
    value_digest: str | None = Field(default=None, pattern=_DIGEST)


class OwnerStructuredReviewProposal(_Strict):
    schema_version: Literal["owner_structured_review.proposal.v1"] = (
        "owner_structured_review.proposal.v1"
    )
    goal_id: str
    creative_job_id: str
    review_actor_id: str
    registry_revision: int
    subject_key: str
    creative_profile: Literal["creative.content_plan.v2"]
    source_set_digest: str = Field(pattern=_DIGEST)
    objective_digest: str = Field(pattern=_DIGEST)
    source_revision_digest: str = Field(pattern=_DIGEST)
    source_evidence: tuple[OwnerEvidenceSummary, ...]
    fields: dict[str, OwnerStructuredFieldProposal]
    proposal_digest: str = Field(pattern=_DIGEST)


class OwnerStructuredReviewPreview(_Strict):
    schema_version: Literal["owner_structured_review.preview.v1"] = (
        "owner_structured_review.preview.v1"
    )
    goal_id: str
    subject_key: str
    review_actor_id: str
    proposal_digest: str = Field(pattern=_DIGEST)
    source_revision_digest: str = Field(pattern=_DIGEST)
    review_digest: str = Field(pattern=_DIGEST)
    preview_digest: str = Field(pattern=_DIGEST)
    outcome: Literal["READY", "NEEDS_HUMAN"]
    reason_codes: tuple[str, ...]
    state_facts: StateFactsV1 | None
    model_calls: Literal[0] = 0


class _EvidenceCandidate(_Strict):
    evidence_id: str
    field_path: str
    value: JsonValue
    authority_kind: AuthorityKind
    trust_level: str
    review_digest: str


class _Snapshot(_Strict):
    goal_id: str
    creative_job_id: str
    subject_key: str
    creative_profile: str
    objective_digest: str
    source_set_digest: str
    source_revision_digest: str
    evidence: tuple[OwnerEvidenceSummary, ...]
    candidates: tuple[_EvidenceCandidate, ...]


class OwnerStructuredReviewService:
    """Resolve and review typed owner facts without running a model or a scheduler."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def proposal(
        self,
        goal_id: str,
        principal: OwnerPrincipal,
    ) -> OwnerStructuredReviewProposal:
        snapshot = self._snapshot(goal_id)
        self._authorize_subject(principal, snapshot.subject_key)
        fields = self._proposal_fields(snapshot.candidates)
        document = {
            "schema_version": "owner_structured_review.proposal.v1",
            "goal_id": snapshot.goal_id,
            "creative_job_id": snapshot.creative_job_id,
            "review_actor_id": principal.actor_id,
            "registry_revision": principal.registry_revision,
            "subject_key": snapshot.subject_key,
            "creative_profile": snapshot.creative_profile,
            "source_set_digest": snapshot.source_set_digest,
            "objective_digest": snapshot.objective_digest,
            "source_revision_digest": snapshot.source_revision_digest,
            "source_evidence": [item.model_dump(mode="json") for item in snapshot.evidence],
            "fields": {path: item.model_dump(mode="json") for path, item in fields.items()},
        }
        document["proposal_digest"] = canonical_sha256(document)
        return OwnerStructuredReviewProposal.model_validate(document)

    def preview(
        self,
        request: OwnerStructuredReviewPreviewRequest,
        principal: OwnerPrincipal,
    ) -> OwnerStructuredReviewPreview:
        self._authorize_actor(principal, request.review_actor_id)
        proposal = self.proposal(request.goal_id, principal)
        if request.proposal_digest != proposal.proposal_digest:
            raise OwnerStructuredReviewError(409, "OWNER_REVIEW_PROPOSAL_STALE")

        decisions = {item.field_path: item for item in request.decisions}
        review_document = {
            "goal_id": request.goal_id,
            "review_actor_id": principal.actor_id,
            "registry_revision": principal.registry_revision,
            "proposal_digest": proposal.proposal_digest,
            "source_revision_digest": proposal.source_revision_digest,
            "decisions": [decisions[path].model_dump(mode="json") for path in sorted(decisions)],
        }
        review_digest = canonical_sha256(review_document)
        values: dict[str, JsonValue] = {}
        bindings: dict[str, dict[str, object]] = {}
        reasons: list[str] = []

        for path in _REQUIRED_FIELD_PATHS:
            decision = decisions.get(path)
            if decision is None:
                reasons.append(f"OWNER_REVIEW_FIELD_MISSING:{path}")
                continue
            if decision.decision is ReviewDecision.UNKNOWN:
                reasons.append(f"OWNER_REVIEW_FIELD_UNKNOWN:{path}")
                continue
            if decision.decision is ReviewDecision.CONFIRM:
                proposed = proposal.fields[path]
                if (
                    proposed.status is not ProposalFieldStatus.EXPLICIT
                    or proposed.value is None
                    or proposed.evidence_id is None
                    or proposed.authority_kind is None
                ):
                    reasons.append(f"OWNER_REVIEW_CONFIRM_SOURCE_MISSING:{path}")
                    continue
                value = proposed.value
                evidence_id = proposed.evidence_id
                authority = proposed.authority_kind
            else:
                value = decision.corrected_value
                if value is None:
                    reasons.append(f"OWNER_REVIEW_CORRECTION_VALUE_REQUIRED:{path}")
                    continue
                authority = self._authority_for(path)
                evidence_id = self._predicted_evidence_id(
                    path=path,
                    value=value,
                    authority=authority,
                    review_digest=review_digest,
                    actor_id=principal.actor_id,
                )
            values[path] = value
            bindings[path] = self._binding(
                path=path,
                value=value,
                evidence_id=evidence_id,
                authority=authority,
                review_digest=review_digest,
            )

        if reasons:
            return self._preview_result(
                proposal=proposal,
                review_digest=review_digest,
                outcome="NEEDS_HUMAN",
                reasons=tuple(sorted(reasons)),
                state_facts=None,
            )

        state_facts = self._assemble_state_facts(
            proposal=proposal,
            values=values,
            bindings=bindings,
            review_digest=review_digest,
            actor_id=principal.actor_id,
        )
        if state_facts is None:
            return self._preview_result(
                proposal=proposal,
                review_digest=review_digest,
                outcome="NEEDS_HUMAN",
                reasons=("OWNER_REVIEW_STATE_FACTS_INVALID",),
                state_facts=None,
            )
        return self._preview_result(
            proposal=proposal,
            review_digest=review_digest,
            outcome="READY",
            reasons=(),
            state_facts=state_facts,
        )

    def _snapshot(self, goal_id: str) -> _Snapshot:
        row = self.database.fetchone(
            "SELECT g.*,s.creative_job_id,s.discovery_result_hash,s.synthesis_result_hash,"
            "s.source_set_digest,s.source_set_json,s.created_at AS source_created_at,"
            "j.creative_profile,j.creative_objective,j.objective_digest,"
            "j.source_set_digest AS job_source_set_digest "
            "FROM autonomous_goals g "
            "JOIN creative_goal_source_sets s ON s.goal_id=g.goal_id "
            "JOIN creative_jobs j ON j.creative_job_id=s.creative_job_id "
            "WHERE g.goal_id=?",
            (goal_id,),
        )
        if row is None:
            raise OwnerStructuredReviewError(404, "OWNER_REVIEW_GOAL_SOURCE_NOT_FOUND")
        try:
            constraints = json.loads(row["constraints_json"])
            subject_key = constraints["owner_subject_key"]
            source_set = NormalizedCreativeSourceSet.model_validate_json(row["source_set_json"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise OwnerStructuredReviewError(409, "OWNER_REVIEW_GOAL_SOURCE_INVALID") from error
        if (
            not isinstance(subject_key, str)
            or row["creative_profile"] != "creative.content_plan.v2"
            or not constraints.get("local_video_preferred")
            or not parse_goal_directives(row["objective"]).pet_only
            or row["creative_objective"] != row["objective"][:2000]
            or row["objective_digest"]
            != canonical_sha256({"objective": row["creative_objective"] or ""})
            or source_set.source_set_digest != row["source_set_digest"]
            or source_set.source_set_digest != row["job_source_set_digest"]
        ):
            raise OwnerStructuredReviewError(409, "OWNER_REVIEW_GOAL_SOURCE_INVALID")

        subject_rows = self.database.fetchall(
            "SELECT * FROM canonical_evidence WHERE subject_key=? ORDER BY evidence_id LIMIT 5001",
            (subject_key,),
        )
        if len(subject_rows) > 5000:
            raise OwnerStructuredReviewError(409, "OWNER_REVIEW_SOURCE_LIMIT_EXCEEDED")
        known_ids = (
            {
                item["evidence_id"]
                for item in self.database.fetchall(
                    "SELECT evidence_id FROM canonical_evidence WHERE evidence_id IN ("
                    + ",".join("?" for _ in source_set.evidence_ids)
                    + ")",
                    tuple(source_set.evidence_ids),
                )
            }
            if source_set.evidence_ids
            else set()
        )
        if known_ids != set(source_set.evidence_ids):
            raise OwnerStructuredReviewError(409, "OWNER_REVIEW_SOURCE_EVIDENCE_MISSING")

        summaries = tuple(self._evidence_summary(item) for item in subject_rows)
        candidates = tuple(
            candidate
            for item in subject_rows
            if (candidate := self._typed_candidate(item)) is not None
        )
        revision = canonical_sha256(
            {
                "goal": {
                    "goal_id": row["goal_id"],
                    "updated_at": row["updated_at"],
                    "objective": row["objective"],
                    "constraints_json": row["constraints_json"],
                },
                "creative": {
                    "creative_job_id": row["creative_job_id"],
                    "creative_profile": row["creative_profile"],
                    "objective_digest": row["objective_digest"],
                    "source_set_digest": row["source_set_digest"],
                    "source_set_json": row["source_set_json"],
                    "source_created_at": row["source_created_at"],
                },
                "evidence": [
                    {
                        "evidence_id": item["evidence_id"],
                        "raw_hash": item["raw_hash"],
                        "trust_level": item["trust_level"],
                        "source": item["source"],
                        "provenance_json": item["provenance_json"],
                        "value_json": item["value_json"],
                    }
                    for item in subject_rows
                ],
            }
        )
        return _Snapshot(
            goal_id=row["goal_id"],
            creative_job_id=row["creative_job_id"],
            subject_key=subject_key,
            creative_profile=row["creative_profile"],
            objective_digest=row["objective_digest"],
            source_set_digest=row["source_set_digest"],
            source_revision_digest=revision,
            evidence=summaries,
            candidates=candidates,
        )

    @staticmethod
    def _authorize_subject(principal: OwnerPrincipal, subject_key: str) -> None:
        try:
            require_owner_scope(principal, subject_key)
        except OwnerAuthFailure as error:
            raise OwnerStructuredReviewError(error.status_code, error.code) from error

    @staticmethod
    def _authorize_actor(principal: OwnerPrincipal, actor_id: str) -> None:
        try:
            require_owner_actor(principal, actor_id)
        except OwnerAuthFailure as error:
            raise OwnerStructuredReviewError(error.status_code, error.code) from error

    @staticmethod
    def _evidence_summary(row: Any) -> OwnerEvidenceSummary:
        try:
            provenance = json.loads(row["provenance_json"])
            value = json.loads(row["value_json"])
        except (TypeError, json.JSONDecodeError):
            provenance, value = {}, {}
        authority_raw = value.get("authority_kind") if isinstance(value, dict) else None
        try:
            authority = AuthorityKind(authority_raw) if authority_raw else None
        except ValueError:
            authority = None
        return OwnerEvidenceSummary(
            evidence_id=row["evidence_id"],
            evidence_type=row["evidence_type"],
            source=row["source"],
            trust_level=row["trust_level"],
            raw_hash=row["raw_hash"],
            authority_kind=authority,
            photo_bytes_verified=provenance.get("photo_bytes_verified") is True,
        )

    @staticmethod
    def _typed_candidate(row: Any) -> _EvidenceCandidate | None:
        try:
            value = json.loads(row["value_json"])
            provenance = json.loads(row["provenance_json"])
            path = value["field_path"]
            field_value = value["field_value"]
            authority = AuthorityKind(value["authority_kind"])
            review_digest = provenance["review_digest"]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        expected_trust = "D" if authority is AuthorityKind.OWNER_ATTESTATION else "E"
        if (
            row["source"] != "owner_structured_review"
            or path not in _REQUIRED_FIELD_PATHS
            or row["trust_level"] != expected_trust
            or not isinstance(review_digest, str)
            or len(review_digest) != 64
            or any(character not in "0123456789abcdef" for character in review_digest)
        ):
            return None
        if path.startswith("subject_lock.") and authority is AuthorityKind.OWNER_CREATIVE_INTENT:
            return None
        return _EvidenceCandidate(
            evidence_id=row["evidence_id"],
            field_path=path,
            value=field_value,
            authority_kind=authority,
            trust_level=row["trust_level"],
            review_digest=review_digest,
        )

    @staticmethod
    def _proposal_fields(
        candidates: tuple[_EvidenceCandidate, ...],
    ) -> dict[str, OwnerStructuredFieldProposal]:
        result: dict[str, OwnerStructuredFieldProposal] = {}
        for path in _REQUIRED_FIELD_PATHS:
            matches = [item for item in candidates if item.field_path == path]
            values = {canonical_sha256(item.value) for item in matches}
            if not matches:
                result[path] = OwnerStructuredFieldProposal(
                    field_path=path,
                    status=ProposalFieldStatus.UNKNOWN,
                )
            elif len(values) != 1:
                result[path] = OwnerStructuredFieldProposal(
                    field_path=path,
                    status=ProposalFieldStatus.CONFLICT,
                )
            else:
                selected = sorted(matches, key=lambda item: item.evidence_id)[-1]
                result[path] = OwnerStructuredFieldProposal(
                    field_path=path,
                    status=ProposalFieldStatus.EXPLICIT,
                    value=selected.value,
                    evidence_id=selected.evidence_id,
                    authority_kind=selected.authority_kind,
                    value_digest=canonical_sha256(selected.value),
                )
        return result

    @staticmethod
    def _authority_for(path: str) -> AuthorityKind:
        return (
            AuthorityKind.OWNER_ATTESTATION
            if path.startswith("subject_lock.")
            else AuthorityKind.OWNER_CREATIVE_INTENT
        )

    @classmethod
    def _predicted_evidence_id(
        cls,
        *,
        path: str,
        value: JsonValue,
        authority: AuthorityKind,
        review_digest: str,
        actor_id: str,
    ) -> str:
        evidence_value = cls._correction_value(
            path=path,
            value=value,
            authority=authority,
            review_digest=review_digest,
            actor_id=actor_id,
        )
        raw_hash = canonical_sha256({"numeric_value": None, "value": evidence_value})
        origin_ref = f"owner-structured-review:{review_digest}:field:{path}"
        stable = hashlib.sha256(f"manual\0{origin_ref}\0{raw_hash}".encode()).hexdigest()[:24]
        return f"evidence-{stable}"

    @staticmethod
    def _correction_value(
        *,
        path: str,
        value: JsonValue,
        authority: AuthorityKind,
        review_digest: str,
        actor_id: str,
    ) -> dict[str, JsonValue]:
        return {
            "actor_id": actor_id,
            "authority_kind": authority.value,
            "field_path": path,
            "field_value": value,
            "review_digest": review_digest,
        }

    @staticmethod
    def _binding(
        *,
        path: str,
        value: JsonValue,
        evidence_id: str,
        authority: AuthorityKind,
        review_digest: str,
    ) -> dict[str, object]:
        return {
            "field_path": path,
            "evidence_id": evidence_id,
            "authority_kind": authority.value,
            "owner_confirmed": True,
            "review_digest": review_digest,
            "value_digest": canonical_sha256(value),
        }

    def _assemble_state_facts(
        self,
        *,
        proposal: OwnerStructuredReviewProposal,
        values: dict[str, JsonValue],
        bindings: dict[str, dict[str, object]],
        review_digest: str,
        actor_id: str,
    ) -> StateFactsV1 | None:
        lock_ids = {
            "subject_lock.subject_id": values["subject_lock.subject_id"],
            "pose_lock.pose_lock_id": f"pose-{review_digest[:16]}",
            "scene_lock.scene_lock_id": f"scene-{review_digest[:16]}",
            "camera_lock.camera_lock_id": f"camera-{review_digest[:16]}",
        }
        all_values = {**values, **_DERIVED_VALUES, **lock_ids}
        derived_paths = (
            *_DERIVED_VALUES,
            "pose_lock.pose_lock_id",
            "scene_lock.scene_lock_id",
            "camera_lock.camera_lock_id",
        )
        for path in derived_paths:
            value = all_values[path]
            authority = self._authority_for(path)
            bindings[path] = self._binding(
                path=path,
                value=value,
                evidence_id=self._predicted_evidence_id(
                    path=path,
                    value=value,
                    authority=authority,
                    review_digest=review_digest,
                    actor_id=actor_id,
                ),
                authority=authority,
                review_digest=review_digest,
            )

        def lock(prefix: str, names: tuple[str, ...]) -> dict[str, object]:
            return {
                **{name: all_values[f"{prefix}.{name}"] for name in names},
                "evidence_bindings": [bindings[f"{prefix}.{name}"] for name in names],
            }

        try:
            return seal_state_facts(
                {
                    "schema_version": "state_facts.v1",
                    "facts_id": f"facts-{review_digest[:24]}",
                    "facts_version": 1,
                    "creative_profile": "creative.content_plan.v2",
                    "pet_only": True,
                    "new_job_only": True,
                    "subject_key": proposal.subject_key,
                    "source_set_digest": proposal.source_set_digest,
                    "objective_digest": proposal.objective_digest,
                    "subject_lock": lock(
                        "subject_lock",
                        (
                            "subject_id",
                            "species",
                            "breed_or_type",
                            "coat_or_appearance",
                            "distinguishing_marks",
                        ),
                    ),
                    "pose_lock": lock(
                        "pose_lock",
                        ("pose_lock_id", "body_pose", "head_direction", "support_surface", "fixed"),
                    ),
                    "scene_lock": lock(
                        "scene_lock",
                        ("scene_lock_id", "environment", "lighting", "temporary_accessories"),
                    ),
                    "camera_lock": lock(
                        "camera_lock",
                        ("camera_lock_id", "movement", "allowed_framings"),
                    ),
                    "allowed_events": all_values["allowed_events"],
                }
            )
        except (ValidationError, ValueError, TypeError):
            return None

    @staticmethod
    def _preview_result(
        *,
        proposal: OwnerStructuredReviewProposal,
        review_digest: str,
        outcome: Literal["READY", "NEEDS_HUMAN"],
        reasons: tuple[str, ...],
        state_facts: StateFactsV1 | None,
    ) -> OwnerStructuredReviewPreview:
        document: dict[str, object] = {
            "schema_version": "owner_structured_review.preview.v1",
            "goal_id": proposal.goal_id,
            "subject_key": proposal.subject_key,
            "review_actor_id": proposal.review_actor_id,
            "proposal_digest": proposal.proposal_digest,
            "source_revision_digest": proposal.source_revision_digest,
            "review_digest": review_digest,
            "outcome": outcome,
            "reason_codes": reasons,
            "state_facts": (None if state_facts is None else state_facts.model_dump(mode="json")),
            "model_calls": 0,
        }
        document["preview_digest"] = canonical_sha256(document)
        return OwnerStructuredReviewPreview.model_validate(document)
