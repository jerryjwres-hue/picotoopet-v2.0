"""StoryPack v1: strict, side-effect-free story import and production preview.

This module NEVER enqueues production tasks, authorizes GPU, or trusts user supplied paths.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
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
    depends_on: list[Identifier] = Field(default_factory=list, max_length=30)
    handoff: Literal["cut", "continuous", "scene_change"] = "cut"


class StoryPackV1(_Strict):
    schema: Literal["picotoo.storypack.v1"]
    episode_id: Identifier
    title: Text
    output_profile: Literal["p0_landscape", "design_portrait"] = "p0_landscape"
    character_ref: AssetRef
    scene_ref: AssetRef
    story: StoryIntent
    shots: list[StoryShot] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def check_dependencies(self) -> StoryPackV1:
        seen: set[str] = set()
        previous: StoryShot | None = None
        for index, shot in enumerate(self.shots):
            folded = shot.id.casefold()
            if folded in seen:
                raise ValueError(f"shots[{index}].id: duplicated shot ID")
            dependencies = [item.casefold() for item in shot.depends_on]
            if len(set(dependencies)) != len(dependencies):
                raise ValueError(f"shots[{index}].depends_on: duplicated dependency")
            if any(item not in seen for item in dependencies):
                raise ValueError(f"shots[{index}].depends_on: references must precede this shot")
            if shot.handoff == "continuous":
                if previous is None or previous.id.casefold() not in dependencies:
                    raise ValueError(f"shots[{index}]: continuous handoff requires previous shot")
                if previous.state_out.strip() != shot.state_in.strip():
                    raise ValueError(f"shots[{index}]: state_in must match previous state_out")
            seen.add(folded)
            previous = shot
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
    except (UnicodeError, yaml.YAMLError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise StoryPackError(f"StoryPack validation failed: {exc}") from exc


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
            {"id": shot.id, "action": shot.action, "depends_on": shot.depends_on}
            for shot in pack.shots
        ],
        # 资产尚未向可信 registry 查询，预览不能冒充已完成素材核验。
        "unresolved_asset_refs": [pack.character_ref, pack.scene_ref],
        "required_gates": [
            "ASSET_RIGHTS_AND_IDENTITY",
            "SCRIPT_AND_STORYBOARD",
            "GPU_AUTHORIZATION",
            "FINAL_ACCEPTANCE",
        ],
        "can_queue": False,
        "reason": "PREVIEW_ONLY_UNVERIFIED_ASSETS_AND_APPROVALS",
    }
