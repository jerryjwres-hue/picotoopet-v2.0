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
from .human_pipeline import GoalPipelineError, _PriorResultReader
from .video_return import GoalVideoReturnV1, validate_goal_video_return


class _Handoffs(Protocol):
    def context(self, goal_id: str) -> GoalHandoffContext: ...


class GoalVideoContinuationStateError(ValueError):
    """Persisted continuation state exists but failed integrity validation."""


class GoalVideoContinuationRecord(BaseModel):
    """Restart-safe projection over the existing Creative and Production records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_id: str
    handoff_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    return_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    creative_job_id: str
    creative_package_id: str | None
    creative_package_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    creative_status: str
    production_job_id: str | None
    production_status: str | None
    continuation_mode: str = "web_gpt"


class GoalVideoContinuationService:
    """Validate one manual return and reuse the closed downstream pipelines."""

    def __init__(
        self,
        *,
        database: Database,
        handoffs: _Handoffs,
        creative: CreativeIntelligenceService,
        production: ProductionService,
        goals=None,
        workflows=None,
        result_records=None,
        result_store=None,
    ) -> None:
        self.database = database
        self.handoffs = handoffs
        self.creative = creative
        self.production = production
        self.local_results = (
            _PriorResultReader(
                goals=goals, workflows=workflows,
                result_records=result_records, result_store=result_store,
            )
            if all(dep is not None for dep in (goals, workflows, result_records, result_store))
            else None
        )

    @staticmethod
    def _key(goal_id: str) -> str:
        return f"goal-video:{goal_id}"

    def submit(
        self,
        goal_id: str,
        payload: GoalVideoReturnV1,
    ) -> GoalVideoContinuationRecord:
        if self._local_goal(goal_id) is not None:
            raise GoalVideoContinuationStateError("GOAL_LOCAL_CANNOT_ADOPT_WEB_RETURN")
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
                "generated_at": payload.generated_at.isoformat(),
            },
        )
        self.production.create_job(
            ProductionJobCreateRequest(
                creative_package_id=package.creative_package_id,
                idempotency_key=self._key(goal_id),
            )
        )
        return self.status(goal_id)

    def _local_goal(self, goal_id: str):
        if self.local_results is None:
            return None
        try:
            goal = self.local_results.goal(goal_id)
        except GoalPipelineError:
            return None
        if goal.intent_type not in {"video.creative", "product.research_to_video"}:
            return None
        if goal.constraints.get("local_video_preferred") is not True:
            return None
        return goal

    def _start_local(self, goal):
        """Use real Goal Result Store proof and canonical PASS business sources; no WebGPT payload."""
        if self.local_results is None:
            raise KeyError(goal.goal_id)
        ids = goal.constraints.get("source_result_package_ids")
        if not isinstance(ids, list) or not ids:
            raise GoalVideoContinuationStateError("GOAL_LOCAL_SOURCE_REQUIRED")
        try:
            discovery = self.local_results.step_result(
                goal, step_key="research-evidence",
                expected_result_type="autonomous.discovery.v1", label="discovery",
            )
            synthesis = self.local_results.step_result(
                goal, step_key="evidence-synthesis",
                expected_result_type="autonomous.goal_synthesis.v1", label="synthesis",
            )
        except GoalPipelineError as error:
            raise KeyError(goal.goal_id) from error
        if (synthesis.get("goal_id") != goal.goal_id
            or synthesis.get("schema_version") != "1.0"
            or not synthesis.get("evidence_ids")
            or not discovery.get("evidence_ids")):
            raise GoalVideoContinuationStateError("GOAL_SYNTHESIS_PROVENANCE_INVALID")

        # Actual PASS/Completed business result package checks are performed in
        # CreativeSourceNormalizer inside create_job; never fabricate a source set.
        local_job = self.creative.create_job(
            source_result_package_ids=ids,
            creative_profile="creative.content_plan.v1",
            creative_objective=goal.objective,
            idempotency_key=self._key(goal.goal_id),
        )
        source_set = self.creative.source_normalizer.load_persisted_source_set(
            local_job.creative_job_id
        )
        if set(source_set.result_package_ids) != set(ids):
            raise GoalVideoContinuationStateError("GOAL_LOCAL_SOURCE_BINDING_MISMATCH")
        return local_job

    def _local_status(self, goal, creative_row) -> GoalVideoContinuationRecord:
        assert self.local_results is not None
        workflow = self.local_results.workflows.get_workflow(goal.workflow_id)
        hashes = {}
        for step_key, result_type in (
            ("research-evidence", "autonomous.discovery.v1"),
            ("evidence-synthesis", "autonomous.goal_synthesis.v1"),
        ):
            step = next((s for s in workflow.steps if s.step_key == step_key), None)
            if step is None or not step.task_id:
                raise GoalVideoContinuationStateError("GOAL_LOCAL_LINEAGE_LOST")
            record = self.local_results.result_records.get_for_task(step.task_id)
            if record.result_type != result_type or len(record.object_hash) != 64:
                raise GoalVideoContinuationStateError("GOAL_LOCAL_LINEAGE_LOST")
            hashes[step_key] = record.object_hash
        package_id = creative_row["creative_package_id"]
        package = None if package_id is None else self.creative.get_package(
            creative_row["creative_job_id"]
        )
        if package_id is not None and (
            package is None or package.quality_outcome.value != "PASS"
        ):
            raise GoalVideoContinuationStateError("GOAL_LOCAL_PACKAGE_NOT_PASS")
        production = None
        if package is not None:
            production = self.production.create_job(ProductionJobCreateRequest(
                creative_package_id=package.creative_package_id,
                idempotency_key=self._key(goal.goal_id),
            ))
        return GoalVideoContinuationRecord(
            goal_id=goal.goal_id,
            handoff_sha256=hashes["research-evidence"],
            return_sha256=hashes["evidence-synthesis"],
            creative_job_id=creative_row["creative_job_id"],
            creative_package_id=None if package is None else package.creative_package_id,
            creative_package_digest=None if package is None else package.package_digest,
            creative_status=creative_row["status"],
            production_job_id=None if production is None else production.production_job_id,
            production_status=None if production is None else production.status.value,
            continuation_mode="local",
        )

    def status(self, goal_id: str) -> GoalVideoContinuationRecord:
        local_goal = self._local_goal(goal_id)
        if local_goal is not None:
            self._start_local(local_goal)
        creative_row = self.database.fetchone(
            "SELECT * FROM creative_jobs WHERE idempotency_key=?",
            (self._key(goal_id),),
        )
        if creative_row is None:
            raise KeyError(goal_id)
        if local_goal is not None:
            return self._local_status(local_goal, creative_row)
        if creative_row["creative_package_id"] is None:
            raise KeyError(goal_id)
        package_row = self.database.fetchone(
            "SELECT * FROM creative_packages WHERE creative_package_id=?",
            (creative_row["creative_package_id"],),
        )
        if package_row is None:
            raise KeyError(goal_id)
        manifest = json.loads(package_row["manifest_json"])
        provenance = manifest.get("external_provenance")
        local = self.database.fetchone(
            "SELECT * FROM creative_goal_source_sets WHERE creative_job_id=? AND goal_id=?",
            (creative_row["creative_job_id"], goal_id),
        )
        if local is not None:
            # ── Report only a real locally validated Creative package with exact lineage. ──
            if (local["source_set_digest"] != creative_row["source_set_digest"]
                or local["source_set_digest"] != package_row["source_set_digest"]
                or manifest.get("source_set_digest") != local["source_set_digest"]
                or manifest.get("project_key") != f"goal-{goal_id}"
                or manifest.get("quality_outcome") != "PASS"):
                raise GoalVideoContinuationStateError("GOAL_LOCAL_SOURCE_PROVENANCE_INVALID")
            provenance = {
                "handoff_sha256": local["discovery_result_hash"],
                "return_sha256": local["synthesis_result_hash"],
            }
        elif not isinstance(provenance, dict) or provenance.get("goal_id") != goal_id:
            raise GoalVideoContinuationStateError("GOAL_CREATIVE_PROVENANCE_INVALID")
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
