"""Tests for artifact anomaly checks: dissolve, bandana position, and color smear."""

import numpy as np
import pytest

from qc.artifacts import (
    check_bandana_position,
    check_color_smear,
    check_dissolve_ghosting,
    check_fence_penetration,
)
from qc.checker import ShotChecker
from qc.detector import FallbackCVDetector
from qc.spec import ShotExpectation, ShotSpec


def test_dissolve_ghosting_synthetic():
    """Verify linear blend double exposure detection."""
    frames = []
    # Create smooth gradient background frames with a moving block
    x_coords, y_coords = np.meshgrid(np.linspace(0, 1, 200), np.linspace(0, 1, 200))
    base_bg = (x_coords * 100 + y_coords * 50 + 50).astype(np.uint8)
    base_bg = np.dstack([base_bg, base_bg, base_bg])

    for i in range(15):
        f = base_bg.copy()
        x = i * 4
        f[20:180, x:x + 80] = 250
        frames.append(f)

    # Clean motion should have 0 dissolve fails
    fails = check_dissolve_ghosting(frames)
    assert len(fails) == 0

    # Introduce double exposure blend at frame 7: 50% frame 4 + 50% frame 10
    blend_frame = (0.5 * frames[4].astype(np.float32) + 0.5 * frames[10].astype(np.float32)).astype(np.uint8)
    frames[7] = blend_frame

    fails_ghost = check_dissolve_ghosting(frames)
    assert len(fails_ghost) > 0
    assert any(f["check"] == "dissolve_ghosting" for f in fails_ghost)


def test_bandana_position_synthetic():
    """Verify bandana displacement check."""
    # 1. Normal frame: green bandana at y=500 (neck)
    normal_frame = np.zeros((1920, 1080, 3), dtype=np.uint8)
    # Bright green BGR: (30, 200, 30)
    normal_frame[500:650, 450:600] = [30, 200, 30]
    fails_normal = check_bandana_position([normal_frame])
    assert len(fails_normal) == 0

    # 2. Anomalous frame: green bandana on head/back (y=200, cy<450, h>200)
    bad_frame = np.zeros((1920, 1080, 3), dtype=np.uint8)
    bad_frame[200:480, 450:650] = [30, 200, 30]
    fails_bad = check_bandana_position([bad_frame])
    assert len(fails_bad) > 0
    assert fails_bad[0]["check"] == "bandana_position"


def test_color_smear_synthetic():
    """Verify expanding saturated red anomaly check."""
    frames = []
    # 5 base frames
    for _ in range(5):
        frames.append(np.zeros((300, 300, 3), dtype=np.uint8))

    # Frame 4 has sudden massive saturated red blob (BGR: [0, 0, 255])
    # 150x150 = 22,500 pixels (> 14,000 threshold)
    frames[4][50:200, 50:200] = [0, 0, 255]

    fails = check_color_smear(frames)
    assert len(fails) > 0
    assert fails[0]["check"] == "color_smear"


def test_pure_cv_fallback_demotes_count_fails_and_blocks_pass(tmp_path):
    """Verify that pure CV fallback records count mismatches as warnings and forces pass=False."""
    spec = ShotSpec(
        shot_id="TEST_FALLBACK",
        expect=ShotExpectation(dogs=1, people=0, bowls=0, balls=0, faces_visible=False),
    )
    # Empty black frame
    black_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    import cv2
    img_path = tmp_path / "test.jpg"
    cv2.imwrite(str(img_path), black_frame)

    checker = ShotChecker(spec=spec, detector=FallbackCVDetector())
    report, exit_code = checker.run_check(
        media_path=img_path,
        out_json_path=tmp_path / "report.json",
    )

    # Pure CV fallback must NOT pass
    assert report["pass"] is False
    assert exit_code == 1
    # dog_count should be in warnings, NOT in fails
    fail_checks = [f["check"] for f in report["fails"]]
    warn_checks = [w["check"] for w in report["warnings"]]
    assert "dog_count" not in fail_checks
    assert "dog_count" in warn_checks
    assert "pure_cv_fallback" in warn_checks
