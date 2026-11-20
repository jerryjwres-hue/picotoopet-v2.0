"""Independent human MASTER evidence bound to an existing, frozen Owner Episode.

No extra queue, token broker, GPU permission, or automatic copyright certification.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.audit.writer import AuditWriter, canonical_hash
from picotoopet_core.db.database import Database
from picotoopet_core.domain.episode import Episode
from picotoopet_core.domain.storypack_assets import inspect_recorded_asset_refs
from picotoopet_core.domain.storypack_frame_sources import validate_episode_frame_manifest
from picotoopet_core.security.owner_principal import OwnerPrincipal, require_owner_scope

_COMMIT = "studio.storypack.master_source.review"
_REVOKE = "studio.storypack.master_source.revoke"


class MasterEvidenceError(ValueError):
    """Stable failure code; never expose local evidence paths."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class MasterEvidenceClaim(BaseModel):
    """Separate review of the actual content and its provenance evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    ref: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,99}$")
    asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    basis: Literal["self_created", "commercial_license", "written_permission"]
    evidence_ref: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,99}$")
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    human_source_review_completed: Literal[True]
    commercial_ai_use_checked: Literal[True]


def _event(db, audit_id: str, action: str):
    row = db.execute(
        "SELECT * FROM audit_events WHERE audit_id=? AND action=?", (audit_id, action)
    ).fetchone()
    if row is None:
        raise MasterEvidenceError("MASTER_AUDIT_NOT_FOUND")
    signed_fields = (
        "audit_id", "trace_id", "actor_type", "actor_id", "action",
        "resource_type", "resource_id", "decision", "reason_code",
        "details_redacted_json", "previous_hash", "created_at",
    )
    try:
        details = json.loads(row["details_redacted_json"])
        if (not isinstance(details, dict)
                or canonical_hash({key: row[key] for key in signed_fields}) != row["event_hash"]):
            raise ValueError("bad audit")
    except (ValueError, TypeError, KeyError) as exc:
        raise MasterEvidenceError("MASTER_AUDIT_CHANGED") from exc
    return row, details


def _current_event(db, audit_id: str, action: str, revoke: str):
    row, details = _event(db, audit_id, action)
    if db.execute(
        "SELECT 1 FROM audit_events WHERE action=? AND resource_id=? LIMIT 1",
        (revoke, audit_id),
    ).fetchone():
        raise MasterEvidenceError("MASTER_DEPENDENCY_REVOKED")
    if "expires_at" in details:
        try:
            expiry = datetime.fromisoformat(details["expires_at"])
            if expiry.tzinfo is None or datetime.now(UTC) >= expiry:
                raise MasterEvidenceError("MASTER_DEPENDENCY_EXPIRED")
        except (ValueError, TypeError) as exc:
            raise MasterEvidenceError("MASTER_DEPENDENCY_EXPIRED") from exc
    return row, details


class MasterEvidenceService:
    """Revalidate frozen Core tasks and genuine managed bytes before a review audit."""

    def __init__(self, database: Database, objects_dir: Path) -> None:
        self.database = database
        self.objects_dir = objects_dir
        self.audit = AuditWriter(database)

    @staticmethod
    def _frozen(db, episode_id: str, plan_sha: str | None = None):
        rows = db.execute(
            "SELECT audit_id FROM audit_events "
            "WHERE action='episode.freeze_owner_hold' AND resource_id=?",
            (episode_id,),
        ).fetchall()
        if len(rows) != 1:
            raise MasterEvidenceError("MASTER_FROZEN_JOB_MISSING")
        row, details = _event(db, rows[0]["audit_id"], "episode.freeze_owner_hold")
        plan = details.get("plan")
        digest = details.get("frozen_plan_sha256")
        if (row["decision"] != "FROZEN_HOLD"
                or not isinstance(plan, dict)
                or canonical_hash(plan) != digest
                or (plan_sha is not None and digest != plan_sha)
                or plan.get("contract") != "picotoo.owner-frozen-plan.v1"):
            raise MasterEvidenceError("MASTER_FROZEN_PLAN_CHANGED")
        return plan

    def _subject(self, db, episode_id: str, plan_sha: str, source_sha: str,
                 principal: OwnerPrincipal, claims: list[MasterEvidenceClaim]) -> dict:
        plan = self._frozen(db, episode_id, plan_sha)
        require_owner_scope(principal, plan["subject_key"], permission="master.verify")
        if principal.actor_id == plan.get("owner_actor_id"):
            raise MasterEvidenceError("MASTER_REVIEWER_MUST_DIFFER_FROM_OWNER")
        if source_sha != plan.get("source_bindings_sha256"):
            raise MasterEvidenceError("MASTER_SOURCE_SHA_CHANGED")

        # Do not trust a historical freeze if Owner review, asset claim, or approval expired.
        storyboard, board = _current_event(
            db, plan["storyboard_review_id"],
            "studio.storypack.storyboard_review.commit",
            "studio.storypack.storyboard_review.revoke",
        )
        attestation, owned = _current_event(
            db, plan["asset_attestation_id"],
            "studio.storypack.asset_use.attest", "studio.storypack.asset_use.revoke",
        )
        if (storyboard["actor_id"] != plan["owner_actor_id"]
                or attestation["actor_id"] != plan["owner_actor_id"]
                or board.get("registry_revision") != plan["owner_registry_revision"]
                or owned.get("registry_revision") != plan["owner_registry_revision"]
                or board.get("storypack_sha256") != plan["storypack_sha256"]
                or owned.get("storypack_sha256") != plan["storypack_sha256"]
                or board.get("subject_key") != plan["subject_key"]
                or owned.get("subject_key") != plan["subject_key"]):
            raise MasterEvidenceError("MASTER_OWNER_EVIDENCE_CHANGED")

        spec = db.execute(
            "SELECT spec_json FROM production_episodes WHERE episode_id=?",
            (episode_id,),
        ).fetchone()
        if spec is None:
            raise MasterEvidenceError("MASTER_EPISODE_MISSING")
        episode = Episode.model_validate_json(spec["spec_json"])
        if canonical_hash(episode.model_dump(mode="json")) != plan["episode_sha256"]:
            raise MasterEvidenceError("MASTER_EPISODE_CHANGED")

        # Reconstruct only from the immutable Core Task payload; client manifest is ignored.
        keyframes = db.execute(
            "SELECT payload_json FROM tasks WHERE task_type='gen.keyframe' "
            "AND json_extract(payload_json, '$.episode_id')=? ORDER BY rowid",
            (episode_id,),
        ).fetchall()
        if len(keyframes) != len(episode.shots):
            raise MasterEvidenceError("MASTER_KEYFRAME_TASK_SET_CHANGED")
        manifest = None
        for index, task in enumerate(keyframes):
            payload = json.loads(task["payload_json"])
            jobs = payload["jobs"]
            if (payload["shot_id"] != episode.shots[index].shot_id
                    or jobs.get("source_bindings_sha256") != source_sha):
                raise MasterEvidenceError("MASTER_TASK_SOURCE_BINDING_CHANGED")
            if manifest is None:
                manifest = jobs.get("frame_source_manifest")
            elif manifest != jobs.get("frame_source_manifest"):
                raise MasterEvidenceError("MASTER_TASK_MANIFEST_DRIFT")
        try:
            validated = validate_episode_frame_manifest(episode, manifest, source_sha)
        except ValueError as exc:
            raise MasterEvidenceError("MASTER_TASK_MANIFEST_INVALID") from exc
        if validated["storypack_sha256"] != plan["storypack_sha256"]:
            raise MasterEvidenceError("MASTER_STORYPACK_CHANGED")

        # Review ALL approved StoryPack assets, not just a subset used as first frames.
        owner_claims = owned.get("claims")
        if not isinstance(owner_claims, list):
            raise MasterEvidenceError("MASTER_OWNER_CLAIMS_MISSING")
        owner_map = {entry["ref"]: entry for entry in owner_claims}
        submitted = {item.ref: item for item in claims}
        if (len(owner_map) != len(owner_claims)
                or len(submitted) != len(claims)
                or set(submitted) != set(owner_map)):
            raise MasterEvidenceError("MASTER_REVIEW_ASSET_SET_MISMATCH")
        for bound in validated["bindings"]:
            owner = owner_map.get(bound["asset_ref"])
            if owner is None or owner["asset_sha256"] != bound["managed_sha256"]:
                raise MasterEvidenceError("MASTER_FRAME_SOURCE_MISMATCH")

        expected: dict[str, str] = {}
        for item in claims:
            owner = owner_map[item.ref]
            if (item.asset_sha256 != owner["asset_sha256"]
                    or item.basis != owner["basis"]
                    or owner["commercial_ai_generation"] is not True
                    or owner["commercial_distribution"] is not True):
                raise MasterEvidenceError("MASTER_RIGHTS_CLAIM_MISMATCH")
            if item.basis == "self_created":
                if (item.evidence_ref != item.ref
                        or item.evidence_sha256 != item.asset_sha256
                        or owner.get("evidence_sha256") is not None):
                    raise MasterEvidenceError("MASTER_SELF_CREATED_PROOF_MISMATCH")
            elif (item.evidence_ref == item.ref
                  or owner["evidence_sha256"] != item.evidence_sha256):
                raise MasterEvidenceError("MASTER_LICENSE_PROOF_MISMATCH")
            for ref, sha in ((item.ref, item.asset_sha256),
                             (item.evidence_ref, item.evidence_sha256)):
                if ref in expected and expected[ref] != sha:
                    raise MasterEvidenceError("MASTER_EVIDENCE_REF_CONFLICT")
                expected[ref] = sha

        # Rehash every managed source/evidence file, refusing missing or replaced bytes.
        checks = inspect_recorded_asset_refs(
            self.database, sorted(expected), managed_objects_dir=self.objects_dir,
        )
        if any(check["recorded_sha256"] != expected[check["ref"]]
               or check["content_integrity_verified"] is not True
               for check in checks):
            raise MasterEvidenceError("MASTER_MANAGED_EVIDENCE_INVALID")
        return {
            "contract": "picotoo.independent-master-source.v1",
            "episode_id": episode_id,
            "frozen_plan_sha256": plan_sha,
            "source_bindings_sha256": source_sha,
            "owner_asset_attestation_id": plan["asset_attestation_id"],
            "reviewer_actor_id": principal.actor_id,
            "reviewer_registry_revision": principal.registry_revision,
            "claims": [entry.model_dump(mode="json") for entry in
                       sorted(claims, key=lambda entry: entry.ref)],
        }

    @staticmethod
    def _receipt(review_id: str, digest: str, repeated: bool) -> dict:
        return {
            "status": "INDEPENDENT_HUMAN_MASTER_REVIEW_GPU_HOLD",
            "master_review_id": review_id,
            "review_subject_sha256": digest,
            "already_reviewed": repeated,
            "independent_human_source_review_recorded": True,
            "automatic_legal_certification": False,
            "worker_plan_attested": False,
            "dynamic_story_policy_admitted": False,
            "can_lease": False, "can_generate": False, "gpu_authorized": False,
        }

    def commit(self, *, episode_id: str, plan_sha: str, source_sha: str,
               principal: OwnerPrincipal, claims: list[MasterEvidenceClaim]) -> dict:
        with self.database.transaction() as db:
            subject = self._subject(db, episode_id, plan_sha, source_sha, principal, claims)
            digest = canonical_hash(subject)
            existing = db.execute(
                "SELECT audit_id FROM audit_events WHERE action=? AND resource_id=?",
                (_COMMIT, episode_id),
            ).fetchall()
            for item in existing:
                row, details = _event(db, item["audit_id"], _COMMIT)
                if details.get("review_subject_sha256") != digest:
                    raise MasterEvidenceError("MASTER_REVIEW_CONFLICT")
                if db.execute(
                    "SELECT 1 FROM audit_events WHERE action=? AND resource_id=?",
                    (_REVOKE, row["audit_id"]),
                ).fetchone():
                    raise MasterEvidenceError("MASTER_REVIEW_REVOKED")
                return self._receipt(row["audit_id"], digest, True)
            review_id = self.audit.append(
                connection=db, trace_id=plan_sha, actor_type="master_reviewer",
                actor_id=principal.actor_id, action=_COMMIT,
                resource_type="production.master_source", resource_id=episode_id,
                decision="HUMAN_SOURCE_REVIEW_ONLY", reason_code=None,
                details={"review_subject_sha256": digest, "subject": subject},
            )
        return self._receipt(review_id, digest, False)

    def verify(self, *, review_id: str, episode_id: str, plan_sha: str, source_sha: str,
               principal: OwnerPrincipal, claims: list[MasterEvidenceClaim]) -> dict:
        with self.database.transaction() as db:
            subject = self._subject(db, episode_id, plan_sha, source_sha, principal, claims)
            row, details = _current_event(db, review_id, _COMMIT, _REVOKE)
            digest = canonical_hash(subject)
            if (row["resource_id"] != episode_id
                    or row["actor_id"] != principal.actor_id
                    or details.get("subject") != subject
                    or details.get("review_subject_sha256") != digest):
                raise MasterEvidenceError("MASTER_REVIEW_STALE")
        return self._receipt(review_id, digest, True)

    def revoke(self, *, review_id: str, episode_id: str,
               principal: OwnerPrincipal) -> dict:
        with self.database.transaction() as db:
            row, _ = _event(db, review_id, _COMMIT)
            plan = self._frozen(db, episode_id)
            require_owner_scope(principal, plan["subject_key"], permission="master.verify")
            if row["resource_id"] != episode_id or row["actor_id"] != principal.actor_id:
                raise MasterEvidenceError("MASTER_REVIEW_REVOKE_SCOPE")
            if db.execute(
                "SELECT 1 FROM audit_events WHERE action=? AND resource_id=?",
                (_REVOKE, review_id),
            ).fetchone() is None:
                self.audit.append(
                    connection=db, trace_id=review_id,
                    actor_type="master_reviewer", actor_id=principal.actor_id,
                    action=_REVOKE, resource_type="production.master_source",
                    resource_id=review_id, decision="REVOKED",
                    reason_code="MASTER_REVIEW_REVOKED",
                    details={"episode_id": episode_id},
                )
        return {"status": "REVOKED", "master_review_id": review_id,
                "can_lease": False, "gpu_authorized": False}
