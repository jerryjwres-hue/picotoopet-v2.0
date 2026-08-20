"""Durable Superpower v1.0 task-progress contracts."""

from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

_MAX_DETAILS_BYTES = 4 * 1024


class ProgressUpdate(BaseModel):
    """One truthful progress observation emitted by a bounded Worker stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str = Field(min_length=1, max_length=200)
    stage: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    completed: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=1)
    message: str = Field(min_length=1, max_length=500)
    component: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    details: dict[str, JsonValue] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def _validate_truthful_bounds(self) -> ProgressUpdate:
        # ── A numerator without a verifiable denominator would create a fake percent. ──
        if self.completed is not None and self.total is None:
            raise ValueError("completed requires total")
        if self.completed is not None and self.total is not None and self.completed > self.total:
            raise ValueError("completed must not exceed total")
        encoded = json.dumps(
            self.details,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_DETAILS_BYTES:
            raise ValueError("progress details exceed 4096 bytes")
        return self


class ProgressEvent(BaseModel):
    """One immutable Core-owned progress fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    sequence: int = Field(ge=1)
    stage: str
    completed: int | None = None
    total: int | None = None
    message: str
    component: str
    details: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime


class ProgressSnapshot(BaseModel):
    """Bounded latest task progress plus recent durable activity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str
    stage: str | None = None
    completed: int | None = None
    total: int | None = None
    percent: float | None = Field(default=None, ge=0.0, le=100.0)
    latest_message: str | None = None
    component: str | None = None
    last_activity_at: datetime | None = None
    recent_events: list[ProgressEvent] = Field(default_factory=list, max_length=50)
