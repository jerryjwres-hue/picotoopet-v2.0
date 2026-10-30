"""Canonical three-shot story for the 2026-10-29 visual-reject repair.

One white cat, one teal scarf, one living-room layout, one causal chain: the product tag lies on
the floor -> a hand clips it on the scarf -> the cat walks past the lamp wearing it. The data is
synthetic text; it proves the contract and the gate, never what a renderer will draw.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

EVIDENCE = "reviews:key:r1"
SOURCE_REF = "result:finding:1"
SUBJECT_PHRASE = (
    "Mochi, a white short-haired cat with pointed upright ears, amber eyes and a teal scarf"
)
PRODUCT_PHRASE = "a small round matte-charcoal tag clipped to the teal scarf"
SCARF_LOCK = "teal scarf"
TAG_LOCK = "charcoal tag"
CLOSING_1 = "Mochi's right paw rests on the charcoal tag on the wooden floor"
CLOSING_2 = "the charcoal tag is clipped to the teal scarf under Mochi's chin"
WIDTH, HEIGHT = 1280, 720  # video.landscape.v1


def script() -> dict[str, Any]:
    beats = [
        ("beat-001", 1, "The tag slipped off. Not again.", []),
        ("beat-002", 2, "A lightweight tag that clips on in seconds.", [EVIDENCE]),
        ("beat-003", 3, None, []),
    ]
    return {
        "schema_version": "1.0", "creative_profile": "creative.content_plan.v1",
        "script_id": "script-mochi", "title": "Clip it back on", "target_duration_seconds": 12,
        "beats": [
            {"beat_id": beat_id, "order": order, "duration_seconds": 4,
             "voiceover": voiceover, "on_screen_text": None, "visual_intent": f"beat {order}",
             "claim_source_evidence_ids": evidence, "unsupported_claim": False}
            for beat_id, order, voiceover, evidence in beats
        ],
        "cta_beat_id": "beat-003", "warnings": [], "needs_deep_ai": False, "needs_human": False,
    }


def brief() -> dict[str, Any]:
    return {
        "schema_version": "1.0", "creative_profile": "creative.content_plan.v1",
        "selected_idea_id": "idea-001", "target_audience": "cat owners",
        "customer_problem": "a tag that falls off", "value_proposition": "quick attach",
        "primary_hook": "Clip it back on", "emotional_tone": "warm",
        "content_format": "short video", "duration_min_seconds": 10, "duration_max_seconds": 14,
        "message_hierarchy": ["problem", "solution", "payoff"],
        "required_source_finding_refs": [SOURCE_REF], "required_source_evidence_ids": [EVIDENCE],
        "prohibited_claims": [], "cta_intent": "learn more", "continuity_notes": [],
        "needs_deep_ai": False, "needs_human": False,
    }


def _shot(index, beat, featured, opening, action, closing, framing, movement, handoff, risks=()):
    return {
        "shot_id": f"shot-{index:03d}", "beat_id": beat, "order": index, "scene_id": "living_room",
        "duration_seconds": 4.0, "featured": featured, "opening_state": opening,
        "visible_action": action, "closing_state": closing, "camera_framing": framing,
        "camera_movement": movement, "handoff_to_next": handoff, "risk_flags": list(risks),
    }


def bible() -> dict[str, Any]:
    return {
        "schema_version": "video_bible.v1",
        "subject": {
            "subject_id": "mochi", "kind": "PET", "species": "cat",
            "breed_or_type": "short-haired cat",
            "coat_or_appearance": "white coat, pointed upright ears, amber eyes",
            "distinguishing_marks": [SCARF_LOCK, "pointed upright ears", "amber eyes"],
            "identity_phrase": SUBJECT_PHRASE,
        },
        "product": {
            "product_id": "pawtrack-mini", "name": "PawTrack Mini", "category": "pet tag",
            "shape_color_material": "small round matte-charcoal tag",
            "identity_phrase": PRODUCT_PHRASE, "logo_policy": "NO_TEXT_OR_LOGO_IN_FRAME",
            "claims": [{
                "claim_id": "c-clip", "text": "a lightweight tag that clips on in seconds",
                "evidence_ids": [EVIDENCE], "verified": True,
            }],
        },
        "scenes": [{
            "scene_id": "living_room",
            "environment_phrase": (
                "tidy living room, a wooden side table at screen right with one lamp standing "
                "on it, a grey sofa at screen left, wooden floor"
            ),
            "lighting_phrase": "warm lamp glow with soft window light from screen left",
            "palette": ["white", "teal", "charcoal", "warm wood"],
        }],
        "camera_rules": {
            "screen_direction": "LEFT_TO_RIGHT",
            "allowed_movements": ["STATIC", "SLOW_PUSH_IN", "TRACK_SIDE"],
        },
        "continuity_anchors": [
            "one white cat with a teal scarf", "lamp standing on the wooden side table",
            "grey sofa at screen left",
        ],
        "global_continuity_notes": ["Mochi and the charcoal tag look identical in every shot"],
        "arc": [
            {"beat_id": "beat-001", "role": "HOOK"},
            {"beat_id": "beat-002", "role": "DEMO"},
            {"beat_id": "beat-003", "role": "CTA"},
        ],
        "shots": [
            _shot(1, "beat-001", ["SUBJECT", "PRODUCT"],
                  "Mochi sits on the wooden floor beside the side table, the charcoal tag lies "
                  "on the floor by her right paw",
                  "Mochi taps the tag with her right paw", CLOSING_1,
                  "medium shot", "STATIC", "CONTINUOUS"),
            _shot(2, "beat-002", ["SUBJECT", "PRODUCT"], CLOSING_1,
                  "a hand clips the tag onto the teal scarf under Mochi's chin", CLOSING_2,
                  "close-up", "SLOW_PUSH_IN", "CONTINUOUS", ["PRODUCT_CLOSEUP", "HAND_OBJECT"]),
            _shot(3, "beat-003", ["SUBJECT", "PRODUCT"], CLOSING_2,
                  "Mochi walks left to right past the lamp table, the tag swaying on the scarf",
                  "Mochi sits beside the side table facing the camera, the tag clipped to the "
                  "scarf",
                  "wide shot", "TRACK_SIDE", "CUT_ON_ACTION"),
        ],
        "negative_concepts": ["EXTRA_LIMBS", "MORPHING", "DUPLICATED_OBJECTS", "FLICKER"],
        "unverified_fields": ["reference_image"],
        "needs_deep_ai": False, "needs_human": False,
    }


def mutated(**changes: Any) -> dict[str, Any]:
    out = deepcopy(bible())
    out.update(changes)
    return out
