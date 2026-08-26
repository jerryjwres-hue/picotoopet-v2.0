from __future__ import annotations

import importlib
import importlib.util


def _api():
    module_name = "picotoopet_core.deep_ai.frugal"
    spec = importlib.util.find_spec(module_name)
    assert spec is not None, "frugal escalation module must exist"
    module = importlib.import_module(module_name)
    return (
        module.FrugalAssessmentSignals,
        module.FrugalEscalationArbiter,
        module.FrugalEscalationInput,
        module.ProviderCandidate,
        module.ProviderHistorySnapshot,
        module.wilson95,
    )


def _candidate(provider: str, *, successes: int = 0, trials: int = 0):
    (
        _signals,
        _arbiter,
        _input,
        ProviderCandidate,
        ProviderHistorySnapshot,
        _wilson,
    ) = _api()
    return ProviderCandidate(
        provider=provider,
        readiness="ready",
        expected_quality_uplift=0.45,
        history=ProviderHistorySnapshot(success_count=successes, sample_size=trials),
        cost_penalty=0.10,
        latency_penalty=0.10,
        permission_risk=0.10,
    )


def _input(
    *,
    task_class: str = "repository_maintenance",
    validation_passed: bool = False,
    coverage: float = 0.70,
    contradiction_rate: float = 0.10,
    model_confidence: float = 0.65,
    risk_score: float = 0.30,
    retry_count: int = 0,
    sessions_used: int = 0,
    attempted_providers: tuple[str, ...] = (),
    previous_validation_outcome: str | None = None,
):
    (
        FrugalAssessmentSignals,
        _arbiter,
        FrugalEscalationInput,
        _candidate_type,
        _history,
        _wilson,
    ) = _api()
    return FrugalEscalationInput(
        goal_id="goal-frugal-1",
        task_class=task_class,
        signals=FrugalAssessmentSignals(
            contract_valid=True,
            validation_passed=validation_passed,
            coverage=coverage,
            contradiction_rate=contradiction_rate,
            model_confidence=model_confidence,
            risk_score=risk_score,
            retry_count=retry_count,
        ),
        candidates=[_candidate("codex"), _candidate("claude_code")],
        sessions_used=sessions_used,
        attempted_providers=attempted_providers,
        previous_validation_outcome=previous_validation_outcome,
    )


def test_wilson95_is_conservative_for_zero_and_small_samples() -> None:
    *_rest, wilson95 = _api()

    assert wilson95(0, 0) == (0.0, 1.0)
    lower, upper = wilson95(8, 10)
    assert lower == pytest.approx(0.490162, abs=1e-6)
    assert upper == pytest.approx(0.943318, abs=1e-6)


def test_non_coding_work_is_never_eligible_for_coding_agents() -> None:
    _signals, FrugalEscalationArbiter, *_rest = _api()

    decision = FrugalEscalationArbiter().decide(
        _input(task_class="product_research", validation_passed=False)
    )

    assert decision.eligibility is False
    assert decision.chosen_provider == "none"
    assert decision.action == "local_only"
    assert "NOT_ELIGIBLE_FOR_CODING_AGENT" in decision.reason_codes


def test_high_confidence_validated_local_work_prohibits_external_spend() -> None:
    _signals, FrugalEscalationArbiter, *_rest = _api()

    decision = FrugalEscalationArbiter().decide(
        _input(
            validation_passed=True,
            coverage=1.0,
            contradiction_rate=0.0,
            model_confidence=0.95,
            risk_score=0.0,
        )
    )

    assert decision.local_quality_score >= 90.0
    assert decision.confidence_lower >= 0.80
    assert decision.chosen_provider == "none"
    assert decision.action == "local_only"
    assert "LOCAL_CONFIDENCE_SUFFICIENT" in decision.reason_codes


def test_cold_start_equal_utility_prefers_existing_codex_path_once() -> None:
    _signals, FrugalEscalationArbiter, *_rest = _api()

    decision = FrugalEscalationArbiter().decide(_input())

    assert decision.eligibility is True
    assert decision.chosen_provider == "codex"
    assert decision.action == "external_provider"
    assert decision.external_sessions_remaining == 1


def test_provider_pass_stops_spending_even_when_second_provider_is_ready() -> None:
    _signals, FrugalEscalationArbiter, *_rest = _api()

    decision = FrugalEscalationArbiter().decide(
        _input(
            sessions_used=1,
            attempted_providers=("codex",),
            previous_validation_outcome="pass",
        )
    )

    assert decision.chosen_provider == "none"
    assert decision.action == "local_only"
    assert "PROVIDER_RETURN_VALIDATED" in decision.reason_codes


def test_second_provider_requires_failed_validation_and_never_exceeds_two_sessions() -> None:
    _signals, FrugalEscalationArbiter, *_rest = _api()

    second = FrugalEscalationArbiter().decide(
        _input(
            sessions_used=1,
            attempted_providers=("codex",),
            previous_validation_outcome="failed",
        )
    )
    capped = FrugalEscalationArbiter().decide(
        _input(
            sessions_used=2,
            attempted_providers=("codex", "claude_code"),
            previous_validation_outcome="failed",
        )
    )

    assert second.chosen_provider == "claude_code"
    assert second.external_sessions_remaining == 0
    assert capped.chosen_provider == "none"
    assert capped.action == "manual_review"
    assert "EXTERNAL_SESSION_CAP_REACHED" in capped.reason_codes


# Keep pytest import last so the module-under-test absence is the RED condition, not collection.
import pytest
