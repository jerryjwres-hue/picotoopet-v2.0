"""Deterministic episode draw preflight; estimates work rather than GPU wall time.

This gate is independent of OwnerPrincipal, lease, worker allowlists and GPU HOLD.
One episode may request a bounded batch of seeds; a later batch must be a new,
explicitly accepted production revision, not an unbounded automatic loop.
"""

from __future__ import annotations

from dataclasses import dataclass

from picotoopet_core.domain.episode import Episode, EpisodeValidationError


@dataclass(frozen=True, slots=True)
class EpisodeBudgetPolicy:
    max_takes_per_shot: int = 8                 # 单镜最多 8 次候选抽卡。
    max_takes_per_episode: int = 48             # 每集首次生成候选总数上限。
    max_reserved_video_seconds: float = 720.0  # 计入现有两次 QC 重抽的最坏情形。
    qc_redo_rounds: int = 2                     # 与现有 ExecutorService 重抽轮次一致。


def inspect_episode_budget(episode: Episode, policy: EpisodeBudgetPolicy) -> dict:
    """Pure read-only estimate; no token consumption, DB writes or GPU admission."""
    takes = [len(shot.video.seeds) for shot in episode.shots]
    initial_takes = sum(takes)
    initial_video_seconds = sum(
        len(shot.video.seeds) * shot.seconds for shot in episode.shots
    )
    attempt_multiplier = 1 + policy.qc_redo_rounds
    reserved_seconds = initial_video_seconds * attempt_multiplier
    reasons = []
    for index, shot in enumerate(episode.shots):
        if len(shot.video.seeds) > policy.max_takes_per_shot:
            reasons.append(f"shots[{index}].video.seeds：超过单镜候选上限")
        if len(set(shot.video.seeds)) != len(shot.video.seeds):
            # 相同提示词与种子在同批重复，一般只会浪费本地 GPU 计算。
            reasons.append(f"shots[{index}].video.seeds：同一批不能重复种子")
    if initial_takes > policy.max_takes_per_episode:
        reasons.append("video.seeds：超过每集首次候选总数上限")
    if reserved_seconds > policy.max_reserved_video_seconds:
        reasons.append("video.seeds：包含 QC 重抽的预计视频秒数超出预算")
    return {
        "episode_id": episode.episode_id,
        "allowed": not reasons,
        "errors": reasons,
        "shot_count": len(episode.shots),
        "initial_video_takes": initial_takes,
        "max_reserved_video_takes": initial_takes * attempt_multiplier,
        "initial_video_seconds": round(initial_video_seconds, 3),
        "max_reserved_video_seconds": round(reserved_seconds, 3),
        "qc_redo_rounds": policy.qc_redo_rounds,
        "limits": {
            "max_takes_per_shot": policy.max_takes_per_shot,
            "max_takes_per_episode": policy.max_takes_per_episode,
            "max_reserved_video_seconds": policy.max_reserved_video_seconds,
        },
        # 不是 CUDA 实测活跃时间，也不等于本地电费或 GPU 授权。
        "metric": "REQUESTED_VIDEO_OUTPUT_SECONDS_NOT_GPU_WALL_TIME",
        "gpu_authorized": False,
        "read_only": True,
    }


def enforce_episode_budget(episode: Episode, policy: EpisodeBudgetPolicy) -> dict:
    """Fail closed before any new episode/queue row is persisted."""
    result = inspect_episode_budget(episode, policy)
    if not result["allowed"]:
        raise EpisodeValidationError("；".join(result["errors"]))
    return result
