"""Tests for TikTok / Instagram UI occlusion safety zone checks."""

from qc.safety_zone import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    OCCLUSION_BOTTOM,
    OCCLUSION_TOP,
    check_caption_spec_safety,
)
from qc.spec import CaptionSpec


def test_caption_safe_placement():
    # y_ratio 0.20 -> 384px (well inside safe region [160, 1500])
    cap = CaptionSpec(text="Hello Maotai", y_ratio=0.20)
    fails, metrics = check_caption_spec_safety(cap)
    assert len(fails) == 0
    assert metrics["caption_checked"] is True


def test_caption_in_top_occlusion_fails():
    # y_ratio 0.05 -> 96px (< 160px top occlusion)
    cap = CaptionSpec(text="Blocked header", y_ratio=0.05)
    fails, _ = check_caption_spec_safety(cap)
    assert len(fails) > 0
    assert any("subtitle_safety_zone_top" in f["check"] for f in fails)


def test_caption_in_bottom_occlusion_fails():
    # y_ratio 0.85 -> 1632px (> 1500px bottom occlusion)
    cap = CaptionSpec(text="Blocked footer", y_ratio=0.85)
    fails, _ = check_caption_spec_safety(cap)
    assert len(fails) > 0
    assert any("subtitle_safety_zone_bottom" in f["check"] for f in fails)
