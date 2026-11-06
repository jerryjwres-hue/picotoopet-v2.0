"""Launch canonical Creative from real durable Goal discovery and synthesis; no Web GPT."""

from __future__ import annotations

import hashlib
import json

from picotoopet_core.creative.director import parse_goal_directives
from picotoopet_core.creative.models import CreativeProfile
from picotoopet_core.creative.service import CreativeIntelligenceService
from picotoopet_core.creative.source import CreativeSourceFinding, NormalizedCreativeSourceSet
from picotoopet_core.domain.models import TaskRecord
from picotoopet_core.worker.handlers import HandlerResult

from .human_pipeline import (
    GoalPipelineError,
    GoalStageRequest,
    _DISCOVERY_RESULT_TYPE,
    _DISCOVERY_STEP,
    _LOCAL_CREATIVE_RESULT_TYPE,
    _PriorResultReader,
    _SYNTHESIS_RESULT_TYPE,
    _SYNTHESIS_STEP,
    _handoff_evidence,
)

_VIDEO_GOALS = frozenset({"video.creative", "product.research_to_video"})


class GoalLocalCreativeCoordinator(_PriorResultReader):
    """Link real ResultStore SHA identities to the same four-stage Creative queue."""

    TASK_TYPE = _LOCAL_CREATIVE_RESULT_TYPE
    CAPABILITY = "local.goal.creative"

    def __init__(self, *, goals, workflows, result_records, result_store,
                 creative: CreativeIntelligenceService) -> None:
        super().__init__(goals=goals, workflows=workflows,
                         result_records=result_records, result_store=result_store)
        self.creative = creative

    @staticmethod
    def _digest(document: object) -> str:
        return hashlib.sha256(json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()

    def _profile_for_goal(self, goal) -> str:
        """Select the existing immutable job profile, then opt fresh three-shot Goals into v2."""
        # Durable replay  : restore the stored profile before interpreting fresh directives.
        # Identity binding: the Goal-to-Creative idempotency key is immutable across restarts.
        existing = self.creative.repository.database.fetchone(
            "SELECT creative_profile FROM creative_jobs WHERE idempotency_key=?",
            (f"goal-video:{goal.goal_id}",),
        )
        if existing is not None:
            return existing["creative_profile"]

        # Fresh Goal      : explicit three-shot / affirmative Story Gate selects existing v2.
        # Legacy default  : other new Goals retain the existing v1 Creative pipeline.
        directives = parse_goal_directives(goal.objective)
        if directives.shot_count == 3 or directives.story_gate:
            return CreativeProfile.CONTENT_PLAN_V2.value
        return CreativeProfile.CONTENT_PLAN_V1.value

    def _hash_for_step(self, goal, step_key: str, expected_type: str) -> str:
        # ── ResultStore identities come from Core workflow facts, not model output. ──
        workflow = self.workflows.get_workflow(goal.workflow_id)
        step = next((item for item in workflow.steps if item.step_key == step_key), None)
        if step is None or not step.task_id:
            raise GoalPipelineError("GOAL_SOURCE_STEP_MISSING")
        record = self.result_records.get_for_task(step.task_id)
        if record.result_type != expected_type:
            raise GoalPipelineError("GOAL_SOURCE_TYPE_MISMATCH")
        return record.object_hash

    def handler(self, task: TaskRecord) -> HandlerResult:
        if task.task_type != self.TASK_TYPE:
            raise GoalPipelineError("GOAL_CREATIVE_TASK_TYPE_INVALID")
        request = GoalStageRequest.model_validate(task.payload)
        goal = self.goal(request.goal_id)
        if goal.intent_type not in _VIDEO_GOALS:
            raise GoalPipelineError("GOAL_NOT_VIDEO_ELIGIBLE")
        discovery = self.step_result(
            goal, step_key=_DISCOVERY_STEP,
            expected_result_type=_DISCOVERY_RESULT_TYPE, label="discovery",
        )
        synthesis = self.step_result(
            goal, step_key=_SYNTHESIS_STEP,
            expected_result_type=_SYNTHESIS_RESULT_TYPE, label="synthesis",
        )
        if synthesis.get("goal_id") != goal.goal_id:
            raise GoalPipelineError("GOAL_SYNTHESIS_GOAL_MISMATCH")
        _, source_evidence = _handoff_evidence(discovery)
        allowed = {item["evidence_id"] for item in source_evidence}
        used = synthesis.get("evidence_ids")
        findings_raw = synthesis.get("findings")
        if (not isinstance(used, list) or not used
            or any(not isinstance(item, str) or item not in allowed for item in used)
            or not isinstance(findings_raw, list) or not findings_raw):
            raise GoalPipelineError("GOAL_CREATIVE_EVIDENCE_INSUFFICIENT")

        owner_key = goal.constraints.get("owner_subject_key")
        owner_statements: list[dict[str, object]] = []
        if owner_key is not None:
            # Never infer ownership from a product, a free-text prompt, or model output.
            if (
                goal.intent_type != "video.creative"
                or not isinstance(owner_key, str)
                or not parse_goal_directives(goal.objective).pet_only
            ):
                raise GoalPipelineError("OWNER_SUBJECT_GOAL_SCOPE_INVALID")
            for item in discovery.get("connected_evidence", []):
                if not isinstance(item, dict) or item.get("subject_key") != owner_key:
                    continue
                evidence_id = item.get("evidence_id")
                evidence_type = item.get("evidence_type")
                packet_digest = item.get("reviewed_packet_sha256")
                if (
                    not isinstance(evidence_id, str)
                    or evidence_id not in used
                    or item.get("source") != "owner_attestation"
                    or item.get("origin") != "manual"
                    or item.get("photo_bytes_verified") is not False
                    or item.get("trust_level") not in {"D", "E"}
                    or not isinstance(packet_digest, str)
                    or len(packet_digest) != 64
                    or not all(ch in "0123456789abcdef" for ch in packet_digest)
                    or evidence_type not in {
                        "pet.owner.visible_identity",
                        "pet.owner.visible_scene",
                        "pet.owner.creative_intent",
                    }
                    or not isinstance(item.get("text_excerpt"), str)
                    or not item["text_excerpt"].strip()
                ):
                    continue
                owner_statements.append(item)
            supported = {item["evidence_type"] for item in owner_statements}
            if not {
                "pet.owner.visible_identity",
                "pet.owner.visible_scene",
                "pet.owner.creative_intent",
            }.issubset(supported):
                raise GoalPipelineError("OWNER_SUBJECT_EVIDENCE_NOT_SYNTHESIZED")

        discovery_hash = self._hash_for_step(goal, _DISCOVERY_STEP, _DISCOVERY_RESULT_TYPE)
        synthesis_hash = self._hash_for_step(goal, _SYNTHESIS_STEP, _SYNTHESIS_RESULT_TYPE)
        source_identity = f"goal-synthesis:{synthesis_hash}"
        findings = []
        for rank, statement in enumerate(findings_raw[:24], start=1):
            if not isinstance(statement, str) or not statement.strip():
                raise GoalPipelineError("GOAL_CREATIVE_FINDING_INVALID")
            item = {
                "rank": rank,
                "analysis": statement[:2000],
                "claim_status": "unverified_inference",
                "evidence_ids": used,
            }
            findings.append(CreativeSourceFinding(
                source_finding_ref=f"{source_identity}:finding:{rank}",
                result_package_id=source_identity,
                result_digest=synthesis_hash,
                work_package_id=f"goal:{goal.goal_id}",
                finding_rank=rank,
                finding_digest=self._digest(item),
                finding=item,
                evidence_ids=used,
            ))
        for owner in owner_statements:
            # Owner-attested identity/scene and intended motions are separate,
            # citable statements, never magically promoted model inferences.
            rank = len(findings) + 1
            evidence_id = str(owner["evidence_id"])
            intent = owner["evidence_type"] == "pet.owner.creative_intent"
            item = {
                "rank": rank,
                "claim_status": "creative_intent" if intent else "owner_attested",
                "owner_statement": str(owner["text_excerpt"])[:600],
                "subject_key": owner_key,
                "evidence_ids": [evidence_id],
                "source_type": "owner_subject_attestation",
                "reviewed_packet_sha256": owner["reviewed_packet_sha256"],
                "photo_bytes_verified": False,
            }
            findings.append(CreativeSourceFinding(
                source_finding_ref=f"goal-discovery:{discovery_hash}:owner:{evidence_id}",
                result_package_id=f"goal-discovery:{discovery_hash}",
                result_digest=discovery_hash,
                work_package_id=f"goal:{goal.goal_id}",
                finding_rank=rank,
                finding_digest=self._digest(item),
                finding=item,
                evidence_ids=[evidence_id],
            ))
        source = NormalizedCreativeSourceSet(
            project_key=f"goal-{goal.goal_id}",
            result_package_ids=[],
            result_digests=[],
            findings=findings,
            evidence_ids=sorted(set(used)),
            source_set_digest=self._digest({
                "goal_id": goal.goal_id,
                "discovery_result_hash": discovery_hash,
                "synthesis_result_hash": synthesis_hash,
                "findings": [item.finding_digest for item in findings],
                "evidence_ids": sorted(set(used)),
            }),
        )
        job = self.creative.create_goal_job(
            goal_id=goal.goal_id,
            source_set=source,
            discovery_result_hash=discovery_hash,
            synthesis_result_hash=synthesis_hash,
            creative_objective=goal.objective,
            creative_profile=self._profile_for_goal(goal),
        )
        return HandlerResult(
            summary={"goal_id": goal.goal_id, "creative_job_id": job.creative_job_id},
            result_document={
                "schema_version": "1.0",
                "goal_id": goal.goal_id,
                "creative_job_id": job.creative_job_id,
                "source_set_digest": source.source_set_digest,
                "discovery_result_hash": discovery_hash,
                "synthesis_result_hash": synthesis_hash,
                "web_gpt_required": False,
            },
            result_type=self.TASK_TYPE,
            schema_version="1.0",
        )
