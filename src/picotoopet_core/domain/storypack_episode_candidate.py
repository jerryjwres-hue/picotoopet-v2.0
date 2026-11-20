"""Compile complete, explicitly supplied StoryPack parameters into a read-only Episode.

This fills the existing Episode contract without creating any permissions.
Client-provided references and prompts are UNTRUSTED until separate MASTER,
Owner, dynamic-story, budget and GPU admission checks all pass.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from copy import deepcopy
from typing import Any

from picotoopet_core.domain.episode import EpisodeValidationError, load_episode
from picotoopet_core.domain.storypack import StoryPackV1, storypack_preview

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMPLETION_KEYS = frozenset({"shots", "edit"})
_SHOT_REQUIRED_KEYS = frozenset({
    "shot_id", "emotion", "camera", "first_frame", "video", "audio", "transition_out",
})
_SHOT_OPTIONAL_KEYS = frozenset({"last_frame", "caption"})
_TRUST_GATES = [
    "OWNER_PRINCIPAL_CURRENT",
    "STORYBOARD_SHA_BOUND_APPROVAL",
    "CHARACTER_SCENE_STYLE_MASTER_RIGHTS_AND_SHA",
    "FIRST_FRAME_REFERENCES_RESOLVED_AND_APPROVED",
    "DYNAMIC_STORY_POLICY_COMPATIBLE",
    "GPU_HOLD_SEPARATELY_RELEASED",
    "VISUAL_QC_AND_FINAL_HUMAN_ACCEPT",
]


class EpisodeCandidateError(ValueError):
    """Stable input-contract violation; never return a partly trusted Episode."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _sha256_document(value: dict[str, Any]) -> str:
    # 输入规范化与 Mac/Windows 上的后续 SHA 对账使用相同序列化参数。
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _narrative_video_prompt(
    source_shot: Any, supplied_prompt: str,
) -> str:
    """Bind the frozen StoryPack's cause/effect beats into the *rendered* prompt.

    This is deterministic text assembly, not a semantic or visual QC pass.
    Existing human-authored cinematic guidance remains intact at the end.
    """
    if source_shot.handoff == "continuous":
        link = "Continue from the preceding shot's final visible state. "
    elif source_shot.handoff == "scene_change":
        link = "This shot starts after a deliberate scene cut, without invented events. "
    else:
        link = "Start only the current shot; do not jump to later story events. "
    return (
        "Narrative motion constraints for this single shot: "
        + link
        + f"Starting situation: {source_shot.state_in}. "
        + f"Visible action: {source_shot.action}. "
        + f"Required ending situation: {source_shot.state_out}. "
        + f"Story reason: {source_shot.because}. "
        + f"Director's visual instructions: {supplied_prompt}"
    )


