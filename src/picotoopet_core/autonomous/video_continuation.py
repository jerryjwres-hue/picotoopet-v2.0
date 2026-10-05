"""Goal handoff return continuation into canonical Creative and Production."""

from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.creative.service import CreativeIntelligenceService
from picotoopet_core.db.database import Database
from picotoopet_core.production.models import ProductionJobCreateRequest
from picotoopet_core.production.service import ProductionService

from .goal_handoff_access import GoalHandoffContext
from .video_return import GoalVideoReturnV1, validate_goal_video_return


class _Handoffs(Protocol):
    def context(self, goal_id: str) -> GoalHandoffContext: ...


class GoalVideoContinuationRecord(BaseModel):
    """Restart-safe projection over the existing Creative and Production records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_id: str
    handoff_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    return_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    creative_job_id: str
    creative_package_id: str
    creative_package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    creative_status: str
    production_job_id: str | None
    production_status: str | None


class GoalVideoContinuationService:
    """Validate one manual return and reuse the closed downstream pipelines."""

    def __init__(
        self,
        *,
        database: Database,
        handoffs: _Handoffs,
        creative: CreativeIntelligenceService,
        production: ProductionService,
    ) -> None:
        self.database = database
        self.handoffs = handoffs
        self.creative = creative
        self.production = production

    @staticmethod
    def _key(goal_id: str) -> str:
        return f"goal-video:{goal_id}"

    def submit(
        self,
        goal_id: str,
        payload: GoalVideoReturnV1,
    ) -> GoalVideoContinuationRecord:
        if payload.goal_id != goal_id:
            raise ValueError("GOAL_PATH_BINDING_MISMATCH")
        context = self.handoffs.context(goal_id)
        validated = validate_goal_video_return(payload, context)
        package = self.creative.adopt_external(
            source_set=validated.source_set,
            stage_results=validated.stage_results,
            creative_objective=payload.selected_direction,
            idempotency_key=self._key(goal_id),
            provenance={
                "goal_id": goal_id,
                "handoff_sha256": context.package_sha256,
                "prompt_version": context.prompt_version,
                "return_sha256": validated.return_digest,
                "verified_fact_ids": payload.verified_fact_ids,
            },
            completed_at=payload.generated_at,
        )
        self.production.create_job(
            ProductionJobCreateRequest(
                creative_package_id=package.creative_package_id,
                idempotency_key=self._key(goal_id),
            )
        )
        return self.status(goal_id)

    def status(self, goal_id: str) -> GoalVideoContinuationRecord:
        creative_row = self.database.fetchone(
            "SELECT * FROM creative_jobs WHERE idempotency_key=?",
            (self._key(goal_id),),
        )
        if creative_row is None or creative_row["creative_package_id"] is None:
            raise KeyError(goal_id)
        package_row = self.database.fetchone(
            "SELECT * FROM creative_packages WHERE creative_package_id=?",
            (creative_row["creative_package_id"],),
        )
        if package_row is None:
            raise KeyError(goal_id)
        manifest = json.loads(package_row["manifest_json"])
        provenance = manifest.get("external_provenance")
        if not isinstance(provenance, dict) or provenance.get("goal_id") != goal_id:
            raise ValueError("GOAL_CREATIVE_PROVENANCE_INVALID")
        production_row = self.database.fetchone(
            "SELECT production_job_id,status FROM production_jobs WHERE creative_package_id=?",
            (package_row["creative_package_id"],),
        )
        return GoalVideoContinuationRecord(
            goal_id=goal_id,
            handoff_sha256=provenance["handoff_sha256"],
            return_sha256=provenance["return_sha256"],
            creative_job_id=creative_row["creative_job_id"],
            creative_package_id=package_row["creative_package_id"],
            creative_package_digest=package_row["package_digest"],
            creative_status=creative_row["status"],
            production_job_id=(
                None if production_row is None else production_row["production_job_id"]
            ),
            production_status=None if production_row is None else production_row["status"],
        )
