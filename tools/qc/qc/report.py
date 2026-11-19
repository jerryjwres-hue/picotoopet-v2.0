"""QC report serialization (JSON) and visual collage generation (report.jpg)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import cv2
import numpy as np


def calculate_qc_score(fails: List[Dict[str, Any]], warnings: List[Dict[str, Any]]) -> int:
    """Calculate overall QC score from 0 to 100."""
    score = 100
    # Each distinct failure heavily impacts passability
    score -= len(fails) * 25
    # Warnings lightly reduce polish score
    score -= len(warnings) * 5
    return max(0, min(100, score))


def format_report_data(
    shot_id: str,
    fails: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
    metrics: Dict[str, Any],
) -> Dict[str, Any]:
    """Construct standard report dictionary."""
    is_pass = (len(fails) == 0)
    score = calculate_qc_score(fails, warnings)

    return {
        "shot_id": shot_id,
        "pass": is_pass,
        "score": score,
        "fails": fails,
        "warnings": warnings,
        "metrics": metrics,
    }


def save_report_json(report_data: Dict[str, Any], out_path: str | Path) -> None:
    """Write report to JSON file."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)


def render_report_image(
    frames: List[np.ndarray],
    fails: List[Dict[str, Any]],
    report_data: Dict[str, Any],
    out_jpg_path: str | Path,
    annotated_boxes_per_frame: Optional[Dict[int, List[Any]]] = None,
) -> None:
    """Generate visual collage (report.jpg) highlighting problem frames or keyframes."""
    out_p = Path(out_jpg_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    thumb_w, thumb_h = 360, 640
    problem_frame_indices = set()
    for f in fails:
        if f.get("frame") is not None:
            problem_frame_indices.add(int(f["frame"]))

    # Select frames to showcase: problem frames first, or 3-4 evenly spaced frames
    selected_indices: List[int] = []
    if problem_frame_indices:
        selected_indices = sorted(list(problem_frame_indices))[:6]
    elif frames:
        n = len(frames)
        if n <= 4:
            selected_indices = list(range(n))
        else:
            selected_indices = [0, n // 3, (2 * n) // 3, n - 1]

    if not selected_indices and frames:
        selected_indices = [0]

    thumbs: List[np.ndarray] = []
    for idx in selected_indices:
        if idx >= len(frames):
            continue
        frame_copy = frames[idx].copy()

        # Draw detected boxes if available
        if annotated_boxes_per_frame and idx in annotated_boxes_per_frame:
            for box in annotated_boxes_per_frame[idx]:
                x1, y1, x2, y2 = box.box_xyxy
                color = (0, 0, 255) if idx in problem_frame_indices else (0, 255, 0)
                cv2.rectangle(frame_copy, (x1, y1), (x2, y2), color, 3)
                label_txt = f"{box.label} {box.confidence:.2f}"
                cv2.putText(
                    frame_copy, label_txt, (x1, max(30, y1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2, cv2.LINE_AA,
                )

        # Stamp frame index badge
        badge_color = (0, 0, 220) if idx in problem_frame_indices else (0, 180, 0)
        cv2.putText(
            frame_copy, f"Frame {idx}", (30, 60),
            cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 0, 0), 6, cv2.LINE_AA,
        )
        cv2.putText(
            frame_copy, f"Frame {idx}", (30, 60),
            cv2.FONT_HERSHEY_SIMPLEX, 1.3, badge_color, 2, cv2.LINE_AA,
        )

        thumb = cv2.resize(frame_copy, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA)
        thumbs.append(thumb)

    if not thumbs:
        # Fallback blank canvas
        canvas = np.zeros((thumb_h + 100, thumb_w, 3), dtype=np.uint8)
        thumbs.append(canvas[:thumb_h, :thumb_w])

    # Arrange thumbnails horizontally (or 2 rows if > 3)
    if len(thumbs) <= 4:
        row = np.hstack(thumbs)
    else:
        # 2 rows
        mid = (len(thumbs) + 1) // 2
        r1_list = thumbs[:mid]
        r2_list = thumbs[mid:]
        while len(r2_list) < len(r1_list):
            r2_list.append(np.zeros_like(r1_list[0]))
        row = np.vstack([np.hstack(r1_list), np.hstack(r2_list)])

    total_w = row.shape[1]
    banner_h = 100
    banner = np.zeros((banner_h, total_w, 3), dtype=np.uint8)

    is_pass = report_data.get("pass", False)
    score = report_data.get("score", 0)
    shot_id = report_data.get("shot_id", "SHOT")

    status_str = "PASS" if is_pass else "FAIL"
    status_color = (0, 200, 0) if is_pass else (0, 0, 230)

    # Top banner text
    text_title = f"QC: {shot_id} | Status: {status_str} | Score: {score}/100"
    cv2.putText(
        banner, text_title, (30, 55),
        cv2.FONT_HERSHEY_SIMPLEX, 1.2, status_color, 3, cv2.LINE_AA,
    )

    fails_count = len(report_data.get("fails", []))
    warns_count = len(report_data.get("warnings", []))
    sub_title = f"Fails: {fails_count} | Warnings: {warns_count} | Frames sampled: {len(frames)}"
    cv2.putText(
        banner, sub_title, (30, 85),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1, cv2.LINE_AA,
    )

    collage = np.vstack([banner, row])
    ok, encoded = cv2.imencode(".jpg", collage, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise OSError("Could not encode QC report preview")
    out_p.write_bytes(encoded.tobytes())
