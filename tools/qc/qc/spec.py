"""Shot specification data structures and schema validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class ShotExpectation(BaseModel):
    """Expected counts of objects and visibility requirements."""
    model_config = ConfigDict(extra="allow")

    dogs: int = Field(default=0, ge=0, description="Expected number of dogs (Maotai)")
    people: int = Field(default=0, ge=0, description="Expected number of people")
    bowls: int = Field(default=0, ge=0, description="Expected number of food/water bowls")
    balls: int = Field(default=0, ge=0, description="Expected number of balls/toys")
    faces_visible: bool = Field(default=False, description="Whether human faces are allowed/expected")


class CaptionSpec(BaseModel):
    """Subtitle text and vertical layout position ratio."""
    text: str = Field(..., description="Subtitle text")
    y_ratio: float = Field(default=0.20, ge=0.0, le=1.0, description="Y-coordinate anchor ratio from top")
    start: Optional[float] = Field(default=None, description="Start timestamp in seconds")
    end: Optional[float] = Field(default=None, description="End timestamp in seconds")


class ShotSpec(BaseModel):
    """Complete specification for a single shot QC check."""
    shot_id: str = Field(..., description="Unique identifier of the shot (e.g. S01, S03)")
    check_entity_counts: bool = True
    expect: ShotExpectation = Field(default_factory=ShotExpectation, description="Expected entity presence")
    identity_refs: Dict[str, str] = Field(default_factory=dict, description="Reference images for identity verification")
    min_motion: float = Field(default=0.15, ge=0.0, description="Minimum acceptable optical flow magnitude")
    max_motion: float = Field(default=2.5, ge=0.0, description="Maximum acceptable optical flow magnitude")
    caption: Optional[CaptionSpec] = Field(default=None, description="Subtitle specifications")
    allow_light_change: bool = Field(default=False, description="Whether intra-shot light/brightness change is allowed")
    fps_sample: float = Field(default=4.0, gt=0, description="Sampling rate in frames per second")

    @classmethod
    def from_file(cls, path: str | Path) -> ShotSpec:
        """Load and parse ShotSpec from a JSON file."""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Shot specification file not found: {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)
