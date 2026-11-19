"""End-to-end integration tests for ShotChecker and CLI."""

import json
from pathlib import Path
from typing import List
import cv2
import numpy as np

from qc.checker import ShotChecker
from qc.cli import main
from qc.detector import BaseDetector, DetectionBox
from qc.spec import ShotSpec


class CertifiedMockDetector(BaseDetector):
    """Certified detector mock that fulfills object expectations without falling back."""
    is_fallback: bool = False

    def detect_frame(self, frame: np.ndarray) -> List[DetectionBox]:
        return [
            DetectionBox(x1=150, y1=300, x2=400, y2=700, label="dog", confidence=0.95),
            DetectionBox(x1=200, y1=720, x2=340, y2=780, label="bowl", confidence=0.92),
        ]


def test_qc_checker_passing_image(synthetic_image_generator, tmp_path):
    # Create single image matching expect: 1 dog, 1 bowl
    img = synthetic_image_generator(
        width=540, height=960,
        draw_dog=True, draw_bowl=True, draw_ball=False, draw_face=False,
    )
    img_path = tmp_path / "shot_01.png"
    cv2.imwrite(str(img_path), img)

    # Reference dog crop
    ref_crop = img[300:700, 150:400]
    ref_path = tmp_path / "dog_ref.png"
    cv2.imwrite(str(ref_path), ref_crop)

    spec_dict = {
        "shot_id": "S01",
        "expect": {"dogs": 1, "people": 0, "bowls": 1, "balls": 0, "faces_visible": False},
        "identity_refs": {"dog": str(ref_path)},
        "min_motion": 0.0,
        "max_motion": 5.0,
        "caption": {"text": "Maotai lunch", "y_ratio": 0.20},
        "allow_light_change": False,
    }
    spec_path = tmp_path / "spec.json"
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec_dict, f)

    spec = ShotSpec.from_file(spec_path)
    checker = ShotChecker(spec=spec, detector=CertifiedMockDetector())

    report_json = tmp_path / "report.json"
    report_jpg = tmp_path / "report.jpg"

    report_data, exit_code = checker.run_check(
        media_path=img_path,
        out_json_path=report_json,
        out_jpg_path=report_jpg,
    )

    assert exit_code == 0
    assert report_data["pass"] is True
    assert report_data["score"] >= 80
    assert report_json.is_file()
    assert report_jpg.is_file()


def test_qc_checker_fallback_cv_blocks_pass(synthetic_image_generator, tmp_path):
    """Under pure CV fallback, quantity checks become warnings and pass is forced False."""
    img = synthetic_image_generator(
        width=540, height=960,
        draw_dog=True, draw_bowl=True, draw_ball=False, draw_face=False,
    )
    img_path = tmp_path / "shot_fallback.png"
    cv2.imwrite(str(img_path), img)

    spec_dict = {
        "shot_id": "S_FALLBACK",
        "expect": {"dogs": 1, "people": 0, "bowls": 1, "balls": 0, "faces_visible": False},
        "min_motion": 0.0,
        "max_motion": 5.0,
    }
    spec_path = tmp_path / "spec_fallback.json"
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec_dict, f)

    spec = ShotSpec.from_file(spec_path)
    checker = ShotChecker(spec=spec, use_florence=False)

    report_json = tmp_path / "report_fallback.json"
    report_data, exit_code = checker.run_check(img_path, out_json_path=report_json)

    assert exit_code == 1
    assert report_data["pass"] is False
    assert report_data.get("fallback_cv_active") is True


def test_qc_checker_failing_unexpected_face(synthetic_image_generator, tmp_path):
    class DetectorWithFace(BaseDetector):
        is_fallback = False
        def detect_frame(self, frame):
            return [
                DetectionBox(x1=100, y1=100, x2=200, y2=200, label="human face", confidence=0.99),
                DetectionBox(x1=150, y1=300, x2=400, y2=700, label="dog", confidence=0.95),
            ]

    img = synthetic_image_generator(
        width=540, height=960,
        draw_dog=True, draw_bowl=False, draw_face=True,
    )
    img_path = tmp_path / "shot_face_fail.png"
    cv2.imwrite(str(img_path), img)

    spec_dict = {
        "shot_id": "S02",
        "expect": {"dogs": 1, "people": 0, "bowls": 0, "faces_visible": False},
        "min_motion": 0.0,
        "max_motion": 5.0,
    }
    spec_path = tmp_path / "spec.json"
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec_dict, f)

    spec = ShotSpec.from_file(spec_path)
    checker = ShotChecker(spec=spec, detector=DetectorWithFace())

    report_json = tmp_path / "report.json"
    report_data, exit_code = checker.run_check(img_path, out_json_path=report_json)

    assert exit_code == 1
    assert report_data["pass"] is False
    assert any("face_visibility" in f["check"] for f in report_data["fails"])


def test_qc_cli_e2e(synthetic_image_generator, tmp_path):
    img = synthetic_image_generator(width=540, height=960, draw_dog=True, draw_bowl=True)
    img_path = tmp_path / "cli_test.png"
    cv2.imwrite(str(img_path), img)

    spec_dict = {
        "shot_id": "S03",
        "expect": {"dogs": 1, "bowls": 1, "people": 0, "faces_visible": False},
        "min_motion": 0.0,
        "max_motion": 5.0,
    }
    spec_path = tmp_path / "cli_spec.json"
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec_dict, f)

    report_path = tmp_path / "cli_report.json"

    args = [
        "check",
        "--spec", str(spec_path),
        "--media", str(img_path),
        "--out", str(report_path),
    ]
    exit_code = main(args)
    # Pure CV fallback exits with 1 (fail) because pure CV cannot certify pass
    assert exit_code == 1
    assert report_path.is_file()
