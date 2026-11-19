"""Video assembly pipeline orchestrating transitions, effects, captions, audio, and encoding."""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np
from scipy.io import wavfile

from edit.audio.bus import AudioBusMixer
from edit.captions.bounce import render_caption_on_frame
from edit.edl import export_edl_file, format_timecode, generate_edl_text
from edit.fx.punch_in import apply_punch_in_zoom, compute_punch_in_scale
from edit.fx.speed_curve import SpeedCurveInterpolator
from edit.plan import EditPlan, ShotPlan
from edit.strip import generate_thumbnail_strip
from edit.transitions.base import apply_transition
from edit.transitions.j_l_cut import compute_jl_cut_audio_intervals

logger = logging.getLogger("edit.assembler")


class VideoReaderCache:
    """Helper to cache and seek frames from video files."""

    def __init__(self, video_path: str):
        self.path = video_path
        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            raise FileNotFoundError(f"Cannot open video source: {video_path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))

    def get_frame_at_time(self, time_sec: float) -> np.ndarray:
        """Fetch frame at source timestamp (in seconds)."""
        frame_idx = max(0, min(self.total_frames - 1, int(round(time_sec * self.fps))))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.cap.read()
        if not ret or frame is None:
            return np.zeros((1920, 1080, 3), dtype=np.uint8)
        return frame

    def close(self):
        if self.cap and self.cap.isOpened():
            self.cap.release()


def assemble_video_pipeline(
    plan: EditPlan,
    out_video_path: str | Path,
    out_edl_path: Optional[str | Path] = None,
    out_strip_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Execute complete video assembly according to EditPlan."""
    out_p = Path(out_video_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    if out_edl_path is None:
        out_edl_path = out_p.with_name("edl.txt")
    if out_strip_path is None:
        out_strip_path = out_p.with_name("strip.jpg")

    canvas_w, canvas_h = plan.size
    fps = plan.fps

    # 1. Calculate timeline segment schedule for each shot
    shot_timeline_map: List[Dict[str, Any]] = []
    current_timeline_time = 0.0

    for i, shot in enumerate(plan.shots):
        raw_cut_dur = max(0.1, shot.out_point - shot.in_point)
        interpolator = SpeedCurveInterpolator(shot.speed)
        if shot.speed:
            avg_speed = np.mean([kp.x for kp in shot.speed])
            timeline_dur = raw_cut_dur / max(0.1, avg_speed)
        else:
            timeline_dur = raw_cut_dur

        rec_in = current_timeline_time
        rec_out = rec_in + timeline_dur

        trans_dur = 0.0
        if shot.transition_out and i < len(plan.shots) - 1:
            trans_dur = min(shot.transition_out.dur, timeline_dur * 0.5)

        shot_timeline_map.append({
            "index": i,
            "shot": shot,
            "rec_in": rec_in,
            "rec_out": rec_out,
            "timeline_dur": timeline_dur,
            "trans_dur": trans_dur,
            "interpolator": interpolator,
        })

        current_timeline_time = rec_out - trans_dur

    total_duration_sec = current_timeline_time
    total_output_frames = int(round(total_duration_sec * fps))

    # 2. Render each shot's processed frames
    shot_rendered_frames: List[List[np.ndarray]] = []
    thumbnail_cards: List[Dict[str, Any]] = []

    for item in shot_timeline_map:
        shot: ShotPlan = item["shot"]
        dur: float = item["timeline_dur"]
        interp: SpeedCurveInterpolator = item["interpolator"]
        num_frames = max(1, int(round(dur * fps)))

        reader = VideoReaderCache(shot.video)
        frames_for_shot: List[np.ndarray] = []

        for f_idx in range(num_frames):
            t_shot = f_idx / float(fps)
            t_source_offset = interp.map_timeline_to_source_time(t_shot)
            src_t = shot.in_point + t_source_offset

            frame = reader.get_frame_at_time(src_t)
            if frame.shape[:2] != (canvas_h, canvas_w):
                frame = cv2.resize(frame, (canvas_w, canvas_h), interpolation=cv2.INTER_LINEAR)

            scale = compute_punch_in_scale(t_shot, shot.punch_in)
            frame = apply_punch_in_zoom(frame, scale)

            if shot.caption:
                cap = shot.caption
                if cap.start <= t_shot <= cap.end:
                    time_in_sub = t_shot - cap.start
                    frame = render_caption_on_frame(
                        frame_bgr=frame,
                        text=cap.text,
                        time_since_start=time_in_sub,
                        y_ratio=cap.y_ratio,
                        font_path=plan.font,
                    )

            frames_for_shot.append(frame)

        reader.close()
        shot_rendered_frames.append(frames_for_shot)

        mid_idx = len(frames_for_shot) // 2
        mid_frame = frames_for_shot[mid_idx].copy()
        thumbnail_cards.append({
            "shot_id": shot.shot_id,
            "frame": mid_frame,
            "timecode": f"{format_timecode(item['rec_in'], fps=fps)} - {format_timecode(item['rec_out'], fps=fps)}",
        })

    # 3. Stitch shots with transitions into master video sequence
    master_frames: List[np.ndarray] = []

    for i in range(len(shot_rendered_frames)):
        cur_frames = shot_rendered_frames[i]
        item = shot_timeline_map[i]
        shot = item["shot"]
        trans_dur = item["trans_dur"]
        trans_frames_count = int(round(trans_dur * fps))

        if i == len(shot_rendered_frames) - 1 or trans_frames_count <= 0 or not shot.transition_out:
            master_frames.extend(cur_frames)
        else:
            next_frames = shot_rendered_frames[i + 1]
            t_spec = shot.transition_out
            t_type = t_spec.type.lower()

            body_frames = cur_frames[:-trans_frames_count] if trans_frames_count < len(cur_frames) else []
            master_frames.extend(body_frames)

            overlap_out = cur_frames[-trans_frames_count:] if trans_frames_count < len(cur_frames) else cur_frames
            overlap_in = next_frames[:trans_frames_count] if trans_frames_count < len(next_frames) else next_frames

            actual_trans_len = min(len(overlap_out), len(overlap_in))
            t_params = {"dir": t_spec.dir, "offset": t_spec.offset}

            for t_idx in range(actual_trans_len):
                prog = t_idx / float(actual_trans_len)
                frame_trans = apply_transition(
                    type_name=t_type,
                    frame_out=overlap_out[t_idx],
                    frame_in=overlap_in[t_idx],
                    progress=prog,
                    params=t_params,
                )
                master_frames.append(frame_trans)

            shot_rendered_frames[i + 1] = next_frames[actual_trans_len:]

    final_video_duration = len(master_frames) / float(fps)

    # 4. Render 3-Bus Mastered Audio
    audio_mixer = AudioBusMixer(sample_rate=44100)
    mastered_audio = audio_mixer.mix_timeline(
        plan=plan,
        total_duration_sec=final_video_duration,
        shot_timeline_map=shot_timeline_map,
    )

    # 5. Output Video via FFmpeg: H.264 High, CRF 18, -preset veryfast, AAC 192k
    temp_dir = tempfile.mkdtemp(prefix="picotoo_edit_")
    temp_wav_path = Path(temp_dir) / "mastered_audio.wav"
    wavfile.write(str(temp_wav_path), 44100, (mastered_audio * 32767.0).astype(np.int16))

    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{canvas_w}x{canvas_h}",
        "-pix_fmt", "bgr24",
        "-r", str(fps),
        "-i", "pipe:0",
        "-i", str(temp_wav_path),
        "-c:v", "libx264",
        "-profile:v", "high",
        "-crf", "18",
        "-preset", "veryfast",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        str(out_p),
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    raw_payload = b"".join(f.tobytes() for f in master_frames)
    _, stderr_data = proc.communicate(input=raw_payload)

    # Cleanup temp audio
    shutil.rmtree(temp_dir, ignore_errors=True)

    if proc.returncode != 0:
        err = stderr_data.decode("utf-8", errors="ignore")
        raise RuntimeError(f"FFmpeg encoding failed (code {proc.returncode}): {err}")

    # 6. Generate EDL file (edl.txt)
    edl_text = generate_edl_text(
        plan_title="Maotai Short Film",
        shot_timeline_map=shot_timeline_map,
        fps=fps,
    )
    export_edl_file(edl_text, out_edl_path)

    # 7. Generate Thumbnail Strip (strip.jpg)
    generate_thumbnail_strip(
        shot_thumbnails=thumbnail_cards,
        out_path=out_strip_path,
    )

    return {
        "final_video": str(out_p),
        "edl_file": str(out_edl_path),
        "strip_image": str(out_strip_path),
        "total_duration_sec": round(final_video_duration, 2),
        "total_frames": len(master_frames),
        "shot_count": len(plan.shots),
    }
