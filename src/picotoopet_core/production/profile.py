"""Closed 2.3.20.1 ComfyUI production profile."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from picotoopet_core.creative.models import VideoOutputProfile

PRODUCTION_PROFILE_ID       = "production.comfyui.v1"
PRODUCTION_PROFILE_VERSION  = "1.0"
COMFY_ENDPOINT              = "http://127.0.0.1:8188"
T2V_WORKFLOW_ID             = "comfy.wan22.ti2v5b.t2v.v1"
I2V_WORKFLOW_ID             = "comfy.wan22.ti2v5b.i2v.v1"
NEGATIVE_PROMPT_POLICY_ID   = "wan22.safe-negative.v1"

WAN22_DIFFUSION_MODEL       = "wan2.2_ti2v_5B_fp16.safetensors"
WAN22_VAE_MODEL             = "wan2.2_vae.safetensors"
WAN22_TEXT_ENCODER          = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"

MIN_WIDTH                   = 256
MAX_WIDTH                   = 1280
MIN_HEIGHT                  = 256
MAX_HEIGHT                  = 1280
DEFAULT_WIDTH               = 832
DEFAULT_HEIGHT              = 480
DEFAULT_FPS                 = 24
MAX_FPS                     = 30
DEFAULT_FRAME_COUNT         = 81
MAX_FRAME_COUNT             = 121
MAX_COMFY_ATTEMPTS          = 2

WORKFLOW_BY_RENDER_INTENT = {
    "GENERATIVE_VIDEO": T2V_WORKFLOW_ID,
    "IMAGE_TO_VIDEO": I2V_WORKFLOW_ID,
}

ALLOWED_WORKFLOW_IDS = frozenset(WORKFLOW_BY_RENDER_INTENT.values())
ALLOWED_MODEL_FILES = frozenset(
    {
        WAN22_DIFFUSION_MODEL,
        WAN22_VAE_MODEL,
        WAN22_TEXT_ENCODER,
    }
)


@dataclass(frozen=True, slots=True)
class VideoOutputProfileSpec:
    width: int
    height: int
    fps: int


VIDEO_OUTPUT_PROFILES = {
    VideoOutputProfile.LANDSCAPE_V1: VideoOutputProfileSpec(832, 480, 24),
    VideoOutputProfile.VERTICAL_V1: VideoOutputProfileSpec(480, 832, 24),
    VideoOutputProfile.SQUARE_V1: VideoOutputProfileSpec(640, 640, 24),
}

TIMELINE_TOLERANCE_SECONDS = 5.0


def duration_ms(duration_seconds: float) -> int:
    """Convert validated Creative timing to deterministic integer milliseconds."""

    return int((Decimal(str(duration_seconds)) * 1000).quantize(Decimal("1"), ROUND_HALF_UP))


def frame_count_for_duration(duration_seconds: float, fps: int) -> int:
    """Map duration to the nearest Wan-compatible 4n+1 frame count.

    Nearest-family quantization is bounded by two frames (2/fps seconds).
    Durations beyond the existing renderer limit fail instead of truncating.
    """

    target_frames = Decimal(str(duration_seconds)) * fps
    family_index = int(
        ((target_frames - 1) / 4).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )
    frame_count = max(1, 4 * max(0, family_index) + 1)
    if frame_count > MAX_FRAME_COUNT:
        raise ValueError("PRODUCTION_SHOT_DURATION_UNSUPPORTED")
    rendered_seconds = Decimal(frame_count) / fps
    if abs(rendered_seconds - Decimal(str(duration_seconds))) > Decimal(2) / fps:
        raise ValueError("PRODUCTION_SHOT_DURATION_UNSUPPORTED")
    return frame_count
