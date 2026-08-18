"""Deterministic information-gain stop policy for bounded autonomous research."""

from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

_LOW_INFORMATION_GAIN = 0.05
_MAX_DEEPENING_ROUNDS = 3


class ResearchStopReason(StrEnum):
    """Auditable reasons for either continuing or stopping research deepening."""

    CONTINUE = "continue"
    LOW_INFORMATION_GAIN = "low_information_gain"
    MAX_DEEPENING_ROUNDS = "max_deepening_rounds"


class ResearchRound(BaseModel):
    """One completed research round with measured, not model-invented, information gain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    round_number: int = Field(ge=0, le=_MAX_DEEPENING_ROUNDS)
    evidence_ids: list[str] = Field(default_factory=list, max_length=2_000)
    cluster_ids: list[str] = Field(default_factory=list, max_length=500)
    information_gain_ratio: float

    @field_validator("information_gain_ratio")
    @classmethod
    def _bounded_gain(cls, value: float) -> float:
        normalized = float(value)
        if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
            raise ValueError("information gain must be a finite ratio between 0 and 1")
        return normalized


class ResearchStopDecision(BaseModel):
    """Deterministic decision consumed by the orchestrator; no provider call is involved."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stop: bool
    reason: ResearchStopReason
    next_round: int | None = Field(default=None, ge=0, le=_MAX_DEEPENING_ROUNDS)


def evaluate_research_stop(rounds: list[ResearchRound]) -> ResearchStopDecision:
    """Stop after two low-gain rounds or three deepening rounds beyond round zero."""

    if not rounds:
        return ResearchStopDecision(
            stop=False,
            reason=ResearchStopReason.CONTINUE,
            next_round=0,
        )

    if rounds[0].round_number != 0:
        raise ValueError("research history must begin with the initial round 0")
    for expected, item in enumerate(rounds):
        if item.round_number != expected:
            raise ValueError("research round numbers must be strictly consecutive")

    latest = rounds[-1]
    if latest.round_number >= _MAX_DEEPENING_ROUNDS:
        return ResearchStopDecision(
            stop=True,
            reason=ResearchStopReason.MAX_DEEPENING_ROUNDS,
            next_round=None,
        )

    if len(rounds) >= 3:
        previous = rounds[-2]
        if (
            previous.round_number > 0
            and previous.information_gain_ratio < _LOW_INFORMATION_GAIN
            and latest.information_gain_ratio < _LOW_INFORMATION_GAIN
        ):
            return ResearchStopDecision(
                stop=True,
                reason=ResearchStopReason.LOW_INFORMATION_GAIN,
                next_round=None,
            )

    return ResearchStopDecision(
        stop=False,
        reason=ResearchStopReason.CONTINUE,
        next_round=latest.round_number + 1,
    )
