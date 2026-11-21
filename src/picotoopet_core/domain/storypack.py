"""V3.1 StoryPack validation ported to real Mac Core 2.3 (read-only, JSON only).

Source: V3.1 storypack.py; structural field and continuity validators preserved.
This adapter does not compile executable ProductionPlans or approve render jobs.

Original contract: strict, side-effect-free story import and production preview.

This module NEVER enqueues production tasks, authorizes GPU, or trusts user supplied paths.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from picotoopet_core.production.profile import frame_count_for_duration

Identifier = Annotated[
    str,
    Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"),
]
AssetRef = Annotated[
    str,
    Field(min_length=3, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"),
]
Text = Annotated[str, Field(min_length=1, max_length=1200)]

# 这里只定义预览规格；它们不是 GPU 生成许可证。
OUTPUT_PROFILES = {
    "p0_landscape": (832, 480, 24, 4),
    "design_portrait": (480, 832, 24, 4),
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class StoryIntent(_Strict):
    goal: Text
    payoff: Text


class StoryShot(_Strict):
    id: Identifier
    action: Text
    state_in: Text
    state_out: Text
    because: Text
    scene_ref: AssetRef | None = None                # 单镜场景可覆盖默认场景。
    cast_refs: list[AssetRef] | None = None          # None=主角；[]=无角色镜头。
    depends_on: list[Identifier] = Field(default_factory=list, max_length=30)
    handoff: Literal["cut", "continuous", "scene_change"] = "cut"


class StoryPackV1(_Strict):
    schema: Literal["picotoo.storypack.v1"]
    episode_id: Identifier
    title: Text
    output_profile: Literal["p0_landscape", "design_portrait"] = "p0_landscape"
    character_ref: AssetRef
    supporting_character_refs: list[AssetRef] = Field(default_factory=list, max_length=12)
    scene_ref: AssetRef
    additional_scene_refs: list[AssetRef] = Field(default_factory=list, max_length=30)
    style_ref: AssetRef | None = None
    story: StoryIntent
    shots: list[StoryShot] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def check_dependencies(self) -> StoryPackV1:
        seen: set[str] = set()
        previous: StoryShot | None = None
        previous_scene: str | None = None
        allowed_cast = {ref.casefold() for ref in [self.character_ref, *self.supporting_character_refs]}
        allowed_scenes = {ref.casefold() for ref in [self.scene_ref, *self.additional_scene_refs]}
        if len(allowed_cast) != 1 + len(self.supporting_character_refs):
            raise ValueError("supporting_character_refs: duplicate characters")
        if len(allowed_scenes) != 1 + len(self.additional_scene_refs):
            raise ValueError("additional_scene_refs: duplicate scenes")
        for index, shot in enumerate(self.shots):
            folded = shot.id.casefold()
            if folded in seen:
                raise ValueError(f"shots[{index}].id: duplicated shot ID")
            dependencies = [item.casefold() for item in shot.depends_on]
            if len(set(dependencies)) != len(dependencies):
                raise ValueError(f"shots[{index}].depends_on: duplicated dependency")
            if any(item not in seen for item in dependencies):
                raise ValueError(f"shots[{index}].depends_on: references must precede this shot")
            actual_scene = (shot.scene_ref or self.scene_ref).casefold()
            if actual_scene not in allowed_scenes:
                raise ValueError(f"shots[{index}].scene_ref: scene not declared in the package")
            cast = [ref.casefold() for ref in (
                [self.character_ref] if shot.cast_refs is None else shot.cast_refs
            )]
            if len(cast) != len(set(cast)) or any(ref not in allowed_cast for ref in cast):
                raise ValueError(f"shots[{index}].cast_refs: unknown or duplicate character")
            if shot.handoff == "continuous":
                if previous is None or previous.id.casefold() not in dependencies:
                    raise ValueError(f"shots[{index}]: continuous handoff requires previous shot")
                if previous.state_out.strip() != shot.state_in.strip():
                    raise ValueError(f"shots[{index}]: state_in must match previous state_out")
                if previous_scene != actual_scene:
                    raise ValueError(f"shots[{index}]: continuous handoff cannot change scenes")
            seen.add(folded)
            previous = shot
            previous_scene = actual_scene
        return self


class StoryPackError(ValueError):
    """Invalid StoryPack content; the source remains unchanged."""


def _unique_json_pairs(pairs):
    # 不允许模型在相同 JSON key 下提交不同版本来误导审核者。
    value = {}
    for key, item in pairs:
        if key in value:
            raise StoryPackError("StoryPack JSON has duplicate object keys")
        value[key] = item
    return value


def parse_storypack(source: bytes, *, as_yaml: bool = False) -> StoryPackV1:
    """验证 V3.1 StoryPack 结构；2.3 适配阶段只支持 JSON，不引入新依赖。"""
    if as_yaml:
        raise StoryPackError("STORYPACK_YAML_NOT_SUPPORTED_ON_23")
    try:
        # 只允许 UTF-8 JSON；重复键及模型输出的 NaN/Infinity 均拒绝。
        def reject_nonfinite(_: str) -> None:
            raise StoryPackError("STORYPACK_NONFINITE_NUMBER")

        data = json.loads(
            source.decode("utf-8-sig"),
            object_pairs_hook=_unique_json_pairs,
            parse_constant=reject_nonfinite,
        )
        return StoryPackV1.model_validate(data)
    except ValidationError as exc:
        # 只返回字段路径和错误种类，不回显剧本文本或文件路径。
        issues = [
            f"{'.'.join(str(part) for part in item['loc'])}: {item['type']}"
            for item in exc.errors(include_input=False)
        ]
        raise StoryPackError("StoryPack validation failed: " + "; ".join(issues[:16])) from exc
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise StoryPackError(f"StoryPack syntax invalid: {type(exc).__name__}") from exc


def storypack_preview(pack: StoryPackV1) -> dict:
    """Deterministic dry-run summary: no DB writes, worker calls or approvals."""
    payload = pack.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    width, height, fps, seconds = OUTPUT_PROFILES[pack.output_profile]
    # Canonical 2.3 Wan profile uses 4n+1 frames; 4 seconds at 24fps means 97, not 96.
    # Reuse the real Production compiler's quantization without granting render authority.
    frames_per_shot = frame_count_for_duration(seconds, fps)
    source_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    # 2.3 的 Creative → ProductionPlan 不接受旧 V3.1 Episode；禁止虚构兼容编译结果。
    compilation = {
        "contract": "picotoo.episode-draft.v1",
        "source_storypack_sha256": source_sha256,
        "episode_contract_valid": False,
        "executable": False,
        "can_queue": False,
        "reason": "CANONICAL_23_PRODUCTION_BRIDGE_NOT_IMPLEMENTED",
        "missing_trust_gates": [
            "CANONICAL_CREATIVE_PACKAGE_APPROVED",
            "OWNER_MASTER_AUTHORITY",
            "WINDOWS_WORKER_ED25519_WITNESS",
            "GPU_HOLD_SEPARATELY_RELEASED",
        ],
    }
    return {
        "validated": True,
        "schema": pack.schema,
        "episode_id": pack.episode_id,
        "storypack_sha256": source_sha256,
        "production_compilation": compilation,
        "shot_count": len(pack.shots),
        "output": {
            "width": width,
            "height": height,
            "fps": fps,
            "seconds_per_shot": seconds,
            "frames_per_shot": frames_per_shot,
            "planned_duration_s": len(pack.shots) * seconds,
            "planned_frames": len(pack.shots) * frames_per_shot,
        },
        "shots": [
            {
                "id": shot.id,
                "action": shot.action,
                "depends_on": shot.depends_on,
                "scene_ref": shot.scene_ref or pack.scene_ref,
                "cast_refs": (
                    [pack.character_ref] if shot.cast_refs is None else shot.cast_refs
                ),
                "handoff": shot.handoff,
            }
            for shot in pack.shots
        ],
        # 资产必须由可信登记表认证；由 LLM 粘贴的 ref 本身不构成许可。
        "unresolved_asset_refs": list(dict.fromkeys([
            pack.character_ref, *pack.supporting_character_refs,
            pack.scene_ref, *pack.additional_scene_refs,
            *([pack.style_ref] if pack.style_ref else []),
        ])),
        "missing_design_locks": [] if pack.style_ref else ["style_ref"],
        "required_gates": [
            "ASSET_RIGHTS_AND_IDENTITY",
            "SCRIPT_AND_STORYBOARD",
            "GPU_AUTHORIZATION",
            "FINAL_ACCEPTANCE",
        ],
        "can_queue": False,
        "reason": "PREVIEW_ONLY_UNVERIFIED_ASSETS_AND_APPROVALS",
    }
