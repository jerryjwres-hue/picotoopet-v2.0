"""Story Director instructions and bounded context for the opt-in v2 Creative runtime.

Everything the local model receives for the Video Bible stage is assembled here and in
``CreativeIntelligenceCoordinator._stage_context``: the system prompt below, the strict JSON
schema of ``VideoBibleDraft`` and a context object that carries only validated earlier stages,
the allowed evidence ids and the hard constraints. Source text stays untrusted data.
"""

from __future__ import annotations

from typing import Any

from picotoopet_core.production.profile import VIDEO_OUTPUT_PROFILES

from .models import CreativeBriefResult, CreativeScriptResult
from .video_bible import (
    CAMERA_PHRASE,
    MAX_BIBLE_SHOTS,
    MIN_SHOT_SECONDS,
    CameraMovement,
)

VIDEO_BIBLE_TEMPLATE_VERSION = "video-bible-v1.0.0"
SHOT_PLAN_FROM_BIBLE_TEMPLATE_VERSION = "shot-plan-from-bible-v1.0.0"

STORY_DIRECTOR_INSTRUCTIONS = (
    " You are the Story Director. Return one video_bible.v1 object: the single source of "
    "truth for subject and product identity, scenes, camera and shot-to-shot continuity of a "
    "short product video that a local text-to-video model renders one shot at a time with no "
    "memory between shots. "
    "(1) Identity: write subject.identity_phrase and product.identity_phrase once, as concrete "
    "visible attributes (species or breed, coat colour, marks, accessories; shape, colour, "
    "material). They are copied word for word into every shot that features them. Never "
    "depend on a brand name, readable text or a logo. "
    "(2) Claims: invent no product facts. Every product.claims entry that is verified must "
    "cite ids from allowed_evidence_ids; creative-only statements get verified=false with no "
    "evidence and must never appear in a voiceover. "
    "(3) Shots: split the script beats into shots of "
    f"{MIN_SHOT_SECONDS:g} to 5.0 seconds (aim for 3 to 5) with exactly one dominant visible "
    "action each; never join actions with 'then' or semicolons. Cover every beat in order. "
    "Give each shot opening_state and closing_state; use handoff_to_next CONTINUOUS only when "
    "the next shot's opening_state is word for word this shot's closing_state. "
    "(4) arc lists exactly the supplied beat_ids in order; the first is HOOK and the last, the "
    "supplied CTA beat, is the only CTA. "
    "(5) Scenes: one environment phrase, one lighting phrase and at most six palette words per "
    "place; reuse a scene for shots that happen in the same place. "
    "(6) Camera: choose camera_movement only from camera_rules.allowed_movements and keep "
    "screen direction consistent. "
    "(7) Write phrases in concise English. Forbidden: URLs, file paths, image or video file "
    "names, reference images, tools, workflows, model or software instructions, and quality "
    "adjective spam such as 8K, masterpiece or cinematic. "
    "(8) If the evidence cannot support a coherent video, set needs_human to true instead of "
    "inventing facts."
)


def director_constraints(
    brief: CreativeBriefResult, script: CreativeScriptResult
) -> dict[str, Any]:
    spec = VIDEO_OUTPUT_PROFILES[brief.output_profile_id]
    return {
        "output_profile_id": brief.output_profile_id.value,
        "frame_size": f"{spec.width}x{spec.height}",
        "shot_seconds": {"min": MIN_SHOT_SECONDS, "preferred": [3.0, 5.0], "max": 5.0},
        "max_shots": MAX_BIBLE_SHOTS,
        "script_beat_ids": [beat.beat_id for beat in script.beats],
        "cta_beat_id": script.cta_beat_id,
        "script_target_duration_seconds": script.target_duration_seconds,
        "camera_rules": {
            "allowed_movements": [movement.value for movement in CameraMovement],
            "phrases": {key.value: value for key, value in CAMERA_PHRASE.items()},
        },
        "reference_images": "none: no approved image exists; do not describe or request one",
    }
