"""StoryPack v1: strict, side-effect-free story import and production preview.

This module NEVER enqueues production tasks, authorizes GPU, or trusts user supplied paths.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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


def parse_storypack(source: bytes, *, as_yaml: bool) -> StoryPackV1:
    """Accept only UTF-8 structured data. Never execute model, tool or code strings."""
    try:
        data = (
            yaml.safe_load(source.decode("utf-8-sig"))
            if as_yaml
            else json.loads(source.decode("utf-8-sig"))
        )
        return StoryPackV1.model_validate(data)
    except ValidationError as exc:
        # 返回字段路径与错误类型，不回显用户粘贴的剧本或私有素材内容。
        issues = [
            f"{'.'.join(str(part) for part in item['loc'])}: {item['type']}"
            for item in exc.errors(include_input=False)
        ]
        raise StoryPackError("StoryPack validation failed: " + "; ".join(issues[:16])) from exc
    except (UnicodeError, yaml.YAMLError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise StoryPackError(f"StoryPack syntax invalid: {type(exc).__name__}") from exc


def storypack_preview(pack: StoryPackV1) -> dict:
    """Deterministic dry-run summary: no DB writes, worker calls or approvals."""
    payload = pack.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    width, height, fps, seconds = OUTPUT_PROFILES[pack.output_profile]
    return {
        "validated": True,
        "schema": pack.schema,
        "episode_id": pack.episode_id,
        "storypack_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "shot_count": len(pack.shots),
        "output": {
            "width": width,
            "height": height,
            "fps": fps,
            "seconds_per_shot": seconds,
            "planned_duration_s": len(pack.shots) * seconds,
            "planned_frames": len(pack.shots) * seconds * fps,
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