def complete_storypack_episode_preview(
    pack: StoryPackV1,
    expected_storypack_sha256: str,
    completion: dict[str, Any],
) -> dict[str, Any]:
    """Complete known Episode fields while preserving every StoryPack-owned value."""
    preview = storypack_preview(pack)
    source_sha = preview["storypack_sha256"]
    if (
        not isinstance(expected_storypack_sha256, str)
        or _SHA256.fullmatch(expected_storypack_sha256) is None
        or not hmac.compare_digest(source_sha, expected_storypack_sha256)
    ):
        raise EpisodeCandidateError("STORYPACK_SOURCE_SHA_STALE")

    # 用户补全内容只准包含编译器缺失的值，不能覆盖剧集身份与镜号。
    if not isinstance(completion, dict) or set(completion) != _COMPLETION_KEYS:
        raise EpisodeCandidateError("EPISODE_COMPLETION_FIELDS_INVALID")
    edits, supplied_shots = completion["edit"], completion["shots"]
    if not isinstance(edits, dict) or set(edits) != {"loudness_lufs"}:
        raise EpisodeCandidateError("EPISODE_EDIT_SCOPE_INVALID")
    if not isinstance(supplied_shots, list) or len(supplied_shots) != len(pack.shots):
        raise EpisodeCandidateError("EPISODE_SHOT_SET_MISMATCH")

    # 只从已经验证的 StoryPack 草稿创建骨架，不读取任何客户端权威字段。
    candidate = preview["production_compilation"]["episode_draft"]
    candidate["edit"]["loudness_lufs"] = edits["loudness_lufs"]
    for index, (source_shot, supplied) in enumerate(
        zip(pack.shots, supplied_shots, strict=True)
    ):
        if not isinstance(supplied, dict):
            raise EpisodeCandidateError("EPISODE_SHOT_FIELDS_INVALID")
        keys = set(supplied)
        if not _SHOT_REQUIRED_KEYS <= keys or not keys <= (
            _SHOT_REQUIRED_KEYS | _SHOT_OPTIONAL_KEYS
        ):
            raise EpisodeCandidateError("EPISODE_SHOT_FIELDS_INVALID")
        if supplied["shot_id"] != source_shot.id:
            raise EpisodeCandidateError("EPISODE_SHOT_ORDER_OR_ID_DRIFT")
        # 空列表也不能冒充已选好的首帧；文件是否可信另由 MASTER 门禁确认。
        first = supplied["first_frame"]
        if not isinstance(first, dict) or not isinstance(first.get("refs"), list) or not first["refs"]:
            raise EpisodeCandidateError("EPISODE_FIRST_FRAME_REFS_REQUIRED")
        video = supplied["video"]
        if not isinstance(video, dict) or not isinstance(video.get("seeds"), list):
            raise EpisodeCandidateError("EPISODE_SEED_SET_INVALID")
        seeds = video["seeds"]
        if len(seeds) != len(set(str(s) for s in seeds)):
            raise EpisodeCandidateError("EPISODE_SEED_DUPLICATE")
        for key in (_SHOT_REQUIRED_KEYS | _SHOT_OPTIONAL_KEYS) - {"shot_id"}:
            if key in supplied:
                # 补全数据是用户原文，不允许后续导演 Prompt 拼装反向修改来源。
                candidate["shots"][index][key] = deepcopy(supplied[key])

        # 关键修复：StoryPack 的状态与因果不再只留在审稿元数据中。
        # 直接绑定到将交给原有生成 Worker 的 first/last still 与 video.prompt。
        # 不生成新资产、不覆盖视频种子/摄影机参数，也不授予任何 GPU 权限。
        shot_plan = candidate["shots"][index]
        video_plan = shot_plan["video"]
        video_plan["prompt"] = _narrative_video_prompt(
            source_shot, video_plan["prompt"]
        )
        if source_shot.handoff == "continuous" or index == 0:
            shot_plan["first_frame"]["prompt"] = (
                f"Opening story state to depict: {source_shot.state_in}. "
                + shot_plan["first_frame"]["prompt"]
            )
        if shot_plan.get("last_frame") is not None:
            shot_plan["last_frame"]["prompt"] = (
                f"Final story state to depict: {source_shot.state_out}. "
                + shot_plan["last_frame"]["prompt"]
            )

    # 使用既有 Episode 权威验证器，不新增平行格式或执行器。
    try:
        encoded = json.dumps(
            candidate, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        episode = load_episode(encoded, as_yaml=False)
    except (TypeError, ValueError, EpisodeValidationError) as error:
        raise EpisodeCandidateError("EPISODE_COMPLETION_CONTRACT_INVALID") from error

    finalized = episode.model_dump(mode="json")
    return {
        "contract": "picotoo.episode-candidate-preview.v1",
        "status": "EPISODE_CONTRACT_VALID_UNTRUSTED",
        "source_storypack_sha256": source_sha,
        "candidate_episode_sha256": _sha256_document(finalized),
        "episode_contract_valid": True,
        "episode": finalized,
        "shot_context": preview["production_compilation"]["shot_context"],
        "missing_trust_gates": _TRUST_GATES,
        "references_trusted": False,
        "owner_approved": False,
        "can_queue": False,
        "can_generate": False,
        "can_publish": False,
    }
