"""Edit plan data models and schema validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field


class SpeedKeypoint(BaseModel):
    """Speed curve keypoint (time in seconds within cut, speed multiplier)."""
    t: float = Field(..., ge=0.0, description="Timestamp in shot cut relative to 'in' point (sec)")
    x: float = Field(..., gt=0.0, description="Playback speed multiplier (e.g. 1.0 = normal, 0.5 = 2x slow mo, 2.0 = 2x speed)")


class PunchInSpec(BaseModel):
    """Dynamic zoom punch-in effect."""
    t: float = Field(..., ge=0.0, description="Start timestamp of punch-in (sec)")
    scale: float = Field(default=1.15, gt=1.0, le=2.5, description="Target zoom factor")
    dur: float = Field(default=0.3, gt=0.0, description="Duration of easing zoom transition (sec)")


class TransitionSpec(BaseModel):
    """Shot outgoing transition specification."""
    type: str = Field(default="hard", description="Transition type: hard, whip, match, j_cut, l_cut")
    dur: float = Field(default=0.25, ge=0.0, description="Transition duration in seconds")
    dir: str = Field(default="left", description="Direction for directional transitions (left, right, up, down)")
    offset: float = Field(default=0.3, description="Offset seconds for J-cut / L-cut audio leads/tails")


class CaptionSpec(BaseModel):
    """Subtitle item specification."""
    text: str = Field(..., description="Subtitle text")
    start: float = Field(..., ge=0.0, description="Start timestamp relative to shot cut start (sec)")
    end: float = Field(..., ge=0.0, description="End timestamp relative to shot cut start (sec)")
    y_ratio: float = Field(default=0.20, ge=0.0, le=1.0, description="Vertical anchor ratio from canvas top")


class AudioTrackSpec(BaseModel):
    """Audio clip track reference with gain."""
    file: Optional[str] = Field(default=None, description="Path to audio file (flac, wav, mp3)")
    from_video: Optional[str] = Field(default=None, alias="from", description="Extract audio from specified video")
    gain_db: float = Field(default=0.0, description="Gain adjustment in decibels")

    model_config = ConfigDict(populate_by_name=True)


class SFXSpec(BaseModel):
    """Spot sound effect placed at timeline timestamp."""
    file: str = Field(..., description="Path to sound effect audio file")
    at: float = Field(..., ge=0.0, description="Timeline timestamp to trigger sound effect (sec)")
    gain_db: float = Field(default=0.0, description="Gain in dB")


class MusicSpec(BaseModel):
    """Background music bus specification with sidechain ducking."""
    file: str = Field(..., description="Background music file path")
    gain_db: float = Field(default=-16.0, description="Base music gain in dB")
    duck_under_vocal_db: float = Field(default=-8.0, description="Attenuation dB when vocal is active")


class ShotPlan(BaseModel):
    """Plan for a single video shot."""
    shot_id: str = Field(..., description="Unique shot identifier (e.g. S01, S02)")
    video: str = Field(..., description="Path to source video file")
    in_point: float = Field(default=0.0, alias="in", ge=0.0, description="Source video in-point (sec)")
    out_point: float = Field(..., alias="out", gt=0.0, description="Source video out-point (sec)")
    vocal: Optional[AudioTrackSpec] = Field(default=None, description="Dog vocal audio bus track")
    foley: Optional[AudioTrackSpec] = Field(default=None, description="Foley action sound track")
    speed: Optional[List[SpeedKeypoint]] = Field(default=None, description="Speed curve keypoints")
    punch_in: Optional[PunchInSpec] = Field(default=None, description="Punch-in zoom effect")
    transition_out: Optional[TransitionSpec] = Field(default=None, description="Outgoing transition to next shot")
    caption: Optional[CaptionSpec] = Field(default=None, description="Subtitle for this shot")

    model_config = ConfigDict(populate_by_name=True)

    @property
    def source_duration(self) -> float:
        return max(0.0, self.out_point - self_point if hasattr(self, "self_point") else self.out_point - self.in_point)


class EditPlan(BaseModel):
    """Complete multi-shot edit assembly plan."""
    size: Tuple[int, int] = Field(default=(1080, 1920), description="Canvas resolution [width, height]")
    fps: int = Field(default=30, gt=0, description="Output video frame rate")
    loudness_lufs: float = Field(default=-14.0, description="Final integrated loudness target in LUFS")
    font: Optional[str] = Field(default=None, description="Font file path for subtitles")
    shots: List[ShotPlan] = Field(..., min_length=1, description="List of shots to assemble")
    music: Optional[MusicSpec] = Field(default=None, description="Background music configuration")
    sfx: List[SFXSpec] = Field(default_factory=list, description="Global sound effects list")

    @classmethod
    def from_file(cls, path: str | Path) -> EditPlan:
        """Load EditPlan from JSON file."""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Edit plan file not found: {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)
