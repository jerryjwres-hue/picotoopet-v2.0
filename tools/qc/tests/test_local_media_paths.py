import cv2
import numpy as np

from qc.checker import load_media_frames
from qc.report import render_report_image


def test_unicode_media_and_report_paths(tmp_path):
    frame = np.full((96, 96, 3), 160, dtype=np.uint8)
    image = tmp_path / "分镜.png"
    image.write_bytes(cv2.imencode(".png", frame)[1].tobytes())
    frames, _ = load_media_frames(image)
    assert np.array_equal(frames[0], frame)
    preview = tmp_path / "质检报告.jpg"
    render_report_image(frames, [], {"pass": True, "score": 100}, preview)
    assert preview.read_bytes().startswith(b"\xff\xd8")
