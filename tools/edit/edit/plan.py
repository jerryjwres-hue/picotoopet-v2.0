"""Edit plan data models, schema validation, and Claude plan converter."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import cv2
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger("edit.plan")


class SpeedKeypoint(BaseModel):
    """Speed curve keypoint (time in seconds within cut, speed multiplier)."""
    t: float = Field(..., ge=0.0, description="Timestamp in shot cut relative to 'in' point (sec)")
    x: float = Field(..., gt=0.0, description="Playback speed multiplier")


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
    start: float = Field(default=0.0, ge=0.0, description="Start timestamp relative to shot cut start (sec)")
    end: float = Field(default=999.0, ge=0.0, description="End timestamp relative to shot cut start (sec)")
    y_ratio: float = Field(default=0.20, ge=0.0, le=1.0, alias="y", description="Vertical anchor ratio from canvas top")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class AudioTrackSpec(BaseModel):
    """Audio clip track reference with gain."""
    file: Optional[str] = Field(default=None, description="Path to audio file (flac, wav, mp3)")
    from_video: Optional[str] = Field(default=None, alias="from", description="Extract audio from specified video")
    gain_db: float = Field(default=0.0, alias="db", description="Gain adjustment in decibels")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class SFXSpec(BaseModel):
    """Spot sound effect placed at timeline timestamp."""
    file: str = Field(..., description="Path to sound effect audio file")
    at: float = Field(..., ge=0.0, description="Timeline timestamp to trigger sound effect (sec)")
    gain_db: float = Field(default=0.0, alias="db", description="Gain in dB")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class MusicSpec(BaseModel):
    """Single background music bus specification with sidechain ducking."""
    file: str = Field(..., description="Background music file path")
    gain_db: float = Field(default=-16.0, alias="db", description="Base music gain in dB")
    duck_under_vocal_db: float = Field(default=-8.0, description="Attenuation dB when vocal is active")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class MusicCue(BaseModel):
    """Individual background music cue aligned to shots or timeline."""
    file: str = Field(..., description="Background music audio file path")
    shot: Optional[int] = Field(default=None, description="Shot index on which to anchor music start")
    at: Optional[float] = Field(default=None, description="Timeline timestamp in seconds")
    offset: float = Field(default=0.0, description="Offset relative to shot start (sec)")
    in_point: float = Field(default=0.0, alias="in", description="Audio in-point (sec)")
    dur: Optional[float] = Field(default=None, description="Duration in seconds")
    gain_db: float = Field(default=-14.0, alias="db", description="Music gain in dB")
    fade_in: float = Field(default=0.3, description="Fade-in duration in seconds")
    fade_out: float = Field(default=0.8, description="Fade-out duration in seconds")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class ShotPlan(BaseModel):
    """Plan for a single video shot."""
    shot_id: str = Field(..., description="Unique shot identifier (e.g. S01, S02)")
    video: str = Field(..., description="Path to source video file")
    in_point: float = Field(default=0.0, alias="in", ge=0.0, description="Source video in-point (sec)")
    out_point: float = Field(..., alias="out", gt=0.0, description="Source video out-point (sec)")
    audio_offset: float = Field(default=0.0, description="Audio offset in seconds (negative = J-cut, audio leads picture)")
    vocal: Optional[AudioTrackSpec] = Field(default=None, description="Dog vocal audio bus track")
    foley: Optional[AudioTrackSpec] = Field(default=None, description="Foley action sound track")
    speed: Optional[List[SpeedKeypoint]] = Field(default=None, description="Speed curve keypoints")
    punch_in: Optional[PunchInSpec] = Field(default=None, description="Punch-in zoom effect")
    transition_out: Optional[TransitionSpec] = Field(default=None, description="Outgoing transition to next shot")
    caption: Optional[CaptionSpec] = Field(default=None, description="Subtitle for this shot")

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    @property
    def source_duration(self) -> float:
        return max(0.0, self.out_point - self.in_point)


class EditPlan(BaseModel):
    """Complete multi-shot edit assembly plan."""
    size: Tuple[int, int] = Field(default=(1080, 1920), description="Canvas resolution [width, height]")
    fps: int = Field(default=24, gt=0, description="Output video frame rate")
    loudness_lufs: float = Field(default=-14.0, description="Final integrated loudness target in LUFS")
    font: Optional[str] = Field(default=None, description="Font file path for subtitles")
    shots: List[ShotPlan] = Field(..., min_length=1, description="List of shots to assemble")
    music: Optional[Union[MusicSpec, List[MusicCue], MusicCue]] = Field(default=None, description="Background music configuration")
    sfx: List[SFXSpec] = Field(default_factory=list, description="Global sound effects list")

    model_config = ConfigDict(extra="allow")

    @classmethod
    def from_file(cls, path: str | Path) -> EditPlan:
        """Load EditPlan from JSON file, supporting both standard and Claude formats."""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Edit plan file not found: {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Detect Claude plan format: has 'root' or shots lack 'shot_id'
        if "root" in data or (data.get("shots") and "shot_id" not in data["shots"][0]):
            return convert_claude_plan(data, p)

        return cls(**data)


def probe_video_duration(video_path: Path | str) -> float:
    """Helper to probe media duration in seconds."""
    p = Path(video_path)
    if not p.is_file():
        return 3.0
    cap = cv2.VideoCapture(str(p))
    if cap.isOpened():
        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        if total_frames > 0 and fps > 0:
            return float(total_frames / fps)
    return 3.0


def resolve_media_root(raw_root: str, plan_file_path: Path) -> Path:
    """Resolve project media root folder across Windows/Linux path mappings."""
    if raw_root and Path(raw_root).is_dir():
        return Path(raw_root)

    candidates = [
        plan_file_path.parent.parent,
        plan_file_path.parent,
        Path(r"D:\opc in D\LTX\电影项目\茅台晚餐_连续性V2"),
    ]
    for cand in candidates:
        if cand.is_dir() and ((cand / "24_场景包").is_dir() or (cand / "22_声音").is_dir()):
            return cand

    return plan_file_path.parent


def convert_claude_plan(data: Dict[str, Any], plan_path: Path) -> EditPlan:
    """Convert Claude cut plan format (e.g. plan_e01_v2.json) into standard EditPlan."""
    base_dir = resolve_media_root(data.get("root", ""), plan_path)

    # 1. Convert shots
    shots: List[ShotPlan] = []
    for idx, s in enumerate(data.get("shots", [])):
        shot_id = f"S{idx + 1:02d}"
        v_rel = s["video"]
        v_abs = str((base_dir / v_rel).resolve()) if not Path(v_rel).is_absolute() else v_rel

        in_pt = float(s.get("in", 0.0))
        out_pt = float(s.get("out", probe_video_duration(v_abs)))
        audio_offset = float(s.get("audio_offset", 0.0))

        # Audio vocal / ltx track
        ltx_db = float(s.get("ltx_db", 0.0))
        vocal = AudioTrackSpec(from_video=v_abs, gain_db=ltx_db)

        # Foley track
        foley = None
        if "foley" in s and s["foley"]:
            f_file = s["foley"]["file"]
            f_abs = str((base_dir / f_file).resolve()) if not Path(f_file).is_absolute() else f_file
            foley = AudioTrackSpec(file=f_abs, gain_db=float(s["foley"].get("db", -3.0)))

        # Speed
        speed = None
        if "speed" in s and s["speed"] is not None:
            sp = s["speed"]
            if isinstance(sp, (int, float)):
                speed = [SpeedKeypoint(t=0.0, x=float(sp))]
            elif isinstance(sp, list):
                speed = [SpeedKeypoint(**k) for k in sp]

        # Punch in
        punch_in = None
        if "punch_in" in s and s["punch_in"]:
            punch_in = PunchInSpec(**s["punch_in"])

        # Caption
        caption = None
        if "caption" in s and s["caption"]:
            cap = s["caption"]
            caption = CaptionSpec(
                text=cap["text"],
                start=float(cap.get("start", 0.2)),
                end=float(cap.get("end", 99.0)),
                y_ratio=float(cap.get("y", cap.get("y_ratio", 0.20))),
            )

        # Transition out
        transition_out = None
        if "transition_out" in s and s["transition_out"]:
            tr = s["transition_out"]
            if isinstance(tr, str):
                tr_lower = tr.lower()
                XF = {
                    "whip_left": ("whip", 0.18, "left"),
                    "whip_right": ("whip", 0.18, "right"),
                    "whip_up": ("whip", 0.18, "up"),
                    "whip_down": ("whip", 0.18, "down"),
                    "match": ("match", 0.16, "left"),
                    "cut": ("hard", 0.04, "left"),
                    "hard": ("hard", 0.04, "left"),
                    "dip": ("hard", 0.30, "left"),
                    "zoom": ("whip", 0.25, "left"),
                }
                t_type, t_dur, t_dir = XF.get(tr_lower, ("hard", 0.04, "left"))
                transition_out = TransitionSpec(type=t_type, dur=t_dur, dir=t_dir)
            elif isinstance(tr, dict):
                transition_out = TransitionSpec(**tr)

        shots.append(ShotPlan(
            shot_id=shot_id,
            video=v_abs,
            in_point=in_pt,
            out_point=out_pt,
            audio_offset=audio_offset,
            vocal=vocal,
            foley=foley,
            speed=speed,
            punch_in=punch_in,
            transition_out=transition_out,
            caption=caption,
        ))

    # 2. Convert Music
    music_cues: List[MusicCue] = []
    mus_data = data.get("music")
    if mus_data:
        raw_cues = mus_data if isinstance(mus_data, list) else [mus_data]
        for c in raw_cues:
            m_file = c["file"]
            m_abs = str((base_dir / m_file).resolve()) if not Path(m_file).is_absolute() else m_file
            music_cues.append(MusicCue(
                file=m_abs,
                shot=c.get("shot"),
                at=float(c["at"]) if "at" in c else None,
                offset=float(c.get("offset", 0.0)),
                in_point=float(c.get("in", 0.0)),
                dur=float(c["dur"]) if "dur" in c else None,
                gain_db=float(c.get("db", c.get("gain_db", -14.0))),
                fade_in=float(c.get("fade_in", 0.3)),
                fade_out=float(c.get("fade_out", 0.8)),
            ))

    # 3. Convert SFX
    sfx_list: List[SFXSpec] = []
    for fx in data.get("sfx", []):
        f_file = fx["file"]
        f_abs = str((base_dir / f_file).resolve()) if not Path(f_file).is_absolute() else f_file
        sfx_list.append(SFXSpec(
            file=f_abs,
            at=float(fx.get("at", 0.0)),
            gain_db=float(fx.get("db", fx.get("gain_db", 0.0))),
        ))

    # Output plan
    font_path = data.get("font")
    if font_path and not Path(font_path).is_file():
        # Check standard Poppins or fallback font
        local_cand = Path(__file__).resolve().parent.parent / "fonts" / "Poppins-Bold.ttf"
        if local_cand.is_file():
            font_path = str(local_cand)
        else:
            font_path = None

    return EditPlan(
        size=tuple(data.get("size", (1080, 1920))),
        fps=int(data.get("fps", 24)),
        loudness_lufs=float(data.get("loudness_lufs", -14.0)),
        font=font_path,
        shots=shots,
        music=music_cues if music_cues else None,
        sfx=sfx_list,
    )
