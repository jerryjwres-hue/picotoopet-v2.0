"""Edit Decision List (EDL) timecode generation and export."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def format_timecode(seconds: float, fps: int = 30) -> str:
    """Format seconds into standard SMPTE timecode string HH:MM:SS:FF."""
    total_frames = int(round(seconds * fps))
    ff = total_frames % fps
    total_sec = total_frames // fps
    ss = total_sec % 60
    mm = (total_sec // 60) % 60
    hh = total_sec // 3600
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def generate_edl_text(
    plan_title: str,
    shot_timeline_map: List[Dict[str, Any]],
    fps: int = 30,
) -> str:
    """Generate formatted EDL text table."""
    lines = [
        f"# PICOTOO PET EDIT DECISION LIST (EDL)",
        f"# Title: {plan_title}",
        f"# Total Shots: {len(shot_timeline_map)}",
        f"# FPS: {fps}",
        f"#" + "-" * 78,
        f"{'SHOT_ID':<8} {'SRC_IN':<12} {'SRC_OUT':<12} {'REC_IN':<12} {'REC_OUT':<12} {'TRANSITION':<12} {'NOTES'}",
        f"#" + "-" * 78,
    ]

    for item in shot_timeline_map:
        shot = item["shot"]
        rec_in_tc = format_timecode(item["rec_in"], fps=fps)
        rec_out_tc = format_timecode(item["rec_out"], fps=fps)
        src_in_tc = format_timecode(shot.in_point, fps=fps)
        src_out_tc = format_timecode(shot.out_point, fps=fps)

        t_type = "HARD"
        if shot.transition_out:
            t_type = f"{shot.transition_out.type.upper()}_{shot.transition_out.dir.upper()}" if shot.transition_out.dir else shot.transition_out.type.upper()

        notes = []
        if shot.speed:
            notes.append("speed_curve")
        if shot.punch_in:
            notes.append(f"punch_in({shot.punch_in.scale}x)")
        if shot.caption:
            notes.append(f"sub('{shot.caption.text[:12]}...')")
        notes_str = ",".join(notes) if notes else "cut"

        line = f"{shot.shot_id:<8} {src_in_tc:<12} {src_out_tc:<12} {rec_in_tc:<12} {rec_out_tc:<12} {t_type:<12} {notes_str}"
        lines.append(line)

    lines.append(f"#" + "-" * 78)
    lines.append("")
    return "\n".join(lines)


def export_edl_file(edl_text: str, out_path: str | Path) -> None:
    """Save EDL text to file."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(edl_text)
