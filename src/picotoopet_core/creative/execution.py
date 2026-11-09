"""Mac Worker four-stage Creative Intelligence execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from picotoopet_core.business.local_intelligence import LocalIntelligenceError
from picotoopet_core.db.database import Database
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.worker.handlers import HandlerResult

from .director import director_constraints, parse_goal_directives, story_gate_applies
from .models import (
    CreativeBriefResult,
    CreativeDeepAiHandoffRecord,
    CreativeJobRecord,
    CreativeJobStatus,
    CreativeProfile,
    CreativeQualityOutcome,
    CreativeScriptResult,
    CreativeStageKind,
)
from .package import CreativePackageFinalizer
from .profiles import (
    CreativeStageDefinition,
    creative_profile_definition,
    pet_only_creative_stage,
    trusted_pet_only_video_bible_stage,
)
from .quality import CreativeQualityGate
from .repository import CreativeRepository
from .source import CreativeSourceNormalizer, NormalizedCreativeSourceSet
from .state_spine import (
    STATIC_PET_STORY_POLICY,
    AuthorityKind,
    StateFactsV1,
    UnlockedVideoBibleProposalV1,
    bind_pet_only_video_bible,
    build_state_spine,
    canonical_sha256,
    static_pet_story_findings,
    verify_shot_plan_prompt_locks,
)
from .store import CreativeArtifactStore
from .video_bible import (
    KEYFRAME_KIT_SCHEMA_VERSION as KEYFRAME_KIT_STAGE_KEY,
)
from .video_bible import (
    KEYFRAME_REVIEW_NOTICE,
    KEYFRAME_REVIEW_NOTICE_KEY,
    KeyframeKitError,
    VideoBible,
    build_keyframe_kit,
    derive_shot_plan,
    shot_plan_integrity_findings,
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


class TrustedPetCreativeBindingError(ValueError):
    """Fail-closed reason emitted before any pet-only v2 model call."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class TrustedPetCreativeBinding:
    commitment_id: str
    goal_id: str
    review_digest: str
    story_policy_opt_in: str
    facts: StateFactsV1


def _json_row(value: object, code: str) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError) as error:
        raise TrustedPetCreativeBindingError(code) from error
    if not isinstance(parsed, dict):
        raise TrustedPetCreativeBindingError(code)
    return parsed


