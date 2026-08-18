"""Research Priority Score must be deterministic and honest about missing evidence."""

from __future__ import annotations

import pytest

from picotoopet_core.autonomous.content_radar import (
    RadarDecision,
    RadarScoreSignals,
    score_candidate,
)


def test_exact_weight_mapping_reaches_100_only_with_all_maximum_signals() -> None:
    score = score_candidate(
        RadarScoreSignals(
            trend_velocity=1.0,
            audience_resonance=1.0,
            novelty=1.0,
            business_relevance=1.0,
            evidence_quality=1.0,
            cross_platform=1.0,
            actionability=1.0,
        )
    )

    assert score.component_points == {
        "trend_velocity": 20.0,
        "audience_resonance": 20.0,
        "novelty": 15.0,
        "business_relevance": 15.0,
        "evidence_quality": 10.0,
        "cross_platform": 10.0,
        "actionability": 10.0,
    }
    assert score.total == 100.0
    assert score.coverage == 1.0
    assert score.decision is RadarDecision.DEEP_RESEARCH


def test_threshold_boundaries_are_exactly_85_and_70() -> None:
    deep = score_candidate(
        RadarScoreSignals(
            trend_velocity=1.0,
            audience_resonance=1.0,
            novelty=1.0,
            business_relevance=1.0,
            evidence_quality=0.5,
            cross_platform=0.5,
            actionability=0.5,
        )
    )
    shallow = score_candidate(
        RadarScoreSignals(
            trend_velocity=1.0,
            audience_resonance=1.0,
            novelty=1.0,
            business_relevance=1.0,
            evidence_quality=0.0,
            cross_platform=0.0,
            actionability=0.0,
        )
    )
    low = score_candidate(
        RadarScoreSignals(
            trend_velocity=1.0,
            audience_resonance=1.0,
            novelty=1.0,
            business_relevance=0.99,
            evidence_quality=0.0,
            cross_platform=0.0,
            actionability=0.0,
        )
    )

    assert deep.total == 85.0
    assert deep.decision is RadarDecision.DEEP_RESEARCH
    assert shallow.total == 70.0
    assert shallow.decision is RadarDecision.SHALLOW_VALIDATION
    assert low.total == 69.85
    assert low.decision is RadarDecision.RETAIN_SIGNAL


def test_missing_signals_contribute_zero_and_reduce_weighted_coverage() -> None:
    score = score_candidate(
        RadarScoreSignals(
            trend_velocity=0.5,
            audience_resonance=None,
            novelty=None,
            business_relevance=1.0,
            evidence_quality=None,
            cross_platform=None,
            actionability=None,
        )
    )

    assert score.component_points["trend_velocity"] == 10.0
    assert score.component_points["business_relevance"] == 15.0
    assert score.component_points["audience_resonance"] == 0.0
    assert score.total == 25.0
    # Only the 20-point velocity and 15-point business dimensions had evidence.
    assert score.coverage == 0.35
    assert score.decision is RadarDecision.RETAIN_SIGNAL


@pytest.mark.parametrize("value", [-0.01, 1.01, float("inf"), float("-inf")])
def test_signal_contract_rejects_out_of_range_or_non_finite_values(value: float) -> None:
    with pytest.raises(ValueError):
        RadarScoreSignals(trend_velocity=value)


def test_score_rounding_is_stable_to_two_decimal_places() -> None:
    score = score_candidate(
        RadarScoreSignals(
            trend_velocity=0.333333,
            audience_resonance=0.666666,
        )
    )

    assert score.component_points["trend_velocity"] == 6.67
    assert score.component_points["audience_resonance"] == 13.33
    assert score.total == 20.0
    assert score.coverage == 0.4
