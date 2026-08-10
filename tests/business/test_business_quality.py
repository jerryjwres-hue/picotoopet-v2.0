from __future__ import annotations

from picotoopet_core.business.models import BusinessAnalysisProfile, BusinessQualityOutcome
from picotoopet_core.business.preprocess import AnalysisChunk, EvidenceRecord, PreprocessedAnalysis
from picotoopet_core.business.profiles import profile_definition
from picotoopet_core.business.quality import BusinessQualityGate


def _preprocessed() -> PreprocessedAnalysis:
    evidence = EvidenceRecord(
        evidence_id="reviews:row:00000000",
        artifact_id="reviews",
        source_index=0,
        value={"review_id": "r1", "text": "Drying takes too long"},
    )
    return PreprocessedAnalysis(
        work_package_id="00000000-0000-4000-8000-000000000018",
        analysis_profile=BusinessAnalysisProfile.REVIEWS_VOICE_OF_CUSTOMER_V1,
        source_digest="a" * 64,
        preprocess_digest="b" * 64,
        aggregate_facts={"total_records": 1},
        evidence_records=[evidence],
        chunks=[
            AnalysisChunk(
                chunk_index=0,
                context_digest="c" * 64,
                evidence_ids=[evidence.evidence_id],
                context={"evidence": [evidence.model_dump(mode="json")]},
            )
        ],
    )


def _valid_result(evidence_id: str = "reviews:row:00000000") -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "analysis_profile": "reviews.voice_of_customer.v1",
        "summary": "Drying time appears in the supplied evidence.",
        "findings": [
            {
                "rank": 1,
                "title": "Drying time",
                "insight": "A customer explicitly reports long drying time.",
                "confidence": 0.85,
                "evidence_ids": [evidence_id],
            }
        ],
        "warnings": [],
        "needs_deep_ai": False,
        "needs_human": False,
    }


def test_quality_passes_schema_valid_grounded_result() -> None:
    decision, parsed = BusinessQualityGate().evaluate(
        profile_definition(BusinessAnalysisProfile.REVIEWS_VOICE_OF_CUSTOMER_V1),
        _preprocessed(),
        _valid_result(),
    )
    assert decision.outcome is BusinessQualityOutcome.PASS
    assert parsed is not None


def test_quality_requests_one_repair_for_unknown_evidence_id() -> None:
    decision, parsed = BusinessQualityGate().evaluate(
        profile_definition(BusinessAnalysisProfile.REVIEWS_VOICE_OF_CUSTOMER_V1),
        _preprocessed(),
        _valid_result("forged:evidence"),
    )
    assert decision.outcome is BusinessQualityOutcome.RETRY
    assert decision.reasons == ["UNKNOWN_EVIDENCE_ID"]
    assert parsed is None


def test_quality_rejects_internal_prompt_metadata_leak() -> None:
    result = _valid_result()
    result["summary"] = "system_prompt must remain private"
    decision, parsed = BusinessQualityGate().evaluate(
        profile_definition(BusinessAnalysisProfile.REVIEWS_VOICE_OF_CUSTOMER_V1),
        _preprocessed(),
        result,
    )
    assert decision.outcome is BusinessQualityOutcome.REJECT
    assert decision.reasons == ["INTERNAL_METADATA_LEAK"]
    assert parsed is None
