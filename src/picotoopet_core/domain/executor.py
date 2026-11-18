"""本地执行桥与生产审片的数据契约。"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TASK_RUNNERS = {
    "gen.keyframe": "run_qwen_edit.py",
    "gen.video": "run_ltx_flf.py",
    "gen.foley": "run_foley.py",
    "qc.check": "qc.check",
    "edit.assemble": "edit.assemble",
}
GPU_TAG = "gpu-5070ti"
Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]


class ExecutorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ExecutorLease(ExecutorModel):
    worker_id: Identifier
    resource_tags: list[Identifier] = Field(min_length=1, max_length=32)
    lease_seconds: int = Field(ge=30, le=3600)
    resume_task_id: Identifier | None = None


class ExecutorPayload(ExecutorModel):
    episode_id: Identifier
    shot_id: Identifier
    runner: Literal[
        "run_qwen_edit.py", "run_ltx_flf.py", "run_foley.py", "qc.check", "edit.assemble"
    ]
    jobs: dict[str, Any]
    args: list[str] = Field(default_factory=list)


class ExecutorReport(ExecutorModel):
    worker_id: Identifier
    attempt_count: int | None = Field(default=None, ge=1)


class ExecutorHeartbeat(ExecutorReport):
    progress: float = Field(ge=0, le=1)
    message: str = Field(max_length=500)


class ExecutorArtifact(ExecutorModel):
    kind: Literal["image", "video", "audio", "sheet"]
    path: str = Field(min_length=1, max_length=4096)
    sha256: Sha256
    bytes: int = Field(ge=0)
    shot_id: Identifier
    take: int = Field(ge=1)


class ExecutorMetrics(ExecutorModel):
    seconds: float = Field(ge=0)


class ExecutorComplete(ExecutorReport):
    artifacts: list[ExecutorArtifact] = Field(max_length=256)
    qc: dict[str, Any]
    metrics: ExecutorMetrics


class ExecutorFail(ExecutorReport):
    error: str = Field(min_length=1, max_length=2000)
    retryable: bool


class ArtifactDecision(ExecutorModel):
    decision: Literal["pick", "reject", "redo"]
    note: str = Field(default="", max_length=2000)


class ReviewedArtifact(ExecutorArtifact):
    artifact_id: str
    decision: Literal["pick", "reject", "redo"] | None = None
    note: str = ""
    thumbnail_id: str | None = None


class ArtifactList(ExecutorModel):
    result_id: str | None = None
    upstream_task_id: str | None = None
    artifacts: list[ReviewedArtifact] = Field(default_factory=list)
    qc: dict[str, Any] = Field(default_factory=dict)
    sheet_thumbnail_id: str | None = None


class ThumbnailRecord(ExecutorModel):
    thumbnail_id: str


class ThumbnailContent(ThumbnailRecord):
    jpeg_base64: str
