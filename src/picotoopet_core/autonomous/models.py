"""Typed contracts for PicotooPet AI autonomous goals."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class GoalOrigin(StrEnum):
    """Who created a durable Goal fact."""

    HUMAN = "human"
    AUTONOMOUS = "autonomous"
    SYSTEM = "system"


class PriorityClass(StrEnum):
    """Stable product priority classes mapped onto the existing queue range."""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"

    @property
    def queue_priority(self) -> int:
        """Return the existing queue priority; lower numbers execute first."""

        return {
            PriorityClass.P0: 0,
            PriorityClass.P1: 100,
            PriorityClass.P2: 300,
            PriorityClass.P3: 600,
            PriorityClass.P4: 900,
        }[self]


class GoalStatus(StrEnum):
    """Durable goal lifecycle independent from physical queue attempts."""

    READY = "Ready"
    RUNNING = "Running"
    PAUSED = "Paused"
    COMPLETED = "Completed"
    DEFERRED = "Deferred"
    CANCELLED = "Cancelled"
    FAILED = "Failed"


class GoalCreate(BaseModel):
    """Replay-safe Goal creation request; execution remains in WorkflowService."""

    model_config = ConfigDict(extra="forbid")

    origin: GoalOrigin
    intent_type: str = Field(min_length=1, max_length=120)
    priority_class: PriorityClass
    objective: str = Field(min_length=1, max_length=4000)
    constraints: dict[str, Any] = Field(default_factory=dict)
    budget_class: str = Field(default="local-first", min_length=1, max_length=100)
    parent_goal_id: str | None = None
    pinned: bool = False
    score: float | None = Field(default=None, ge=0.0, le=100.0)
    idempotency_key: str = Field(min_length=1, max_length=200)


class GoalRecord(BaseModel):
    """Canonical autonomous Goal projection stored by Mac Core."""

    model_config = ConfigDict(extra="forbid")

    goal_id: str
    parent_goal_id: str | None = None
    workflow_id: str | None = None
    origin: GoalOrigin
    intent_type: str
    priority_class: PriorityClass
    objective: str
    constraints: dict[str, Any] = Field(default_factory=dict)
    budget_class: str
    pinned: bool
    score: float | None = None
    status: GoalStatus
    idempotency_key: str
    created_at: datetime
    updated_at: datetime


HumanGoalType = Literal[
    "product.research",
    "consumer.pain_points",
    "business.opportunity",
    "video.creative",
    "product.research_to_video",
]
HumanGoalDepth = Literal["quick", "standard", "deep"]


class HumanGoalCreate(BaseModel):
    """Bounded user-facing Goal request; callers cannot set trust or scheduler fields."""

    model_config = ConfigDict(extra="forbid")

    goal_type: HumanGoalType
    objective: str = Field(min_length=1, max_length=4000)
    depth: HumanGoalDepth = "standard"


class GoalTemplate(BaseModel):
    """One fixed suggestion shown by the Windows Goal Center."""

    model_config = ConfigDict(extra="forbid")

    goal_type: HumanGoalType
    title: str = Field(min_length=1, max_length=120)
    example: str = Field(min_length=1, max_length=500)
