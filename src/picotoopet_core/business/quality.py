"""Deterministic post-inference validation for local business intelligence."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from .models import BusinessQualityDecision, BusinessQualityOutcome
from .preprocess import PreprocessedAnalysis
from .profiles import AnalysisProfileDefinition, LocalIntelligenceResult


class BusinessQualityGate:
    """Validate structure/evidence deterministically; do not perform model inference."""

    def evaluate(
        self,
        profile: AnalysisProfileDefinition,
        preprocessed: PreprocessedAnalysis,
        model_result: dict[str, Any],
    ) -> tuple[BusinessQualityDecision, LocalIntelligenceResult | None]:
        try:
            parsed = LocalIntelligenceResult.model_validate(model_result)
        except ValidationError as error:
            return (
                BusinessQualityDecision(
                    outcome=BusinessQualityOutcome.RETRY,
                    reasons=["RESULT_SCHEMA_INVALID"],
                    correction_instruction=self._validation_correction(error),
                ),
                None,
            )
        if parsed.analysis_profile is not profile.profile_id:
            return (
                BusinessQualityDecision(
                    outcome=BusinessQualityOutcome.RETRY,
                    reasons=["RESULT_PROFILE_MISMATCH"],
                    correction_instruction="Return the exact requested analysis_profile and preserve all evidence IDs.",
                ),
                None,
            )

        known_evidence = {item.evidence_id for item in preprocessed.evidence_records}
        unknown = sorted(
            {
                evidence_id
                for finding in parsed.findings
                for evidence_id in finding.evidence_ids
                if evidence_id not in known_evidence
            }
        )
        if unknown:
            return (
                BusinessQualityDecision(
                    outcome=BusinessQualityOutcome.RETRY,
                    reasons=["UNKNOWN_EVIDENCE_ID"],
                    correction_instruction=(
                        "Use only evidence_ids present in the supplied evidence. Unknown IDs: "
                        + ", ".join(unknown[:10])
                    ),
                ),
                None,
            )

        ranks = [finding.rank for finding in parsed.findings]
        if len(ranks) != len(set(ranks)) or sorted(ranks) != list(range(1, len(ranks) + 1)):
            return (
                BusinessQualityDecision(
                    outcome=BusinessQualityOutcome.RETRY,
                    reasons=["FINDING_RANKS_INVALID"],
                    correction_instruction="Use unique consecutive ranks starting at 1.",
                ),
                None,
            )

        encoded = json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False).lower()
        leak_markers = (
            "you are picotoopet local intelligence",
            "authorization: bearer",
            "api_token",
            "system_prompt",
            "response_format",
        )
        if any(marker in encoded for marker in leak_markers):
            return (
                BusinessQualityDecision(
                    outcome=BusinessQualityOutcome.REJECT,
                    reasons=["INTERNAL_METADATA_LEAK"],
                ),
                None,
            )

        if parsed.needs_human:
            return (
                BusinessQualityDecision(
                    outcome=BusinessQualityOutcome.NEEDS_HUMAN,
                    reasons=["MODEL_DECLARED_HUMAN_REVIEW"],
                ),
                parsed,
            )
        if parsed.needs_deep_ai:
            return (
                BusinessQualityDecision(
                    outcome=BusinessQualityOutcome.NEEDS_DEEP_AI,
                    reasons=["MODEL_DECLARED_DEEP_AI"],
                ),
                parsed,
            )
        return BusinessQualityDecision(outcome=BusinessQualityOutcome.PASS), parsed

    @staticmethod
    def _validation_correction(error: ValidationError) -> str:
        locations = []
        for item in error.errors(include_url=False)[:10]:
            location = ".".join(str(part) for part in item.get("loc", ()))
            if location:
                locations.append(location)
        suffix = ", ".join(locations) or "unknown fields"
        return f"Repair only the JSON schema errors at: {suffix}. Do not invent evidence IDs."
