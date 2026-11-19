"""Core Quality Control orchestrator executing all 7 checks on image/video media."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

from qc.artifacts import (
    check_bandana_position,
    check_color_smear,
    check_dissolve_ghosting,
    check_fence_penetration,
)
from qc.audio_qc import check_audio_quality
from qc.detector import BaseDetector, DetectionBox, FallbackCVDetector, Florence2Detector
from qc.identity import DINOv2Extractor, evaluate_identity_consistency
from qc.motion import check_motion
from qc.report import format_report_data, render_report_image, save_report_json
from qc.safety_zone import check_caption_spec_safety, detect_occluded_text_in_frame
from qc.spec import ShotSpec
from qc.stability import check_visual_stability

logger = logging.getLogger("qc.checker")


def load_media_frames(media_path: str | Path, target_fps: float = 4.0) -> Tuple[List[np.ndarray], float]:
    """Load media file as list of sampled BGR frames.

    If media is an image, returns single-element list.
    If media is a video, samples frames at target_fps (default 4 fps).
    Returns (frames, original_fps).
    """
    p = Path(media_path)
    if not p.is_file():
        raise FileNotFoundError(f"Media file not found: {p}")

    suffix = p.suffix.lower()
    # Check if single image
    if suffix in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
        img = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"Could not read image file: {p}")
        return [img], target_fps

    # Video file: sample at target_fps
    cap = cv2.VideoCapture(str(p))
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {p}")

    orig_fps = cap.get(cv2.CAP_PROP_FPS)
    if orig_fps <= 0 or np.isnan(orig_fps):
        orig_fps = 30.0

    step = max(1, int(round(orig_fps / target_fps)))
    frames: List[np.ndarray] = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_idx % step == 0:
            frames.append(frame)
        frame_idx += 1

    cap.release()
    return frames, orig_fps


def load_last_frame_of_video(video_path: str | Path) -> Optional[np.ndarray]:
    """Extract and return the very last frame of a video."""
    p = Path(video_path)
    if not p.is_file():
        return None
    cap = cv2.VideoCapture(str(p))
    if not cap.isOpened():
        return None
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, total_frames - 1))
        ret, frame = cap.read()
        cap.release()
        if ret:
            return frame
    # Fallback read to end
    last_frame = None
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        last_frame = frame
    cap.release()
    return last_frame


class ShotChecker:
    """Orchestrates comprehensive 7-point quality control checks."""

    def __init__(
        self,
        spec: ShotSpec,
        detector: Optional[BaseDetector] = None,
        identity_extractor: Optional[DINOv2Extractor] = None,
        use_florence: bool = False,
    ):
        self.spec = spec
        if detector is not None:
            self.detector = detector
        elif use_florence:
            try:
                self.detector = Florence2Detector()
            except Exception:
                self.detector = FallbackCVDetector()
        else:
            self.detector = FallbackCVDetector()

        self.identity_extractor = identity_extractor or DINOv2Extractor()

    def run_check(
        self,
        media_path: str | Path,
        prev_media_path: Optional[str | Path] = None,
        out_json_path: str | Path = "report.json",
        out_jpg_path: Optional[str | Path] = None,
    ) -> Tuple[Dict[str, Any], int]:
        """Execute all checks.

        Returns:
            (report_dict, exit_code) where exit_code is 0 (pass) or 1 (fail).
        """
        all_fails: List[Dict[str, Any]] = []
        all_warnings: List[Dict[str, Any]] = []
        metrics: Dict[str, Any] = {
            "media": str(media_path),
            "prev_media": str(prev_media_path) if prev_media_path else None,
            "sampled_fps": self.spec.fps_sample,
            "total_sampled_frames": 0,
        }

        # 1. Load media frames
        frames, orig_fps = load_media_frames(media_path, target_fps=self.spec.fps_sample)
        metrics["total_sampled_frames"] = len(frames)
        metrics["original_video_fps"] = round(orig_fps, 2)

        prev_last_frame = None
        if prev_media_path:
            prev_last_frame = load_last_frame_of_video(prev_media_path)

        # 2. Frame-by-frame entity detection & counts
        annotated_boxes_per_frame: Dict[int, List[DetectionBox]] = {}
        target_crops: Dict[str, List[np.ndarray]] = {"dog": [], "owner": []}

        for f_idx, frame in enumerate(frames):
            boxes = self.detector.detect_frame(frame)
            annotated_boxes_per_frame[f_idx] = boxes

            # Count occurrences by label
            counts: Dict[str, int] = {"dog": 0, "person": 0, "bowl": 0, "ball": 0, "face": 0}
            for box in boxes:
                lbl = box.label.lower()
                if "dog" in lbl:
                    counts["dog"] += 1
                    target_crops["dog"].append(box.crop(frame))
                elif "person" in lbl or "body" in lbl:
                    counts["person"] += 1
                    target_crops["owner"].append(box.crop(frame))
                elif "bowl" in lbl or "dish" in lbl:
                    counts["bowl"] += 1
                elif "ball" in lbl or "toy" in lbl:
                    counts["ball"] += 1
                elif "face" in lbl:
                    counts["face"] += 1

            # Validate against expectations
            exp = self.spec.expect
            is_fallback = getattr(self.detector, "is_fallback", False)
            dest_list = all_warnings if is_fallback else all_fails
            suffix = " (pure CV fallback advisory)" if is_fallback else ""

            if counts["dog"] != exp.dogs:
                dest_list.append({
                    "check": "dog_count",
                    "frame": f_idx,
                    "detail": f"Frame {f_idx}: expected {exp.dogs} dog(s), detected {counts['dog']}{suffix}.",
                })

            if counts["person"] != exp.people:
                dest_list.append({
                    "check": "people_count",
                    "frame": f_idx,
                    "detail": f"Frame {f_idx}: expected {exp.people} person(s), detected {counts['person']}{suffix}.",
                })

            if counts["bowl"] != exp.bowls:
                dest_list.append({
                    "check": "bowl_count",
                    "frame": f_idx,
                    "detail": f"Frame {f_idx}: expected {exp.bowls} bowl(s), detected {counts['bowl']}{suffix}.",
                })

            if counts["ball"] != exp.balls:
                dest_list.append({
                    "check": "ball_count",
                    "frame": f_idx,
                    "detail": f"Frame {f_idx}: expected {exp.balls} ball(s), detected {counts['ball']}{suffix}.",
                })

            if not exp.faces_visible and counts["face"] > 0:
                dest_list.append({
                    "check": "face_visibility",
                    "frame": f_idx,
                    "detail": f"Frame {f_idx}: faces_visible is false, but detected {counts['face']} visible face(s){suffix}.",
                })

        # Record pure CV fallback advisory warning if applicable
        if getattr(self.detector, "is_fallback", False):
            all_warnings.append({
                "check": "pure_cv_fallback",
                "frame": None,
                "detail": "Pure CV fallback active; quantity checks are advisory warnings and cannot certify pass. Real Florence-2 model required.",
            })

        # 3. Artifact Anomaly Checks (Dissolve/Ghosting, Bandana position, Color smear, Fence)
        metrics["artifacts"] = {}
        if getattr(self.spec, "check_dissolve", True):
            dissolve_issues = check_dissolve_ghosting(frames)
            all_fails.extend(dissolve_issues)
            metrics["artifacts"]["dissolve_ghosting_fails"] = len(dissolve_issues)

        if getattr(self.spec, "check_bandana", True):
            bandana_issues = check_bandana_position(frames)
            all_fails.extend(bandana_issues)
            metrics["artifacts"]["bandana_position_fails"] = len(bandana_issues)

        if getattr(self.spec, "check_color_smear", True):
            smear_issues = check_color_smear(frames)
            all_fails.extend(smear_issues)
            metrics["artifacts"]["color_smear_fails"] = len(smear_issues)

        if getattr(self.spec, "check_fence", False):
            fence_issues = check_fence_penetration(frames, enabled=True)
            all_fails.extend(fence_issues)
            metrics["artifacts"]["fence_penetration_fails"] = len(fence_issues)

        # 3. Identity Consistency Check (DINOv2)
        metrics["identity"] = {}
        if self.spec.identity_refs:
            for entity_key, ref_path in self.spec.identity_refs.items():
                crops = target_crops.get(entity_key, [])
                id_fails, id_warns, id_metrics = evaluate_identity_consistency(
                    crops=crops,
                    ref_image_path=ref_path,
                    extractor=self.identity_extractor,
                )
                all_fails.extend(id_fails)
                all_warnings.extend(id_warns)
                metrics["identity"][entity_key] = id_metrics

        # 4. Visual Stability Check (Brightness & Color Temp)
        stab_fails, stab_warns, stab_metrics = check_visual_stability(
            frames=frames,
            allow_light_change=self.spec.allow_light_change,
            prev_last_frame=prev_last_frame,
        )
        all_fails.extend(stab_fails)
        all_warnings.extend(stab_warns)
        metrics["stability"] = stab_metrics

        # 5. Motion Flow Check (Farneback)
        motion_fails, motion_warns, motion_metrics = check_motion(
            frames=frames,
            min_motion=self.spec.min_motion,
            max_motion=self.spec.max_motion,
        )
        all_fails.extend(motion_fails)
        all_warnings.extend(motion_warns)
        metrics["motion"] = motion_metrics

        # 6. Subtitle Safety Zone Check
        cap_fails, cap_metrics = check_caption_spec_safety(self.spec.caption)
        all_fails.extend(cap_fails)
        metrics["caption_safety"] = cap_metrics

        # Also inspect frames for burned-in occluded text
        for f_idx, frame in enumerate(frames):
            occ_issues = detect_occluded_text_in_frame(frame)
            for iss in occ_issues:
                all_warnings.append({
                    "check": "burned_in_text_occlusion",
                    "frame": f_idx,
                    "detail": f"Frame {f_idx} has high edge density in {iss['zone']} (potential occluded text).",
                })

        # 7. Audio Quality Check
        audio_fails, audio_warns, audio_metrics = check_audio_quality(media_path)
        all_fails.extend(audio_fails)
        all_warnings.extend(audio_warns)
        metrics["audio"] = audio_metrics

        # Format final report
        report_data = format_report_data(
            shot_id=self.spec.shot_id,
            fails=all_fails,
            warnings=all_warnings,
            metrics=metrics,
        )

        # Pure CV fallback: never certified pass
        if getattr(self.detector, "is_fallback", False):
            report_data["pass"] = False
            report_data["fallback_cv_active"] = True

        # Output JSON
        save_report_json(report_data, out_json_path)

        # Output visual report JPG
        if out_jpg_path is None:
            json_p = Path(out_json_path)
            out_jpg_path = json_p.with_suffix(".jpg")

        try:
            render_report_image(
                frames=frames,
                fails=all_fails,
                report_data=report_data,
                out_jpg_path=out_jpg_path,
                annotated_boxes_per_frame=annotated_boxes_per_frame,
            )
            report_data["report_jpg"] = str(out_jpg_path)
        except Exception as exc:
            logger.warning(f"Could not render report.jpg: {exc}")

        exit_code = 0 if report_data["pass"] else 1
        return report_data, exit_code