def _digest_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def load_trusted_pet_creative_binding(
    database: Database,
    job: CreativeJobRecord,
) -> TrustedPetCreativeBinding:
    """Read and verify the canonical owner commitment for one Goal-backed pet v2 job.

    No caller-controlled readiness flag is accepted. Every authority edge is reconstructed from
    the Goal snapshot and canonical ledger rows already committed by Mac Core.
    """

    snapshot = database.fetchone(
        "SELECT s.goal_id,s.source_set_digest,s.source_set_json,g.objective,g.constraints_json "
        "FROM creative_goal_source_sets s "
        "JOIN autonomous_goals g ON g.goal_id=s.goal_id "
        "WHERE s.creative_job_id=?",
        (job.creative_job_id,),
    )
    if snapshot is None:
        raise TrustedPetCreativeBindingError("TRUSTED_STATE_FACTS_GOAL_LINK_MISSING")
    if snapshot["source_set_digest"] != job.source_set_digest:
        raise TrustedPetCreativeBindingError("TRUSTED_STATE_FACTS_SOURCE_MISMATCH")
    if (
        snapshot["objective"][:2000] != job.creative_objective
        or canonical_sha256({"objective": job.creative_objective or ""})
        != job.objective_digest
    ):
        raise TrustedPetCreativeBindingError("TRUSTED_STATE_FACTS_OBJECTIVE_MISMATCH")
    constraints = _json_row(
        snapshot["constraints_json"], "TRUSTED_STATE_FACTS_GOAL_CONSTRAINTS_INVALID"
    )
    subject_key = constraints.get("owner_subject_key")
    if not isinstance(subject_key, str) or not subject_key.startswith("pet:"):
        raise TrustedPetCreativeBindingError("TRUSTED_STATE_FACTS_SUBJECT_MISSING")

    rows = database.fetchall(
        "SELECT * FROM canonical_evidence WHERE goal_id=? AND subject_key=? "
        "AND evidence_type='pet.owner.state_facts.v1' "
        "AND source='owner_structured_review' AND origin_kind='manual' "
        "ORDER BY captured_at DESC,evidence_id DESC LIMIT 2",
        (snapshot["goal_id"], subject_key),
    )
    if not rows:
        raise TrustedPetCreativeBindingError("TRUSTED_STATE_FACTS_COMMITMENT_MISSING")
    row = rows[0]
    value = _json_row(row["value_json"], "TRUSTED_STATE_FACTS_COMMITMENT_INVALID")
    provenance = _json_row(
        row["provenance_json"], "TRUSTED_STATE_FACTS_COMMITMENT_INVALID"
    )
    if value.get("record_kind") != "owner_structured_review_commit.v1":
        raise TrustedPetCreativeBindingError("TRUSTED_STATE_FACTS_COMMITMENT_INVALID")
    story_policy = value.get("story_policy_opt_in")
    if story_policy != STATIC_PET_STORY_POLICY:
        raise TrustedPetCreativeBindingError("TRUSTED_STORY_POLICY_NOT_SELECTED")
    try:
        facts = StateFactsV1.model_validate(value.get("state_facts"))
    except ValidationError as error:
        raise TrustedPetCreativeBindingError("TRUSTED_STATE_FACTS_COMMITMENT_INVALID") from error
    if facts.subject_key != subject_key:
        raise TrustedPetCreativeBindingError("TRUSTED_STATE_FACTS_SUBJECT_MISMATCH")
    if facts.source_set_digest != job.source_set_digest:
        raise TrustedPetCreativeBindingError("TRUSTED_STATE_FACTS_SOURCE_MISMATCH")
    if facts.objective_digest != job.objective_digest:
        raise TrustedPetCreativeBindingError("TRUSTED_STATE_FACTS_OBJECTIVE_MISMATCH")

    review_digest = value.get("review_digest")
    actor_id = value.get("review_actor_id")
    digest_fields = (
        value.get("source_revision_digest"),
        value.get("proposal_digest"),
        review_digest,
        value.get("preview_digest"),
    )
    if (
        not all(_digest_text(item) for item in digest_fields)
        or not isinstance(actor_id, str)
        or not actor_id
        or provenance.get("owner_reviewed") is not True
        or provenance.get("actor_id") != actor_id
        or provenance.get("review_digest") != review_digest
        or provenance.get("proposal_digest") != value.get("proposal_digest")
        or provenance.get("preview_digest") != value.get("preview_digest")
    ):
        raise TrustedPetCreativeBindingError("TRUSTED_STATE_FACTS_PROVENANCE_INVALID")

    groups = (
        facts.subject_lock.evidence_bindings,
        facts.pose_lock.evidence_bindings,
        facts.scene_lock.evidence_bindings,
        facts.camera_lock.evidence_bindings,
    )
    bindings = [item for group in groups for item in group]
    evidence_rows = {
        item["evidence_id"]: item
        for item in database.fetchall(
            "SELECT * FROM canonical_evidence WHERE goal_id=? AND subject_key=? "
            "ORDER BY evidence_id",
            (snapshot["goal_id"], subject_key),
        )
    }
    for binding in bindings:
        bound = evidence_rows.get(binding.evidence_id)
        if bound is None:
            raise TrustedPetCreativeBindingError("TRUSTED_STATE_FACTS_BINDING_MISSING")
        bound_value = _json_row(
            bound["value_json"], "TRUSTED_STATE_FACTS_BINDING_INVALID"
        )
        bound_provenance = _json_row(
            bound["provenance_json"], "TRUSTED_STATE_FACTS_BINDING_INVALID"
        )
        expected_trust = (
            "D" if binding.authority_kind is AuthorityKind.OWNER_ATTESTATION else "E"
        )
        if (
            bound["source"] != "owner_structured_review"
            or bound["origin_kind"] != "manual"
            or bound["trust_level"] != expected_trust
            or bound_value.get("field_path") != binding.field_path
            or bound_value.get("authority_kind") != binding.authority_kind.value
            or canonical_sha256(bound_value.get("field_value")) != binding.value_digest
            or bound_provenance.get("owner_reviewed") is not True
            or bound_provenance.get("actor_id") != actor_id
            or bound_provenance.get("review_digest") != review_digest
        ):
            raise TrustedPetCreativeBindingError("TRUSTED_STATE_FACTS_BINDING_INVALID")

    allowed_event_binding = next(
        (
            item
            for item in evidence_rows.values()
            if _json_row(item["value_json"], "TRUSTED_STATE_FACTS_BINDING_INVALID").get(
                "field_path"
            )
            == "allowed_events"
        ),
        None,
    )
    if allowed_event_binding is None:
        raise TrustedPetCreativeBindingError("TRUSTED_STATE_FACTS_BINDING_MISSING")
    allowed_value = _json_row(
        allowed_event_binding["value_json"], "TRUSTED_STATE_FACTS_BINDING_INVALID"
    )
    allowed_provenance = _json_row(
        allowed_event_binding["provenance_json"], "TRUSTED_STATE_FACTS_BINDING_INVALID"
    )
    if (
        allowed_event_binding["source"] != "owner_structured_review"
        or allowed_event_binding["trust_level"] != "E"
        or allowed_value.get("authority_kind") != AuthorityKind.OWNER_CREATIVE_INTENT.value
        or canonical_sha256(allowed_value.get("field_value"))
        != canonical_sha256(facts.model_dump(mode="json")["allowed_events"])
        or allowed_provenance.get("actor_id") != actor_id
        or allowed_provenance.get("review_digest") != review_digest
    ):
        raise TrustedPetCreativeBindingError("TRUSTED_STATE_FACTS_BINDING_INVALID")

    return TrustedPetCreativeBinding(
        commitment_id=row["evidence_id"],
        goal_id=snapshot["goal_id"],
        review_digest=review_digest,
        story_policy_opt_in=story_policy,
        facts=facts,
    )


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
        # Explicit pet-only v2 Goals select schema-first model stages without affecting
        # old commercial/v1 jobs or the deterministic derived shot-plan stage.
        pet_only_v2 = (
            profile.profile_id == "creative.content_plan.v2"
            and parse_goal_directives(job.creative_objective).pet_only
        )
        trusted_pet: TrustedPetCreativeBinding | None = None
        goal_backed_pet_v2 = pet_only_v2 and self.database.fetchone(
            "SELECT goal_id FROM creative_goal_source_sets WHERE creative_job_id=?",
            (job.creative_job_id,),
        ) is not None
        if goal_backed_pet_v2:
            try:
                trusted_pet = load_trusted_pet_creative_binding(self.database, job)
            except TrustedPetCreativeBindingError as error:
                self.repository.transition_job(
                    job.creative_job_id,
                    CreativeJobStatus.NEEDS_HUMAN,
                    failure_code=error.code,
                    error_message="Owner-confirmed pet Creative facts require attention.",
                    finished=True,
                )
                return self._summary(job.creative_job_id, CreativeJobStatus.NEEDS_HUMAN)
        previous: dict[str, dict[str, Any]] = {}
        for stage_definition in profile.stages:
            stage_kind = stage_definition.stage_kind
            if pet_only_v2:
                stage_definition = (
                    trusted_pet_only_video_bible_stage(stage_definition)
                    if trusted_pet is not None
                    and stage_kind is CreativeStageKind.VIDEO_BIBLE
                    else pet_only_creative_stage(stage_definition)
                )
            context = self._stage_context(
                job.creative_objective,
                source_set,
                previous,
                stage_kind,
                profile_id=profile.profile_id,
            )
            if trusted_pet is not None and stage_kind is CreativeStageKind.VIDEO_BIBLE:
                spine = build_state_spine(
                    trusted_pet.facts,
                    ["BLINK_AND_REOPEN", "SUBTLE_BREATHING", "SUBTLE_BREATHING"],
                    story_policy_opt_in=trusted_pet.story_policy_opt_in,
                )
                context["trusted_state_spine"] = {
                    "commitment_id": trusted_pet.commitment_id,
                    "facts_digest": trusted_pet.facts.facts_digest,
                    "spine_digest": spine.spine_digest,
                    "story_policy_opt_in": trusted_pet.story_policy_opt_in,
                    "shots": [
                        {
                            "shot_id": transition.shot_id,
                            "beat_id": previous[CreativeStageKind.SCRIPT.value]["beats"][index][
                                "beat_id"
                            ],
                            "event": transition.event.value,
                            "allowed_camera_framings": (
                                trusted_pet.facts.camera_lock.allowed_framings
                            ),
                        }
                        for index, transition in enumerate(spine.transitions)
                    ],
                }
            input_digest = self._digest(self._digest_view(context))
            stage = self.repository.create_or_get_stage(
                creative_job_id=job.creative_job_id,
                stage_kind=stage_kind,
                input_digest=input_digest,
                template_version=stage_definition.template_version,
            )
            if stage.status == "Completed" and stage.result is not None:
                problem = self._completed_stage_problem(
                    stage_kind, stage.result, previous, source_set, profile.profile_id
                )
                if problem is not None:
                    return self._fail_closed_reused_stage(job.creative_job_id, stage_kind, problem)
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
                    trusted_pet=trusted_pet,
                )
            except LocalIntelligenceError as error:
                # Audit-only metadata   : persist fixed-field diagnostics, never raw response.
                diagnostic_json = (
                    json.dumps(error.diagnostics, sort_keys=True, separators=(",", ":"))
                    if error.code == "LOCAL_MODEL_JSON_INVALID" and error.diagnostics
                    else None
                )
                self.repository.update_stage(
                    stage.stage_run_id,
                    status="NeedsHuman",
                    quality_outcome=CreativeQualityOutcome.NEEDS_HUMAN,
                    failure_code=error.code,
                    error_message=diagnostic_json,
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
        """Add the untrusted keyframe_kit.v1 sidecar for a story-gated three-shot Goal.

        Only exactly three gated shots produce a kit. The kit is a proposal: every still is
        PENDING_HUMAN_REVIEW and nothing here claims an image, a hash or an approval exists.
        """

        bible_raw = previous.get(CreativeStageKind.VIDEO_BIBLE.value)
        if bible_raw is None:
            return
        bible = VideoBible.model_validate(bible_raw)
        if not story_gate_applies(parse_goal_directives(objective), len(bible.shots)):
            return
        brief = CreativeBriefResult.model_validate(previous[CreativeStageKind.CREATIVE_BRIEF.value])
        script = CreativeScriptResult.model_validate(previous[CreativeStageKind.SCRIPT.value])
        try:
            kit = build_keyframe_kit(bible, script, output_profile_id=brief.output_profile_id.value)
        except KeyframeKitError:
            return
        previous[KEYFRAME_KIT_STAGE_KEY] = kit.model_dump(mode="json")
        previous[KEYFRAME_REVIEW_NOTICE_KEY] = dict(KEYFRAME_REVIEW_NOTICE)

    @staticmethod
    def _completed_stage_problem(
        stage_kind: CreativeStageKind,
        result: dict[str, Any],
        previous: dict[str, dict[str, Any]],
        source_set: NormalizedCreativeSourceSet,
        profile_id: str,
    ) -> str | None:
        """Re-verify a persisted v2 Shot Plan against its sealed Bible before a restart reuses it.

        Uses the same pure derivation that built it, so a legitimately persisted result always
        passes and v1 jobs are never touched. A tampered Bible is already refused earlier by the
        immutable stage input digest (``creative stage immutable input conflict``).
        """

        if profile_id == "creative.content_plan.v1":
            return None
        try:
            if stage_kind is CreativeStageKind.SHOT_PLAN:
                bible = VideoBible.model_validate(previous[CreativeStageKind.VIDEO_BIBLE.value])
                if bible.source_set_digest != source_set.source_set_digest:
                    return "CREATIVE_COMPLETED_BIBLE_SOURCE_MISMATCH"
                script = CreativeScriptResult.model_validate(
                    previous[CreativeStageKind.SCRIPT.value]
                )
                if shot_plan_integrity_findings(bible, script, result):
                    return "CREATIVE_COMPLETED_SHOT_PLAN_BIBLE_MISMATCH"
        except (ValueError, KeyError):
            return "CREATIVE_COMPLETED_STAGE_INVALID"
        return None

    def _fail_closed_reused_stage(
        self, creative_job_id: str, stage_kind: CreativeStageKind, code: str
    ) -> HandlerResult:
        # The stored stage row is left untouched as evidence; a re-run fails identically
        # instead of silently re-deriving over it.
        self.repository.transition_job(
            creative_job_id,
            CreativeJobStatus.NEEDS_HUMAN,
            current_stage=stage_kind,
            failure_code=code,
            error_message="A stored creative stage no longer matches its sealed source.",
            finished=True,
        )
        return self._summary(creative_job_id, CreativeJobStatus.NEEDS_HUMAN)

    def _run_stage(
        self,
        *,
        stage,
        stage_definition: CreativeStageDefinition,
        source_set: NormalizedCreativeSourceSet,
        previous: dict[str, dict[str, Any]],
        context: dict[str, Any],
        profile,  # type: ignore[no-untyped-def]
        trusted_pet: TrustedPetCreativeBinding | None = None,
    ) -> tuple[dict[str, Any] | None, CreativeQualityOutcome, dict[str, Any], list[str]]:
        if stage_definition.executor == "DERIVED":
            return self._run_derived(
                stage=stage,
                stage_definition=stage_definition,
                source_set=source_set,
                previous=previous,
                profile=profile,
                objective=context.get("creative_objective"),
                trusted_pet=trusted_pet,
            )
        if (
            trusted_pet is not None
            and stage_definition.stage_kind is CreativeStageKind.VIDEO_BIBLE
        ):
            return self._run_trusted_pet_video_bible(
                stage=stage,
                stage_definition=stage_definition,
                source_set=source_set,
                previous=previous,
                context=context,
                profile=profile,
                trusted_pet=trusted_pet,
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

    def _run_trusted_pet_video_bible(
        self,
        *,
        stage,  # type: ignore[no-untyped-def]
        stage_definition: CreativeStageDefinition,
        source_set: NormalizedCreativeSourceSet,
        previous: dict[str, dict[str, Any]],
        context: dict[str, Any],
        profile,  # type: ignore[no-untyped-def]
        trusted_pet: TrustedPetCreativeBinding,
    ) -> tuple[dict[str, Any] | None, CreativeQualityOutcome, dict[str, Any], list[str]]:
        """Run the model only for unlocked suggestions, then bind and gate in Core."""

        starting_attempts = stage.model_attempts
        last_raw: dict[str, Any] = stage.result or {}
        correction: str | None = None
        if starting_attempts >= self.MAX_MODEL_ATTEMPTS_PER_STAGE and stage.status != "Completed":
            return (
                None,
                CreativeQualityOutcome.NEEDS_DEEP_AI,
                last_raw,
                ["CREATIVE_STAGE_ATTEMPT_BUDGET_EXHAUSTED"],
            )
        if starting_attempts > 0 and stage.status == "Retry" and stage.result:
            outcome, _payload, reasons = self._evaluate_trusted_pet_video_bible(
                raw=stage.result,
                source_set=source_set,
                previous=previous,
                objective=context.get("creative_objective"),
                profile=profile,
                trusted_pet=trusted_pet,
            )
            if outcome is CreativeQualityOutcome.RETRY:
                correction = self._trusted_pet_correction(reasons)

        for attempt in range(starting_attempts + 1, self.MAX_MODEL_ATTEMPTS_PER_STAGE + 1):
            self.repository.update_stage(
                stage.stage_run_id, status="Running", model_attempts=attempt
            )
            raw = self.adapter.run(stage_definition, context, correction=correction)
            last_raw = raw
            outcome, payload, reasons = self._evaluate_trusted_pet_video_bible(
                raw=raw,
                source_set=source_set,
                previous=previous,
                objective=context.get("creative_objective"),
                profile=profile,
                trusted_pet=trusted_pet,
            )
            if outcome is CreativeQualityOutcome.PASS and payload is not None:
                digest = self._digest(payload)
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
            digest = self._digest(raw)
            if (
                outcome is CreativeQualityOutcome.RETRY
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
                correction = self._trusted_pet_correction(reasons)
                continue
            terminal = (
                CreativeQualityOutcome.NEEDS_DEEP_AI
                if outcome is CreativeQualityOutcome.RETRY
                else outcome
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
            return None, terminal, raw, reasons
        return (
            None,
            CreativeQualityOutcome.NEEDS_DEEP_AI,
            last_raw,
            ["CREATIVE_STAGE_ATTEMPT_BUDGET_EXHAUSTED"],
        )

    def _evaluate_trusted_pet_video_bible(
        self,
        *,
        raw: dict[str, Any],
        source_set: NormalizedCreativeSourceSet,
        previous: dict[str, dict[str, Any]],
        objective: str | None,
        profile,  # type: ignore[no-untyped-def]
        trusted_pet: TrustedPetCreativeBinding,
    ) -> tuple[CreativeQualityOutcome, dict[str, Any] | None, list[str]]:
        try:
            proposal = UnlockedVideoBibleProposalV1.model_validate(raw)
        except ValidationError:
            return CreativeQualityOutcome.RETRY, None, ["RESULT_SCHEMA_INVALID"]
        if proposal.needs_human:
            return CreativeQualityOutcome.NEEDS_HUMAN, None, ["MODEL_DECLARED_HUMAN_REVIEW"]
        if proposal.needs_deep_ai:
            return CreativeQualityOutcome.NEEDS_HUMAN, None, ["MODEL_DECLARED_DEEP_AI"]
        try:
            script = CreativeScriptResult.model_validate(
                previous[CreativeStageKind.SCRIPT.value]
            )
            spine = build_state_spine(
                trusted_pet.facts,
                ["BLINK_AND_REOPEN", "SUBTLE_BREATHING", "SUBTLE_BREATHING"],
                story_policy_opt_in=trusted_pet.story_policy_opt_in,
            )
            draft = bind_pet_only_video_bible(
                trusted_pet.facts,
                spine,
                proposal,
                script,
            )
        except (KeyError, ValidationError, ValueError) as error:
            code = str(error).split("\n", 1)[0]
            return CreativeQualityOutcome.RETRY, None, [code[:160]]

        decision, parsed = self.quality.evaluate(
            stage_kind=CreativeStageKind.VIDEO_BIBLE,
            profile=profile,
            source_set=source_set,
            previous_stages=previous,
            raw_result=draft.model_dump(mode="json"),
            objective=objective,
        )
        if decision.outcome is not CreativeQualityOutcome.PASS or parsed is None:
            return decision.outcome, None, decision.reasons
        findings = list(static_pet_story_findings(draft, trusted_pet.facts, spine))
        if findings:
            return CreativeQualityOutcome.RETRY, None, findings[:20]
        return CreativeQualityOutcome.PASS, parsed.model_dump(mode="json"), []

    @staticmethod
    def _trusted_pet_correction(reasons: list[str]) -> str:
        return (
            "Repair only these unlocked Video Bible proposal fields; never emit locked facts: "
            + "; ".join(reasons[:12])
        )[:2000]

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
        trusted_pet: TrustedPetCreativeBinding | None = None,
    ) -> tuple[dict[str, Any] | None, CreativeQualityOutcome, dict[str, Any], list[str]]:
        """Build the shot plan from the sealed Video Bible with no model call."""

        bible = VideoBible.model_validate(previous[CreativeStageKind.VIDEO_BIBLE.value])
        script = CreativeScriptResult.model_validate(previous[CreativeStageKind.SCRIPT.value])
        raw = derive_shot_plan(bible, script)
        if trusted_pet is not None:
            lock_findings = verify_shot_plan_prompt_locks(raw, trusted_pet.facts)
            if lock_findings:
                digest = self._digest(raw)
                self.repository.update_stage(
                    stage.stage_run_id,
                    status="NeedsHuman",
                    model_attempts=0,
                    result=raw,
                    result_digest=digest,
                    quality_outcome=CreativeQualityOutcome.NEEDS_HUMAN,
                    failure_code="CREATIVE_PROMPT_LOCK_MISSING",
                    finished=True,
                )
                return (
                    None,
                    CreativeQualityOutcome.NEEDS_DEEP_AI,
                    raw,
                    list(lock_findings)[:20],
                )
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
    def _digest_view(context: dict[str, Any]) -> dict[str, Any]:
        """The context the immutable stage input digest covers.

        The default story rules are model-facing only. Leaving them out keeps the digest of a
        Bible stage persisted before the default existed unchanged, so such a job resumes.
        """

        constraints = context.get("director_constraints")
        if not isinstance(constraints, dict) or "story_quality_rules" not in constraints:
            return context
        return {
            **context,
            "director_constraints": {
                key: value for key, value in constraints.items() if key != "story_quality_rules"
            },
        }

    @staticmethod
    def _digest(value: object) -> str:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _summary(creative_job_id: str, status: CreativeJobStatus) -> HandlerResult:
        return HandlerResult(summary={"creative_job_id": creative_job_id, "status": status.value})
