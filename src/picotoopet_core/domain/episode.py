"""episode.yaml 的数据模型与中文错误提示。"""

import json
from typing import Annotated, Any, Literal

import yaml
from pydantic import Field, StrictFloat, StrictInt, ValidationError

from picotoopet_core.domain.executor import ExecutorModel, Identifier, ReviewedArtifact
from picotoopet_core.domain.models import TaskRecord

Text = Annotated[str, Field(min_length=1)]
Seconds = Annotated[StrictFloat, Field(gt=0)]
JsonObject = dict[str, Any]
ShotId = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")]


class Camera(ExecutorModel):
    move: Text
    lens: Text | Annotated[StrictFloat, Field(gt=0)]
    speed: Text | Annotated[StrictFloat, Field(gt=0)]


class Frame(ExecutorModel):
    refs: list[Text]
    prompt: Text


class Video(ExecutorModel):
    prompt: Text
    negative: str
    seeds: list[Annotated[StrictInt, Field(ge=0, le=2**63 - 1)]] = Field(
        min_length=1,
        max_length=48,
    )


class Audio(ExecutorModel):
    vocal_from: Literal["ltx", "none"]
    foley: list[Text | JsonObject]
    music_cue: Text | JsonObject | None = None


class Transition(ExecutorModel):
    type: Literal["cut", "j_cut", "l_cut", "whip", "match", "speed_ramp"]
    offset_s: StrictFloat


class Shot(ExecutorModel):
    shot_id: ShotId
    seconds: Seconds
    beat: Text
    emotion: Text
    camera: Camera
    first_frame: Frame
    last_frame: Frame | None = None
    video: Video
    audio: Audio
    transition_out: Transition
    caption: str | None = None


class Edit(ExecutorModel):
    fps: Annotated[StrictFloat, Field(gt=0, le=240)]
    size: tuple[
        Annotated[StrictInt, Field(ge=2, le=8192, multiple_of=2)],
        Annotated[StrictInt, Field(ge=2, le=8192, multiple_of=2)],
    ]
    loudness_lufs: Annotated[StrictFloat, Field(ge=-70, le=-5)]


class Episode(ExecutorModel):
    episode_id: Identifier
    title: Text
    target_seconds: Seconds
    characters: list[Text | JsonObject]
    shots: list[Shot] = Field(min_length=1, max_length=500)
    edit: Edit


class EpisodeSummary(ExecutorModel):
    episode_id: Identifier
    title: str


class EpisodeCreated(ExecutorModel):
    episode: Episode
    tasks: list[TaskRecord]


class ReviewCandidate(ReviewedArtifact):
    task_id: str
    task_type: str
    sheet_thumbnail_id: str | None = None
    qc: JsonObject


class ShotReview(ExecutorModel):
    shot_id: Identifier
    status: str
    redo_count: int
    candidates: list[ReviewCandidate]


class EpisodeReview(ExecutorModel):
    shots: list[ShotReview]
    can_assemble: bool


class EpisodeValidationError(ValueError):
    """含具体字段路径的输入错误。"""


def load_episode(content: bytes, *, as_yaml: bool) -> Episode:
    try:
        raw = yaml.safe_load(content.decode("utf-8-sig")) if as_yaml else json.loads(content)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f"第 {mark.line + 1} 行、第 {mark.column + 1} 列" if mark else "文件"
        raise EpisodeValidationError(f"{location}：YAML 格式无效。") from exc
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
        raise EpisodeValidationError("文件：请输入有效的 UTF-8 JSON 或 YAML。") from exc
    try:
        episode = Episode.model_validate(raw)
    except ValidationError as exc:
        messages = []
        for error in exc.errors():
            path = ""
            for part in error["loc"]:
                path += f"[{part}]" if isinstance(part, int) else f"{'.' if path else ''}{part}"
            reason = {
                "missing": "缺少必填字段",
                "extra_forbidden": "不支持此字段",
            }.get(error["type"], "值不符合字段要求")
            messages.append(f"{path or '根字段'}：{reason}")
        raise EpisodeValidationError("；".join(messages)) from exc

    seen = set()
    for index, shot in enumerate(episode.shots):
        folded = shot.shot_id.casefold()
        if folded in seen:
            raise EpisodeValidationError(f"shots[{index}].shot_id：分镜编号重复。")
        seen.add(folded)
    # 自由对象也必须能安全存为 JSON，避免 YAML 专用日期、集合和递归别名。
    for field, values in (
        ("characters", episode.characters),
        *((f"shots[{i}].audio.foley", shot.audio.foley) for i, shot in enumerate(episode.shots)),
        *(
            (f"shots[{i}].audio.music_cue", [shot.audio.music_cue])
            for i, shot in enumerate(episode.shots)
        ),
    ):
        for index, value in enumerate(values):
            try:
                json.dumps(value, allow_nan=False)
            except (TypeError, ValueError, RecursionError) as exc:
                raise EpisodeValidationError(f"{field}[{index}]：须为 JSON 兼容数据。") from exc
    return episode
