"""Translate explicit director decisions into episode video prompts without a model."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import AfterValidator, Field, StringConstraints, ValidationError, field_validator

from picotoopet_core.domain.episode import Episode, ShotId, load_episode
from picotoopet_core.domain.executor import ExecutorModel, Identifier

CAMERA_TERMS = {
    "固定": "locked-off camera",
    "固定机位": "locked-off camera",
    "缓慢推近": "slow dolly in",
    "推近": "dolly in",
    "拉远": "dolly out",
    "跟拍": "follow the subject",
    "左摇": "pan left",
    "右摇": "pan right",
    "向左平移": "track left",
    "向右平移": "track right",
    "移焦": "rack focus",
    "变焦拉近": "zoom in",
    "变焦拉远": "zoom out",
}


class DirectorError(ValueError):
    """A human-readable issue with directions or the output destination."""


def _english(value: str) -> str:
    if not re.search(r"[A-Za-z]", value) or re.search(r"[\u3040-\u30ff\u3400-\u9fff]", value):
        raise ValueError("请填写明确的英文短句。")
    return " ".join(value.split())


English = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=1000),
    AfterValidator(_english),
]


class ActionDirection(ExecutorModel):
    trigger: English
    behavior: English
    landing: English


class CameraDirection(ExecutorModel):
    opening: English
    trigger: English
    landing: English
    move: English | None = None

    @field_validator("move", mode="before")
    @classmethod
    def translate_camera_term(cls, value):
        if isinstance(value, str):
            return CAMERA_TERMS.get(value.strip(), value)
        return value


class ShotDirection(ExecutorModel):
    subjects: list[Identifier] = Field(max_length=16)
    scene: English
    action: ActionDirection
    camera: CameraDirection
    intent: English | None = None
    sound: English | None = None

    @field_validator("subjects")
    @classmethod
    def unique_subjects(cls, names: list[str]) -> list[str]:
        if len(set(names)) != len(names):
            raise ValueError("同一镜头的主体不可重复。")
        return names


class DirectorDirections(ExecutorModel):
    identities: dict[Identifier, English] = Field(default_factory=dict, max_length=100)
    shots: dict[ShotId, ShotDirection] = Field(min_length=1, max_length=500)


class _DirectionsLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise DirectorError(f"第 {key_node.start_mark.line + 1} 行的字段名须为文本。")
            if key in result:
                raise DirectorError(f"第 {key_node.start_mark.line + 1} 行有重复字段 {key!r}。")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def load_directions(raw: bytes) -> DirectorDirections:
    try:
        data = yaml.load(raw.decode("utf-8-sig"), Loader=_DirectionsLoader)
        return DirectorDirections.model_validate(data)
    except ValidationError as exc:
        messages = []
        for error in exc.errors(include_input=False, include_url=False):
            field = ".".join(map(str, error["loc"])) or "方向表"
            reason = {
                "missing": "缺少必填字段。",
                "extra_forbidden": "不支持此字段。",
            }.get(error["type"], str(error.get("ctx", {}).get("error", "字段值无效。")))
            messages.append(f"{field}：{reason}")
        raise DirectorError("；".join(messages)) from exc
    except (UnicodeError, yaml.YAMLError) as exc:
        raise DirectorError("方向表须为有效的 UTF-8 YAML 或 JSON。") from exc


def _sentence(text: str, *, label: str = "") -> str:
    return label + text + ("" if text.endswith((".", "!", "?")) else ".")


def _prompt(direction: ShotDirection, identities: dict[str, str]) -> str:
    action = direction.action
    camera = direction.camera
    segments = [_sentence(direction.scene)]
    segments.extend(_sentence(identities[name]) for name in direction.subjects)
    if direction.intent:
        segments.append(_sentence(direction.intent, label="Audience focus: "))
    segments.extend(
        (
            _sentence(action.trigger, label="Action cue: "),
            _sentence(action.behavior, label="Action: "),
            _sentence(action.landing, label="Action landing: "),
            _sentence(camera.opening, label="Opening frame: "),
            _sentence(camera.trigger, label="Camera cue: "),
        )
    )
    if camera.move:
        segments.append(_sentence(camera.move, label="Camera move: "))
    segments.append(_sentence(camera.landing, label="Final frame: "))
    if direction.sound:
        segments.append(_sentence(direction.sound, label="Sound: "))
    return " ".join(segments)


def direct_episode(episode: Episode, directions: DirectorDirections) -> str:
    """Compile listed shots only and verify the complete rendered episode."""
    shots = {shot.shot_id: shot for shot in episode.shots}
    unknown_shots = directions.shots.keys() - shots.keys()
    if unknown_shots:
        raise DirectorError(f"方向表含未知镜号：{'、'.join(sorted(unknown_shots))}。")
    payload = episode.model_dump(mode="json")
    for shot in payload["shots"]:
        shot_id = shot["shot_id"]
        direction = directions.shots.get(shot_id)
        if direction is None:
            continue
        unknown_subjects = set(direction.subjects) - directions.identities.keys()
        if unknown_subjects:
            names = "、".join(sorted(unknown_subjects))
            raise DirectorError(f"{shot_id} 含未定义主体：{names}。")
        shot["video"]["prompt"] = _prompt(direction, directions.identities)
    rendered = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=1000)
    load_episode(rendered.encode("utf-8"), as_yaml=True)
    return rendered


def write_directed_episode(output: Path, text: str, inputs: tuple[Path, ...]) -> None:
    if output.resolve() in {path.resolve() for path in inputs}:
        raise DirectorError("请另选输出文件，避免覆盖剧集或方向表。")
    data = text.encode("utf-8")
    try:
        with output.open("xb") as stream:
            stream.write(data)
    except FileExistsError as exc:
        if output.is_file() and output.read_bytes() == data:
            return
        raise DirectorError("输出文件已经存在且内容不同，请另选路径。") from exc
