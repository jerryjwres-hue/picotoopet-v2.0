"""Bounded StoryPack → canonical Human Goal intake proposal.

The returned request is a user-reviewable proposal, never a submitted Goal,
an approved Creative Package, an executable Plan or GPU authorization.
"""

from __future__ import annotations

from picotoopet_core.domain.storypack import OUTPUT_PROFILES, StoryPackV1

_GOAL_OBJECTIVE_LIMIT = 2000
_P0_SHOTS = 3
_P0_SECONDS_PER_SHOT = 4


def build_storypack_goal_intake(
    pack: StoryPackV1, storypack_sha256: str, *, scoped_dynamic: bool = False,
) -> dict:
    """Reuse the existing `video.creative` Goal route instead of inventing an executor."""

    width, height, fps, seconds = OUTPUT_PROFILES[pack.output_profile]
    reasons: list[str] = []
    # Dynamic proposals must never enter the existing static-only trusted pipeline.
    if pack.dynamic_motion is not None and not scoped_dynamic:
        reasons.append("DYNAMIC_SCOPED_GOAL_REQUIRED")
    if pack.output_profile != "p0_landscape" or (
        width, height, fps, seconds
    ) != (832, 480, 24, _P0_SECONDS_PER_SHOT):
        reasons.append("P0_OUTPUT_PROFILE_UNSUPPORTED")
    if len(pack.shots) != _P0_SHOTS:
        reasons.append("P0_REQUIRES_EXACTLY_THREE_SHOTS")
    if any(shot.cast_refs == [] for shot in pack.shots):
        reasons.append("P0_REQUIRES_PET_IN_EVERY_SHOT")

    # 场景/角色 ID 只属于未经认证的编辑提示，不会被登记成权威来源或许可。
    # Goal 服务仍须由真实发现和来源验证生成 Creative Package，不能信任本文字。
    lines = [
        "纯宠物视频，质量优先故事。明确要求3个镜头，每个镜头4秒。",
        "目标：通过现有 Mac Core 本地 video.creative Goal 完成证据核验、导演创意及正式生产规划；不直接执行 GPU。",
        f"故事：{pack.title}。",
        f"目标与结局：{pack.story.goal}；{pack.story.payoff}",
        "创作边界：832×480、24fps、每镜97渲染帧；所有角色、场景、风格来源及主人权限必须真实核验，未授权则停在 NeedsHuman。",
        f"角色草稿标签：{pack.character_ref}；场景草稿标签：{pack.scene_ref}；风格草稿标签：{pack.style_ref or '未提供'}。这些标签不是已认证资产。",
    ]
    for shot in pack.shots:
        lines.append(
            f"{shot.id}：{shot.action}。"
            f"起始：{shot.state_in}。结束：{shot.state_out}。"
            f"动机：{shot.because}。"
            f"切换：{shot.handoff}。"
        )
    if pack.dynamic_motion is not None and scoped_dynamic:
        # The explicitly reviewed motion choices govern the action projection.
        lines.append("动态动作以主人审核的分镜提案为准；禁止静态眨眼替代或改写动作。")
    objective = "\n".join(lines)
    if len(objective) > _GOAL_OBJECTIVE_LIMIT:
        reasons.append("GOAL_OBJECTIVE_OVER_2000_CHARS")

    return {
        "contract": "picotoo.storypack.canonical-goal-intake.v1",
        "storypack_sha256": storypack_sha256,
        "goal_type": "video.creative",
        "depth": "standard",
        "local_video_preferred": True,
        "objective": objective if not reasons else None,
        "objective_character_count": len(objective),
        "ready_for_user_submission": not reasons,
        "blocking_reasons": reasons,
        "requires_explicit_user_action": True,
        "source_evidence_verified": False,
        "creative_package_approved": False,
        "production_plan_executable": False,
        "owner_approved": False,
        "gpu_post_authorized": False,
        "next_step": (
            "DYNAMIC_OWNER_REVIEW_POLICY_REQUIRED"
            if pack.dynamic_motion is not None
            else "REVIEW_AND_SUBMIT_EXISTING_HUMAN_GOAL_API"
            if not reasons else "REVISE_STORYPACK_MANUALLY"
        ),
    }
