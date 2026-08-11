"""Deterministic structure, provenance, and safety gates for creative stages."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError

from .models import (
    CreativeBriefResult,
    CreativeQualityDecision,
    CreativeQualityOutcome,
    CreativeScriptResult,
    CreativeStageKind,
    IdeaRankingResult,
    ShotPlanResult,
)
from .profiles import CreativeProfileDefinition
from .source import NormalizedCreativeSourceSet


class CreativeQualityGate:
    _MODELS: dict[CreativeStageKind, type[BaseModel]] = {
        CreativeStageKind.IDEA_RANKING: IdeaRankingResult,
        CreativeStageKind.CREATIVE_BRIEF: CreativeBriefResult,
        CreativeStageKind.SCRIPT: CreativeScriptResult,
        CreativeStageKind.SHOT_PLAN: ShotPlanResult,
    }

    def evaluate(
        self,
        *,
        stage_kind: CreativeStageKind,
        profile: CreativeProfileDefinition,
        source_set: NormalizedCreativeSourceSet,
        previous_stages: dict[str, dict[str, Any]],
        raw_result: dict[str, Any],
    ) -> tuple[CreativeQualityDecision, BaseModel | None]:
        model = self._MODELS[stage_kind]
        try:
            parsed = model.model_validate(raw_result)
        except ValidationError as error:
            return self._retry("RESULT_SCHEMA_INVALID", self._validation_correction(error)), None

        if self._contains_forbidden_output(parsed.model_dump(mode="json")):
            return CreativeQualityDecision(
                outcome=CreativeQualityOutcome.REJECT,
                reasons=["CREATIVE_OUTPUT_FORBIDDEN_PAYLOAD"],
            ), None
        if bool(getattr(parsed, "needs_human", False)):
            return CreativeQualityDecision(
                outcome=CreativeQualityOutcome.NEEDS_HUMAN,
                reasons=["MODEL_DECLARED_HUMAN_REVIEW"],
            ), parsed
        if bool(getattr(parsed, "needs_deep_ai", False)):
            return CreativeQualityDecision(
                outcome=CreativeQualityOutcome.NEEDS_DEEP_AI,
                reasons=["MODEL_DECLARED_DEEP_AI"],
            ), parsed

        finding_refs = {item.source_finding_ref for item in source_set.findings}
        evidence_ids = set(source_set.evidence_ids)
        if stage_kind is CreativeStageKind.IDEA_RANKING:
            assert isinstance(parsed, IdeaRankingResult)
            used_findings = {ref for idea in parsed.ideas for ref in idea.source_finding_refs}
            used_evidence = {ref for idea in parsed.ideas for ref in idea.source_evidence_ids}
            if not used_findings <= finding_refs:
                return self._retry("UNKNOWN_SOURCE_FINDING_REF", "Use only supplied source_finding_ref values."), None
            if not used_evidence <= evidence_ids:
                return self._retry("UNKNOWN_SOURCE_EVIDENCE_ID", "Use only supplied evidence IDs."), None
        elif stage_kind is CreativeStageKind.CREATIVE_BRIEF:
            assert isinstance(parsed, CreativeBriefResult)
            idea_raw = previous_stages.get(CreativeStageKind.IDEA_RANKING.value)
            if not idea_raw:
                return self._retry("PRIOR_IDEA_STAGE_MISSING", "Reference the validated idea stage."), None
            idea_ids = {item["idea_id"] for item in idea_raw.get("ideas", [])}
            if parsed.selected_idea_id not in idea_ids:
                return self._retry("SELECTED_IDEA_UNKNOWN", "Select only the validated rank-1 idea ID."), None
            if not set(parsed.required_source_finding_refs) <= finding_refs:
                return self._retry("UNKNOWN_SOURCE_FINDING_REF", "Use only supplied source_finding_ref values."), None
            if not set(parsed.required_source_evidence_ids) <= evidence_ids:
                return self._retry("UNKNOWN_SOURCE_EVIDENCE_ID", "Use only supplied evidence IDs."), None
        elif stage_kind is CreativeStageKind.SCRIPT:
            assert isinstance(parsed, CreativeScriptResult)
            used = {evidence for beat in parsed.beats for evidence in beat.claim_source_evidence_ids}
            if not used <= evidence_ids:
                return self._retry("UNKNOWN_SOURCE_EVIDENCE_ID", "Use only supplied evidence IDs."), None
            if any(beat.claim_source_evidence_ids == [] and beat.unsupported_claim for beat in parsed.beats):
                pass
        elif stage_kind is CreativeStageKind.SHOT_PLAN:
            assert isinstance(parsed, ShotPlanResult)
            script_raw = previous_stages.get(CreativeStageKind.SCRIPT.value)
            if not script_raw:
                return self._retry("PRIOR_SCRIPT_STAGE_MISSING", "Reference the validated script stage."), None
            script_beats = {item["beat_id"] for item in script_raw.get("beats", [])}
            shot_beats = {item.beat_id for item in parsed.shots}
            if not shot_beats <= script_beats:
                return self._retry("UNKNOWN_SCRIPT_BEAT", "Use only validated script beat IDs."), None
            if script_beats - shot_beats:
                return self._retry("SCRIPT_BEAT_NOT_COVERED", "Cover every validated script beat."), None
            used = {evidence for shot in parsed.shots for evidence in shot.source_evidence_ids}
            if not used <= evidence_ids:
                return self._retry("UNKNOWN_SOURCE_EVIDENCE_ID", "Use only supplied evidence IDs."), None

        return CreativeQualityDecision(outcome=CreativeQualityOutcome.PASS), parsed

    @staticmethod
    def _retry(code: str, correction: str) -> CreativeQualityDecision:
        return CreativeQualityDecision(
            outcome=CreativeQualityOutcome.RETRY,
            reasons=[code],
            correction_instruction=correction,
        )

    @staticmethod
    def _validation_correction(error: ValidationError) -> str:
        locations = [
            ".".join(str(part) for part in item.get("loc", ()))
            for item in error.errors(include_url=False)[:10]
        ]
        return "Repair only the strict JSON schema fields: " + ", ".join(filter(None, locations))

    @staticmethod
    def _contains_forbidden_output(value: object) -> bool:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
        markers = (
            "authorization: bearer",
            "system_prompt",
            "comfyworkflow",
            "comfyui workflow",
            "checkpoint_loader",
            "shell=true",
            "powershell.exe",
            "cmd.exe",
            "http://",
            "https://",
            "/users/",
            "c:\\users\\",
        )
        return any(marker in encoded for marker in markers)
