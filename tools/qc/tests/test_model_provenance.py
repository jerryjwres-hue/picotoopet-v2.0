"""The actual QC engine, not the requested engine, determines certification."""

import cv2
import numpy as np

from qc.checker import ShotChecker
from qc.detector import BaseDetector, DetectionBox, Florence2Detector
from qc.identity import DINOv2Extractor
from qc.spec import ShotSpec


class CertifiedFixtureDetector(BaseDetector):
    """Test-only object detector with an explicitly declared nonfallback engine."""
    is_fallback = False

    def detect_frame(self, frame):
        return [
            DetectionBox(5, 5, 40, 40, "dog", 0.99),
        ]


class FallbackFixtureIdentity:
    """Test-only representation of an unavailable DINOv2 model."""
    is_fallback = True

    def extract_embedding(self, image):
        # 让相似度本身可能很高，验证降级来源依然阻止自动通过。
        return np.array([1.0, 0.0, 0.0], dtype=np.float32)


def _test_image(tmp_path):
    path = tmp_path / "synthetic.png"
    cv2.imwrite(str(path), np.full((64, 64, 3), 127, dtype=np.uint8))
    return path


def _spec(**changes):
    return ShotSpec(
        shot_id="S01",
        expect={"dogs": 1},
        min_motion=0.0,
        max_motion=5.0,
        check_dissolve=False,
        check_bandana=False,
        check_color_smear=False,
        **changes,
    )


def test_florence_missing_runtime_model_marks_fallback():
    detector = Florence2Detector.__new__(Florence2Detector)
    detector.model = None
    detector.processor = None
    detector.is_fallback = False
    detector.detect_frame(np.zeros((64, 64, 3), dtype=np.uint8))
    assert detector.is_fallback is True


def test_dinov2_missing_runtime_model_marks_fallback():
    extractor = DINOv2Extractor.__new__(DINOv2Extractor)
    extractor.model = None
    extractor.transform = None
    extractor.is_fallback = False
    vector = extractor.extract_embedding(np.zeros((64, 64, 3), dtype=np.uint8))
    assert extractor.is_fallback is True
    assert vector.size > 0


def test_identity_fallback_never_certifies_even_with_matching_vectors(tmp_path):
    image = _test_image(tmp_path)
    checker = ShotChecker(
        spec=_spec(identity_refs={"dog": str(image)}),
        detector=CertifiedFixtureDetector(),
        identity_extractor=FallbackFixtureIdentity(),
    )
    report, exit_code = checker.run_check(image, out_json_path=tmp_path / "qc.json")
    assert exit_code == 1
    assert report["pass"] is False
    assert report["identity_fallback_active"] is True
    assert report["metrics"]["engines"]["identity_extractor_fallback"] is True


def test_missing_reference_cannot_certify_identity(tmp_path):
    image = _test_image(tmp_path)
    checker = ShotChecker(
        spec=_spec(identity_refs={"dog": str(tmp_path / "missing.png")}),
        detector=CertifiedFixtureDetector(),
        identity_extractor=FallbackFixtureIdentity(),
    )
    report, exit_code = checker.run_check(image, out_json_path=tmp_path / "missing.json")
    assert exit_code == 1
    assert any(item["check"] == "identity_unverified" for item in report["fails"])


def test_no_identity_refs_skips_dinov2_initialization():
    checker = ShotChecker(spec=_spec(), detector=CertifiedFixtureDetector())
    assert checker.identity_extractor is None
