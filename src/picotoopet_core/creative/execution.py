"""Mac Worker four-stage Creative Intelligence execution."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from picotoopet_core.business.local_intelligence import LocalIntelligenceError
from picotoopet_core.db.database import Database
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.worker.handlers import HandlerResult

from .director import director_constraints, parse_goal_directives
from .models import (
    CreativeBriefResult,
    CreativeDeepAiHandoffRecord,
    CreativeJobStatus,
    CreativeProfile,
    CreativeQualityOutcome,
    CreativeScriptResult,
    CreativeStageKind,
)
from .package import CreativePackageFinalizer
from .profiles import CreativeStageDefinition, creative_profile_definition
from .quality import CreativeQualityGate
from .repository import CreativeRepository
from .source import CreativeSourceNormalizer, NormalizedCreativeSourceSet
from .store import CreativeArtifactStore
from .video_bible import (
    KEYFRAME_KIT_SCHEMA_VERSION as KEYFRAME_KIT_STAGE_KEY,
)
from .video_bible import (
    KeyframeKitError,
    VideoBible,
    build_keyframe_kit,
    derive_shot_plan,
)


class _Adapter(Protocol):
    def run(
        self,
        profile: CreativeStageDefinition,
        context: dict[str, Any],
        *,
        correction: str | None = None,
    ) -> dict[str, Any]: ...


class CreativeTaskPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    creative_job_id: str
    source_set_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    creative_profile: CreativeProfile

    @classmethod
    def from_task(cls, task: TaskRecord) -> CreativeTaskPayload:
        value = cls.model_validate(task.payload)
        UUID(value.creative_job_id)
        return value


class CreativeIntelligenceCoordinator:
    TASK_TYPE = "creative.content_plan.v1"
    CAPABILITY = "creative.intelligence.v1"
    MAX_MODEL_ATTEMPTS_PER_STAGE = 2

    _JOB_STATUS = {
        CreativeStageKind.IDEA_RANKING: CreativeJobStatus.IDEA_RANKING,
        CreativeStageKind.CREATIVE_BRIEF: CreativeJobStatus.BRIEF_GENERATION,
        CreativeStageKind.SCRIPT: CreativeJobStatus.SCRIPT_GENERATION,
        CreativeStageKind.VIDEO_BIBLE: CreativeJobStatus.SHOT_PLANNING,
        CreativeStageKind.SHOT_PLAN: CreativeJobStatus.SHOT_PLANNING,
    }
    # Stages whose failure must stay local: the Deep-AI handoff/continuation path only knows
    # the four v1 stage kinds and no hosted model may be called per video.
    _LOCAL_ONLY_FAILURE = {
        CreativeStageKind.VIDEO_BIBLE: "CREATIVE_VIDEO_BIBLE_UNRESOLVED",
        CreativeStageKind.SHOT_PLAN: "CREATIVE_DERIVED_SHOT_PLAN_REJECTED",
    }

    def __init__(
        self,
        *,
        database: Database,
        queue: DiagnosticQueueRepository,
        repository: CreativeRepository,
        source_normalizer: CreativeSourceNormalizer,
        store: CreativeArtifactStore,
        adapter: _Adapter,
        configured_model_id: str,
    ) -> None:
        self.database = database
        self.queue = queue
        self.repository = repository
        self.source_normalizer = source_normalizer
        self.store = store
        self.adapter = adapter
        self.configured_model_id = configured_model_id
        self.quality = CreativeQualityGate()
        self.package_finalizer = CreativePackageFinalizer(repository=repository, store=store)

    def handler(self, task: TaskRecord) -> HandlerResult:
        payload = CreativeTaskPayload.from_task(task)
        job = self.repository.get_job(payload.creative_job_id)
        if (
            job.source_set_digest != payload.source_set_digest
            or job.creative_profile is not payload.creative_profile
        ):
            raise ValueError("CREATIVE_TASK_IDENTITY_MISMATCH")
        if job.status is CreativeJobStatus.CREATIVE_READY:
            return self._summary(job.creative_job_id, CreativeJobStatus.CREATIVE_READY)
        if job.status in {
            CreativeJobStatus.REJECTED,
            CreativeJobStatus.FAILED,
            CreativeJobStatus.CANCELLED,
        }:
            raise ValueError("CREATIVE_JOB_NOT_EXECUTABLE")
        existing_package = self.repository.package_for(job.creative_job_id)
        if existing_package is not None:
            self.repository.transition_job(
                job.creative_job_id,
                CreativeJobStatus.CREATIVE_READY,
                creative_package_id=existing_package.creative_package_id,
                finished=True,
            )
            return self._summary(job.creative_job_id, CreativeJobStatus.CREATIVE_READY)
        existing_handoff = self.repository.handoff_for(job.creative_job_id)
        if existing_handoff is not None:
            self.repository.transition_job(
                job.creative_job_id,
                CreativeJobStatus.NEEDS_DEEP_AI,
                deep_ai_handoff_id=existing_handoff.handoff_id,
                finished=True,
            )
            return self._summary(job.creative_job_id, CreativeJobStatus.NEEDS_DEEP_AI)

        source_set = self.source_normalizer.load_persisted_source_set(job.creative_job_id)
        if source_set.source_set_digest != job.source_set_digest:
            raise ValueError("CREATIVE_SOURCE_SET_DIGEST_MISMATCH")
        profile = creative_profile_definition(job.creative_profile.value)
        previous: dict[str, dict[str, Any]] = {}
        for stage_definition in profile.stages:
            stage_kind = stage_definition.stage_kind
            context = self._stage_context(
                job.creative_objective,
                source_set,
                previous,
                stage_kind,
                profile_id=profile.profile_id,
            )
            input_digest = self._digest(context)
            stage = self.repository.create_or_get_stage(
                creative_job_id=job.creative_job_id,
                stage_kind=stage_kind,
                input_digest=input_digest,
                template_version=stage_definition.template_version,
            )
            if stage.status == "Completed" and stage.result is not None:
                previous[stage_kind.value] = stage.result
                continue
            self.repository.transition_job(
                job.creative_job_id,
                self._JOB_STATUS[stage_kind],
                current_stage=stage_kind,
            )
            try:
                result, outcome, raw, reasons = self._run_stage(
                    stage=stage,
                    stage_definition=stage_definition,
                    source_set=source_set,
                    previous=previous,
                    context=context,
                    profile=profile,
                )
            except LocalIntelligenceError as error:
                self.repository.update_stage(
                    stage.stage_run_id,
                    status="NeedsHuman",
                    quality_outcome=CreativeQualityOutcome.NEEDS_HUMAN,
                    failure_code=error.code,
                    finished=True,
                )
                self.repository.transition_job(
                    job.creative_job_id,
                    CreativeJobStatus.NEEDS_HUMAN,
                    current_stage=stage_kind,
                    failure_code=error.code,
                    error_message="Local creative intelligence requires attention.",
                    finished=True,
                )
                return self._summary(job.creative_job_id, CreativeJobStatus.NEEDS_HUMAN)
            if outcome is CreativeQualityOutcome.PASS and result is not None:
                previous[stage_kind.value] = result
                continue
            if outcome is CreativeQualityOutcome.NEEDS_HUMAN:
                self.repository.transition_job(
                    job.creative_job_id,
                    CreativeJobStatus.NEEDS_HUMAN,
                    current_stage=stage_kind,
                    finished=True,
                )
                return self._summary(job.creative_job_id, CreativeJobStatus.NEEDS_HUMAN)
            if outcome is CreativeQualityOutcome.REJECT:
                self.repository.transition_job(
                    job.creative_job_id,
                    CreativeJobStatus.REJECTED,
                    current_stage=stage_kind,
                    failure_code="CREATIVE_OUTPUT_REJECTED",
                    finished=True,
                )
                return self._summary(job.creative_job_id, CreativeJobStatus.REJECTED)
            local_only = self._local_only_failure(profile.profile_id, stage_kind)
            if local_only is not None:
                self.repository.update_stage(
                    stage.stage_run_id,
                    status="NeedsHuman",
                    quality_outcome=CreativeQualityOutcome.NEEDS_HUMAN,
                    failure_code=local_only,
                    finished=True,
                )
                self.repository.transition_job(
                    job.creative_job_id,
                    CreativeJobStatus.NEEDS_HUMAN,
                    current_stage=stage_kind,
                    failure_code=local_only,
                    error_message="Local story direction requires attention.",
                    finished=True,
                )
                return self._summary(job.creative_job_id, CreativeJobStatus.NEEDS_HUMAN)
            return self._finish_deep_ai(
                creative_job_id=job.creative_job_id,
                stage_kind=stage_kind,
                source_set=source_set,
                failed_result=raw,
                reasons=reasons or ["CREATIVE_STAGE_REQUIRES_DEEP_AI"],
                return_schema=stage_definition.return_schema,
                previous=previous,
            )

        self._attach_keyframe_kit(job.creative_objective, previous)
        return self._finish_package(job.creative_job_id, source_set, previous, profile)

    @staticmethod
    def _attach_keyframe_kit(objective: str | None, previous: dict[str, dict[str, Any]]) -> None:
        """Add the untrusted keyframe_kit.v1 sidecar for an explicit story-gate Goal.

        Only exactly three gated shots produce a kit. The kit is a proposal: every still is
        PENDING_HUMAN_REVIEW and nothing here claims an image, a hash or an approval exists.
        """

        bible_raw = previous.get(CreativeStageKind.VIDEO_BIBLE.value)
        if bible_raw is None or not parse_goal_directives(objective).story_gate:
            return
        bible = VideoBible.model_validate(bible_raw)
        brief = CreativeBriefResult.model_validate(previous[CreativeStageKind.CREATIVE_BRIEF.value])
        script = CreativeScriptResult.model_validate(previous[CreativeStageKind.SCRIPT.value])
        try:
            kit = build_keyframe_kit(bible, script, output_profile_id=brief.output_profile_id.value)
        except KeyframeKitError:
            return
        previous[KEYFRAME_KIT_STAGE_KEY] = kit.model_dump(mode="json")

    def _run_stage(
        self,
        *,
        stage,
        stage_definition: CreativeStageDefinition,
        source_set: NormalizedCreativeSourceSet,
        previous: dict[str, dict[str, Any]],
        context: dict[str, Any],
        profile,  # type: ignore[no-untyped-def]
    ) -> tuple[dict[str, Any] | None, CreativeQualityOutcome, dict[str, Any], list[str]]:
        if stage_definition.executor == "DERIVED":
            return self._run_derived(
                stage=stage,
                stage_definition=stage_definition,
                source_set=source_set,
                previous=previous,
                profile=profile,
                objective=context.get("creative_objective"),
            )
        correction: str | None = None
        last_raw: dict[str, Any] = stage.result or {}
        starting_attempts = stage.model_attempts
        if starting_attempts >= self.MAX_MODEL_ATTEMPTS_PER_STAGE and stage.status != "Completed":
            return (
                None,
                CreativeQualityOutcome.NEEDS_DEEP_AI,
                last_raw,
                ["CREATIVE_STAGE_ATTEMPT_BUDGET_EXHAUSTED"],
            )
        if starting_attempts > 0 and stage.status == "Retry" and stage.result:
            # A restart between the two attempts must not make the second one blind: the
            # repair text is a pure function of the stored output, so recompute it.
            earlier, _ = self.quality.evaluate(
                stage_kind=stage_definition.stage_kind,
                profile=profile,
                source_set=source_set,
                previous_stages=previous,
                raw_result=stage.result,
                objective=context.get("creative_objective"),
            )
            if earlier.outcome is CreativeQualityOutcome.RETRY:
                correction = earlier.correction_instruction
        for attempt in range(starting_attempts + 1, self.MAX_MODEL_ATTEMPTS_PER_STAGE + 1):
            self.repository.update_stage(
                stage.stage_run_id, status="Running", model_attempts=attempt
            )
            raw = self.adapter.run(stage_definition, context, correction=correction)
            last_raw = raw
            decision, parsed = self.quality.evaluate(
                stage_kind=stage_definition.stage_kind,
                profile=profile,
                source_set=source_set,
                previous_stages=previous,
                raw_result=raw,
                objective=context.get("creative_objective"),
            )
            digest = self._digest(raw)
            if decision.outcome is CreativeQualityOutcome.PASS and parsed is not None:
                payload = parsed.model_dump(mode="json")
                self.repository.update_stage(
                    stage.stage_run_id,
                    status="Completed",
                    model_attempts=attempt,
                    result=payload,
                    result_digest=digest,
                    quality_outcome=CreativeQualityOutcome.PASS,
                    finished=True,
                )
                return payload, CreativeQualityOutcome.PASS, raw, []
            if (
                decision.outcome is CreativeQualityOutcome.RETRY
                and attempt < self.MAX_MODEL_ATTEMPTS_PER_STAGE
            ):
                self.repository.update_stage(
                    stage.stage_run_id,
                    status="Retry",
                    model_attempts=attempt,
                    result=raw,
                    result_digest=digest,
                    quality_outcome=CreativeQualityOutcome.RETRY,
                )
                correction = decision.correction_instruction
                continue
            terminal = (
                CreativeQualityOutcome.NEEDS_DEEP_AI
                if decision.outcome is CreativeQualityOutcome.RETRY
                else decision.outcome
            )
            self.repository.update_stage(
                stage.stage_run_id,
                status=terminal.value,
                model_attempts=attempt,
                result=raw,
                result_digest=digest,
                quality_outcome=terminal,
                finished=True,
            )
            return None, terminal, raw, decision.reasons
        return (
            None,
            CreativeQualityOutcome.NEEDS_DEEP_AI,
            last_raw,
            ["CREATIVE_STAGE_ATTEMPT_BUDGET_EXHAUSTED"],
        )

    def _local_only_failure(self, profile_id: str, stage_kind: CreativeStageKind) -> str | None:
        if profile_id == "creative.content_plan.v1":
            return None
        return self._LOCAL_ONLY_FAILURE.get(stage_kind)

    def _run_derived(
        self,
        *,
        stage,  # type: ignore[no-untyped-def]
        stage_definition: CreativeStageDefinition,
        source_set: NormalizedCreativeSourceSet,
        previous: dict[str, dict[str, Any]],
        profile,  # type: ignore[no-untyped-def]
        objective: str | None = None,
    ) -> tuple[dict[str, Any] | None, CreativeQualityOutcome, dict[str, Any], list[str]]:
        """Build the shot plan from the sealed Video Bible with no model call."""

        bible = VideoBible.model_validate(previous[CreativeStageKind.VIDEO_BIBLE.value])
        script = CreativeScriptResult.model_validate(previous[CreativeStageKind.SCRIPT.value])
        raw = derive_shot_plan(bible, script)
        decision, parsed = self.quality.evaluate(
            stage_kind=stage_definition.stage_kind,
            profile=profile,
            source_set=source_set,
            previous_stages=previous,
            raw_result=raw,
            objective=objective,
        )
        digest = self._digest(raw)
        if decision.outcome is CreativeQualityOutcome.PASS and parsed is not None:
            payload = parsed.model_dump(mode="json")
            self.repository.update_stage(
                stage.stage_run_id,
                status="Completed",
                model_attempts=0,
                result=payload,
                result_digest=digest,
                quality_outcome=CreativeQualityOutcome.PASS,
                finished=True,
            )
            return payload, CreativeQualityOutcome.PASS, raw, []
        self.repository.update_stage(
            stage.stage_run_id,
            status="NeedsHuman",
            model_attempts=0,
            result=raw,
            result_digest=digest,
            quality_outcome=CreativeQualityOutcome.NEEDS_HUMAN,
            finished=True,
        )
        return None, CreativeQualityOutcome.NEEDS_DEEP_AI, raw, decision.reasons

    def _finish_package(self, creative_job_id, source_set, previous, profile) -> HandlerResult:  # type: ignore[no-untyped-def]
        self.repository.transition_job(creative_job_id, CreativeJobStatus.QUALITY_CHECK)
        saved = self.package_finalizer.finalize(
            creative_job_id=creative_job_id,
            source_set=source_set,
            stage_results=previous,
            profile=profile,
            configured_model_id=self.configured_model_id,
        )
        self.repository.transition_job(
            creative_job_id,
            CreativeJobStatus.CREATIVE_READY,
            creative_package_id=saved.creative_package_id,
            finished=True,
        )
        return self._summary(creative_job_id, CreativeJobStatus.CREATIVE_READY)

    def _finish_deep_ai(
        self,
        *,
        creative_job_id: str,
        stage_kind: CreativeStageKind,
        source_set: NormalizedCreativeSourceSet,
        failed_result: dict[str, Any],
        reasons: list[str],
        return_schema: dict[str, Any],
        previous: dict[str, dict[str, Any]],
    ) -> HandlerResult:
        handoff_id = str(uuid4())
        failed_digest = self._digest(failed_result)
        payload = {
            "schema_version": "1.0",
            "handoff_id": handoff_id,
            "creative_job_id": creative_job_id,
            "failed_stage": stage_kind.value,
            "source_set_digest": source_set.source_set_digest,
            "bounded_findings": [
                {
                    "source_finding_ref": item.source_finding_ref,
                    "finding": item.finding,
                    "evidence_ids": item.evidence_ids,
                }
                for item in source_set.findings[:24]
            ],
            "prior_validated_stages": previous,
            "failed_local_result": failed_result,
            "quality_reasons": reasons,
            "return_schema": return_schema,
        }
        relative, package_digest = self.store.write_handoff_package(handoff_id, payload)
        record = CreativeDeepAiHandoffRecord(
            handoff_id=handoff_id,
            creative_job_id=creative_job_id,
            stage_kind=stage_kind,
            source_set_digest=source_set.source_set_digest,
            failed_result_digest=failed_digest,
            quality_reasons=reasons,
            return_schema=return_schema,
            package_digest=package_digest,
            package_relpath=relative,
            status="ManualReady",
            created_at=datetime.now(UTC),
        )
        saved = self.repository.save_handoff(record)
        self.repository.transition_job(
            creative_job_id,
            CreativeJobStatus.NEEDS_DEEP_AI,
            current_stage=stage_kind,
            deep_ai_handoff_id=saved.handoff_id,
            finished=True,
        )
        return self._summary(creative_job_id, CreativeJobStatus.NEEDS_DEEP_AI)

    @staticmethod
    def _stage_context(
        creative_objective: str | None,
        source_set: NormalizedCreativeSourceSet,
        previous: dict[str, dict[str, Any]],
        stage_kind: CreativeStageKind,
        profile_id: str = "creative.content_plan.v1",
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "schema_version": "1.0",
            "creative_profile": "creative.content_plan.v1",
            "stage": stage_kind.value,
            "creative_objective": creative_objective
            or "Create an evidence-grounded content plan from the supplied findings.",
            "source_findings": [
                {
                    "source_finding_ref": item.source_finding_ref,
                    "finding": item.finding,
                    "evidence_ids": item.evidence_ids,
                }
                for item in source_set.findings
            ],
            "allowed_evidence_ids": source_set.evidence_ids,
        }
        if stage_kind is CreativeStageKind.CREATIVE_BRIEF:
            ideas = previous[CreativeStageKind.IDEA_RANKING.value]["ideas"]
            context["selected_rank_1_idea"] = next(item for item in ideas if item["rank"] == 1)
        elif stage_kind is CreativeStageKind.SCRIPT:
            context["creative_brief"] = previous[CreativeStageKind.CREATIVE_BRIEF.value]
        elif stage_kind is CreativeStageKind.VIDEO_BIBLE:
            brief = previous[CreativeStageKind.CREATIVE_BRIEF.value]
            script = previous[CreativeStageKind.SCRIPT.value]
            context["creative_brief"] = brief
            context["script"] = script
            context["director_constraints"] = director_constraints(
                CreativeBriefResult.model_validate(brief),
                CreativeScriptResult.model_validate(script),
                parse_goal_directives(creative_objective),
            )
        elif stage_kind is CreativeStageKind.SHOT_PLAN:
            context["creative_brief"] = previous[CreativeStageKind.CREATIVE_BRIEF.value]
            context["script"] = previous[CreativeStageKind.SCRIPT.value]
            if profile_id != "creative.content_plan.v1":
                context["video_bible"] = previous[CreativeStageKind.VIDEO_BIBLE.value]
        if profile_id != "creative.content_plan.v1":
            context["creative_runtime"] = profile_id
        return context

    @staticmethod
    def _digest(value: object) -> str:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _summary(creative_job_id: str, status: CreativeJobStatus) -> HandlerResult:
        return HandlerResult(summary={"creative_job_id": creative_job_id, "status": status.value})
