"""把外部已完成的历史候选登记为可审片产物。"""

import json
from pathlib import PureWindowsPath
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, model_validator

from picotoopet_core.domain.episode import Episode, JsonObject
from picotoopet_core.domain.executor import THUMBNAIL_LIMIT, ExecutorModel, SourcedArtifact

IMPORT_LIMIT = 52 * 1024 * 1024
_EXTENSIONS = {
    "image": {".bmp", ".jpg", ".jpeg", ".png", ".webp"},
    "video": {".m4v", ".mkv", ".mov", ".mp4", ".webm"},
    "audio": {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"},
}


class HistoricalCandidate(SourcedArtifact):
    kind: Literal["image", "video", "audio"]
    bytes: StrictInt = Field(gt=0)
    take: StrictInt = Field(ge=1)
    qc: JsonObject = Field(default_factory=dict)
    decision: Literal["pick", "reject"] | None = None
    note: str = Field(default="", max_length=2000)
    jpeg_base64: str | None = Field(default=None, max_length=4 * (THUMBNAIL_LIMIT // 3))

    @model_validator(mode="after")
    def check_media(self) -> "HistoricalCandidate":
        path = PureWindowsPath(self.path)
        if (
            not path.is_absolute()
            or len(path.drive) != 2
            or not path.drive[0].isascii()
            or not path.drive[0].isalpha()
            or any(
                part == ".."
                or any(character in '<>:"|?*' for character in part)
                or part.rstrip(" .") != part
                for part in path.parts[1:]
            )
            or any(ord(character) < 32 for character in self.path)
            or path.suffix.lower() not in _EXTENSIONS[self.kind]
        ):
            raise ValueError("path 须为对应媒体类型的 Windows 本地绝对路径。")
        json.dumps(self.qc, allow_nan=False)
        return self

    def artifact(self) -> SourcedArtifact:
        return SourcedArtifact.model_validate(
            self.model_dump(include=set(SourcedArtifact.model_fields))
        )


class EpisodeHistoryImport(ExecutorModel):
    episode: Episode
    candidates: list[HistoricalCandidate] = Field(min_length=1, max_length=128)
    episode_metadata_complete: bool = True
    fill_unreviewed: StrictBool = Field(
        default=False, description="只补录离线决定或备注，保留已有和曾有的 Mac 审片记录。"
    )

    @model_validator(mode="after")
    def check_candidates(self) -> "EpisodeHistoryImport":
        shots = {item.shot_id for item in self.episode.shots}
        if len({item.casefold() for item in shots}) != len(self.episode.shots):
            raise ValueError("剧集分镜编号重复。")
        json.dumps(self.episode.model_dump(), allow_nan=False)
        picks = set()
        for item in self.candidates:
            if item.shot_id not in shots:
                raise ValueError("候选的 shot_id 须存在于剧集。")
            if item.decision == "pick":
                key = (item.shot_id, item.kind)
                if key in picks:
                    raise ValueError("同一分镜的同类候选只能预选一条。")
                picks.add(key)
        return self


class EpisodeHistoryImported(ExecutorModel):
    episode_id: str
    inserted_count: int
    existing_count: int
    updated_count: int | None = Field(default=None, ge=1)
    conflict_count: int | None = Field(default=None, ge=1)
