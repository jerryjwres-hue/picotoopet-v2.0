"""Autonomous research must stop when information gain is exhausted or the hard round cap is reached."""

from __future__ import annotations

import pytest

from picotoopet_core.autonomous.research_stop import (
    ResearchRound,
    ResearchStopReason,
    evaluate_research_stop,
)


def _round(number: int, gain: float) -> ResearchRound:
    return ResearchRound(
        round_number=number,
        evidence_ids=[f"evidence-{number}"],
        cluster_ids=[f"cluster-{number}"],
        information_gain_ratio=gain,
    )


def test_two_consecutive_sub_five_percent_gains_stop_deepening() -> None:
    decision = evaluate_research_stop(
        [_round(0, 1.0), _round(1, 0.04), _round(2, 0.049)]
    )

    assert decision.stop is True
    assert decision.reason is ResearchStopReason.LOW_INFORMATION_GAIN
    assert decision.next_round is None


def test_a_five_percent_or_higher_round_resets_low_gain_streak() -> None:
    decision = evaluate_research_stop(
        [
            _round(0, 1.0),
            _round(1, 0.04),
            _round(2, 0.05),
        ]
    )

    assert decision.stop is False
    assert decision.reason is ResearchStopReason.CONTINUE
    assert decision.next_round == 3


def test_hard_stop_after_three_deepening_rounds_beyond_initial_collection() -> None:
    decision = evaluate_research_stop(
        [
            _round(0, 1.0),
            _round(1, 0.9),
            _round(2, 0.8),
            _round(3, 0.7),
        ]
    )

    assert decision.stop is True
    assert decision.reason is ResearchStopReason.MAX_DEEPENING_ROUNDS
    assert decision.next_round is None


def test_initial_collection_can_continue_to_first_deepening_round() -> None:
    decision = evaluate_research_stop([_round(0, 1.0)])

    assert decision.stop is False
    assert decision.reason is ResearchStopReason.CONTINUE
    assert decision.next_round == 1


@pytest.mark.parametrize("gain", [-0.01, 1.01, float("inf"), float("-inf")])
def test_round_contract_rejects_invalid_information_gain(gain: float) -> None:
    with pytest.raises(ValueError):
        _round(0, gain)


def test_round_sequence_must_begin_at_zero_and_be_strictly_consecutive() -> None:
    with pytest.raises(ValueError, match="initial round"):
        evaluate_research_stop([_round(1, 0.5)])
    with pytest.raises(ValueError, match="consecutive"):
        evaluate_research_stop([_round(0, 1.0), _round(2, 0.5)])


def test_empty_history_requests_initial_collection_without_guessing_gain() -> None:
    decision = evaluate_research_stop([])

    assert decision.stop is False
    assert decision.reason is ResearchStopReason.CONTINUE
    assert decision.next_round == 0
