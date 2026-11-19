"""Open-vocabulary object and face/person detection.

Primary: Florence-2 (MIT License) for open-vocabulary detection of dog, bowl, ball, person.
Secondary/Fallback: OpenCV YuNet / cascades & heuristic contours for offline testing/CPU fast path.
Strictly commercial-friendly permissive licenses (MIT / Apache-2.0 / BSD). NO AGPL / ultralytics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

from qc.gpu import resolve_device

logger = logging.getLogger("qc.detector")


@dataclass
class DetectionBox:
    """Bounding box detection result."""
    x1: int
    y1: int
    x2: int
    y2: int
    label: str
    confidence: float

    @property
    def box_xyxy(self) -> Tuple[int, int, int, int]:
        return (self.x1, self.y1, self.x2, self.y2)

    def crop(self, frame: np.ndarray) -> np.ndarray:
        """Crop region from image."""
        h, w = frame.shape[:2]
        x1 = max(0, min(w - 1, self.x1))
        x2 = max(x1 + 1, min(w, self.x2))
        y1 = max(0, min(h - 1, self.y1))
        y2 = max(y1 + 1, min(h, self.y2))
        return frame[y1:y2, x1:x2]


class BaseDetector:
    """Interface for object and person/face detection."""

    def detect_frame(self, frame: np.ndarray) -> List[DetectionBox]:
        raise NotImplementedError


class Florence2Detector(BaseDetector):
    """Florence-2 open-vocabulary detector (MIT License)."""

    def __init__(self, model_id: str = "microsoft/Florence-2-base", device: Optional[str] = None):
        self.device = device or resolve_device()
        self.model = None
        self.processor = None
        self.model_id = model_id
        self._load_model()

    def _load_model(self):
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoProcessor
            logger.info(f"Loading Florence-2 model ({self.model_id}) on device: {self.device}...")
            torch_dtype = torch.float16 if self.device == "cuda" else torch.float32
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_id,
                trust_remote_code=True,
                torch_dtype=torch_dtype,
                low_cpu_mem_usage=True,
                local_files_only=True,
            ).to(self.device)
            self.processor = AutoProcessor.from_pretrained(
                self.model_id,
                trust_remote_code=True,
                local_files_only=True,
            )
            self.model.eval()
            logger.info("Florence-2 successfully loaded.")
        except Exception as exc:
            logger.warning(f"Florence-2 local weights not available ({exc}). Using heuristic detector.")
            self.model = None

    def detect_frame(self, frame: np.ndarray, query_labels: Optional[List[str]] = None) -> List[DetectionBox]:
        if self.model is None or self.processor is None:
            return FallbackCVDetector().detect_frame(frame)

        try:
            import torch
            from PIL import Image

            if query_labels is None:
                query_labels = ["dog", "bowl", "ball", "person", "human face"]

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb)

            task_prompt = "<OPEN_VOCABULARY_DETECTION>"
            text_input = task_prompt + ",".join(query_labels)

            inputs = self.processor(text=text_input, images=pil_img, return_tensors="pt").to(self.device)
            with torch.no_grad():
                generated_ids = self.model.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=1024,
                    num_beams=3,
                )
            generated_text = self.processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
            parsed = self.processor.post_process_generation(
                generated_text,
                task=task_prompt,
                image_size=(pil_img.width, pil_img.height),
            )

            results: List[DetectionBox] = []
            detection_dict = parsed.get(task_prompt, {})
            bboxes = detection_dict.get("bboxes", [])
            labels = detection_dict.get("bboxes_labels", [])

            for bbox, label in zip(bboxes, labels):
                x1, y1, x2, y2 = [int(v) for v in bbox]
                results.append(DetectionBox(
                    x1=x1, y1=y1, x2=x2, y2=y2,
                    label=str(label).strip().lower(),
                    confidence=0.90,
                ))
            return results

        except Exception as exc:
            logger.warning(f"Error during Florence-2 inference: {exc}. Using fallback.")
            return FallbackCVDetector().detect_frame(frame)


class FallbackCVDetector(BaseDetector):
    """Fallback detector using OpenCV and computer vision heuristics.

    Permissive Apache 2.0 / BSD / MIT only. Detects faces, people, and objects.
    Ensures tests and offline runs execute without requiring multi-GB weights download.
    """

    def __init__(self):
        self.face_cascade = None
        if hasattr(cv2, "CascadeClassifier") and hasattr(cv2, "data") and hasattr(cv2.data, "haarcascades"):
            try:
                self.face_cascade = cv2.CascadeClassifier(
                    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
                )
            except Exception:
                self.face_cascade = None

    def detect_frame(self, frame: np.ndarray) -> List[DetectionBox]:
        results: List[DetectionBox] = []
        if frame is None or frame.size == 0:
            return results

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # 1. Detect faces using CascadeClassifier if available, otherwise skin-tone ellipse heuristic
        if self.face_cascade is not None and not self.face_cascade.empty():
            faces = self.face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30),
            )
            for (x, y, fw, fh) in faces:
                results.append(DetectionBox(
                    x1=int(x), y1=int(y), x2=int(x + fw), y2=int(y + fh),
                    label="face",
                    confidence=0.85,
                ))
        else:
            # Color/skin tone contour detection for human face
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            # Typical human skin hue in HSV is [0, 25] and [170, 180]
            mask1 = cv2.inRange(hsv, np.array([0, 25, 50], dtype=np.uint8), np.array([25, 220, 255], dtype=np.uint8))
            mask2 = cv2.inRange(hsv, np.array([165, 25, 50], dtype=np.uint8), np.array([180, 220, 255], dtype=np.uint8))
            skin_mask = cv2.bitwise_or(mask1, mask2)
            face_contours, _ = cv2.findContours(skin_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for cnt in face_contours:
                area = cv2.contourArea(cnt)
                if 4000 <= area <= 55000:
                    x, y, fw, fh = cv2.boundingRect(cnt)
                    aspect = float(fw) / float(fh + 1e-6)
                    if 0.50 <= aspect <= 1.25:
                        results.append(DetectionBox(
                            x1=int(x), y1=int(y), x2=int(x + fw), y2=int(y + fh),
                            label="face",
                            confidence=0.80,
                        ))

        # 2. Detect geometric shapes: dog, bowl, ball
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 40, 120)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 500:
                continue
            x, y, bw, bh = cv2.boundingRect(cnt)
            aspect_ratio = float(bw) / float(bh + 1e-6)
            perimeter = cv2.arcLength(cnt, True)
            circularity = 4 * np.pi * (area / (perimeter * perimeter + 1e-6))

            # Ball: compact circle
            if circularity > 0.70 and 0.8 < aspect_ratio < 1.25 and area < 40000:
                results.append(DetectionBox(
                    x1=int(x), y1=int(y), x2=int(x + bw), y2=int(y + bh),
                    label="ball",
                    confidence=0.80,
                ))
            # Bowl: wide elliptical shape
            elif 1.4 <= aspect_ratio <= 3.5 and 2000 <= area < 70000:
                results.append(DetectionBox(
                    x1=int(x), y1=int(y), x2=int(x + bw), y2=int(y + bh),
                    label="bowl",
                    confidence=0.80,
                ))
            # Dog: large figure (area >= 20000)
            elif area >= 20000:
                results.append(DetectionBox(
                    x1=int(x), y1=int(y), x2=int(x + bw), y2=int(y + bh),
                    label="dog",
                    confidence=0.85,
                ))

        return results


def get_detector(use_florence: bool = True) -> BaseDetector:
    """Factory to acquire detection engine."""
    if use_florence:
        try:
            return Florence2Detector()
        except Exception:
            return FallbackCVDetector()
    return FallbackCVDetector()
