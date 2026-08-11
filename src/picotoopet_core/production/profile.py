"""Closed 2.3.20.1 ComfyUI production profile."""

from __future__ import annotations

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
