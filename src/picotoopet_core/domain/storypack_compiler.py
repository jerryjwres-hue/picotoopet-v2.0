"""Non-executable StoryPack -> Episode contract bridge.

The existing Episode model is authoritative. Never synthesize missing prompt,
camera, reference files, negative prompt, seed, Foley, or owner authority.
"""

from __future__ import annotations

from pydantic import ValidationError

from picotoopet_core.domain.episode import Episode
from picotoopet_core.domain.storypack import OUTPUT_PROFILES, StoryPackV1


def compile_episode_draft(pack: StoryPackV1, source_sha256: str) -> dict:
    """Return a deterministic review draft, not a runnable Episode."""
    width, height, fps, seconds = OUTPUT_PROFILES[pack.output_profile]
    cast = list(dict.fromkeys([pack.character_ref, *pack.supporting_character_refs]))
    scenes = list(dict.fromkeys([pack.scene_ref, *pack.additional_scene_refs]))

    # 实际生产必须绑定被批准的资产；这里仅保存引用 ID，绝不猜测本地路径。
    shot_contracts = []
    for shot in pack.shots:
        shot_contracts.append(
            {
                "shot_id": shot.id,
                "seconds": float(seconds),
                "beat": shot.action,
                "emotion": None,             # 待导演确定，不猜测角色心理。
                "camera": None,              # 待导演编写镜头参数。
                "first_frame": None,         # 待可信资产解析和首帧审批。
                "last_frame": None,          # 必须由 handoff 策略决定是否提供。
                "video": None,               # 不允许 LLM 文本自动获得 GPU 参数。
                "audio": None,               # 需确定拟音、旁白与版权素材。
                "transition_out": None,      # 不从场景变化猜测剪辑策略。
                "caption": None,
            }
        )

    draft = {
        "episode_id": pack.episode_id,
        "title": pack.title,
        "target_seconds": float(len(pack.shots) * seconds),
        "characters": [],                 # 角色须来自资产登记表的可信绑定。
        "shots": shot_contracts,
        "edit": {
            "fps": float(fps),
            "size": [width, height],
            "loudness_lufs": None,         # 等候最终音频与交付规范审批。
        },
    }

    # 现有 Episode 是生产权威契约；未完成的草稿必须保持无效状态。
    try:
        Episode.model_validate(draft)
    except ValidationError:
        pass
    else:
        raise RuntimeError("Incomplete StoryPack draft unexpectedly passed Episode validation")

    return {
        "contract": "picotoo.episode-draft.v1",
        "source_storypack_sha256": source_sha256,
        "episode_schema": "picotoopet_core.domain.episode.Episode",
        "episode_contract_valid": False,
        "executable": False,
        "episode_draft": draft,
        "shot_context": [
            {
                "shot_id": shot.id,
                "scene_ref": shot.scene_ref or pack.scene_ref,
                "cast_refs": [pack.character_ref] if shot.cast_refs is None else shot.cast_refs,
                "state_in": shot.state_in,
                "action": shot.action,
                "state_out": shot.state_out,
                "because": shot.because,
                "depends_on": shot.depends_on,
                "handoff": shot.handoff,
            }
            for shot in pack.shots
        ],
        # 创意 LLM 只补差异字段，重复的角色/场景 Bible 不进入每镜 Prompt。
        "shared_asset_refs": {
            "characters": cast,
            "scenes": scenes,
            "style": pack.style_ref,
            "verified": False,
        },
        "missing_contract_fields": {
            "episode": ["characters[trusted]", "edit.loudness_lufs"],
            "each_shot": [
                "emotion",
                "camera.move",
                "camera.lens",
                "camera.speed",
                "first_frame.refs[trusted]",
                "first_frame.prompt",
                "video.prompt",
                "video.negative",
                "video.seeds",
                "audio.vocal_from",
                "audio.foley",
                "transition_out.type",
                "transition_out.offset_s",
            ],
        },
        "missing_trust_gates": [
            "OWNER_PRINCIPAL_VERIFIED",
            "ASSET_RIGHTS_AND_MASTER_SHA_LOCK",
            "STORYBOARD_APPROVED_FOR_SOURCE_SHA",
            "GPU_HOLD_RELEASED_BY_SEPARATE_AUTHORITY",
        ],
        "can_queue": False,
        "can_generate": False,
        "can_publish": False,
    }
