"""Strict contracts for the closed 2.3.20.1 production plane."""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from picotoopet_core.creative.models import VideoOutputProfile
from picotoopet_core.production.profile import VIDEO_OUTPUT_PROFILES


class ProductionProfile(StrEnum):
    # ── Closed profile identity ──────────────────────────────────────────────
    COMFYUI_V1 = "production.comfyui.v1"


class ProductionJobStatus(StrEnum):
    # ── Frozen 20.1 durable job lifecycle ───────────────────────────────────
    READY = "Ready"
    CLAIMED = "Claimed"
    PREFLIGHT = "Preflight"
    RENDERING = "Rendering"
    COLLECTING = "Collecting"
    QUALITY_CHECK = "QualityCheck"
    PRODUCTION_READY = "production_ready"
    NEEDS_HUMAN = "NeedsHuman"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

    # ── Internal source-compat alias; serialized/persisted value remains Ready ──
    PLANNED = "Ready"


class ProductionTaskStatus(StrEnum):
    # ── Frozen 20.1 per-shot lifecycle ──────────────────────────────────────
    PENDING = "Pending"
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    NEEDS_HUMAN = "NeedsHuman"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

    # ── Internal source-compat alias; serialized/persisted value remains Pending ──
    READY = "Pending"


class ProductionExecutionDisposition(StrEnum):
    # ── Compiler decision; renderer never overrides it ──────────────────────
    EXECUTABLE = "Executable"
    NEEDS_HUMAN = "NeedsHuman"


class ProductionExecutionBackend(StrEnum):
    COMFY = "comfy"
    LOCAL_MEDIA = "local_media"


class ProductionExecutionProfile(StrEnum):
    COMFY_T2V = "comfy.wan22.ti2v5b.t2v.v1"
    COMFY_I2V = "comfy.wan22.ti2v5b.i2v.v1"
    TEXT_CARD_V1 = "production.local.text-card.v1"


class ProductionJobCreateRequest(BaseModel):
    """Producer may select only an existing Creative Package and fixed profile."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    creative_package_id: str
    production_profile: Literal["production.comfyui.v1"] = "production.comfyui.v1"
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("creative_package_id")
    @classmethod
    def _valid_package_id(cls, value: str) -> str:
        return str(UUID(value))


class ProductionClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    executor_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")


class ProductionHeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    executor_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    lease_token: str = Field(min_length=16, max_length=200)


class ProductionTaskAttemptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    executor_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    lease_token: str = Field(min_length=16, max_length=200)
    comfy_prompt_id: str | None = Field(default=None, max_length=200)


class ProductionTaskFailureRequest(BaseModel):
    """Bounded terminal failure evidence returned by the active Windows executor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    executor_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    lease_token: str = Field(min_length=16, max_length=200)
    comfy_prompt_id: str | None = Field(default=None, max_length=200)
    failure_code: str = Field(min_length=1, max_length=120, pattern=r"^[A-Z0-9_.-]+$")
    error_message: str | None = Field(default=None, max_length=1000)


class ProductionTaskCommitRequest(BaseModel):
    """Bounded evidence returned by the Windows executor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    executor_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    lease_token: str = Field(min_length=16, max_length=200)
    comfy_prompt_id: str | None = Field(default=None, min_length=1, max_length=200)
    output_relpath: str = Field(min_length=1, max_length=500)
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_bytes: int = Field(gt=0, le=50_000_000_000)
    mime_type: str = Field(min_length=1, max_length=100)
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    frame_count: int = Field(ge=1, le=10_000)
    fps: int = Field(ge=1, le=240)

    @field_validator("output_relpath")
    @classmethod
    def _safe_relative_output(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        parts = [part for part in normalized.split("/") if part]
        if normalized.startswith("/") or not parts or ".." in parts or ":" in parts[0]:
            raise ValueError("output path must be managed-relative")
        return "/".join(parts)


class ProductionLocalMediaPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    text_content: str = Field(min_length=1, max_length=800)
    text_profile_id: Literal["production.local.text-card.v1"]

    @model_validator(mode="after")
    def _digest_matches_text(self) -> ProductionLocalMediaPayload:
        actual = hashlib.sha256(self.text_content.encode("utf-8")).hexdigest()
        if actual != self.text_digest:
            raise ValueError("local media text digest does not match content")
        return self


class ProductionTaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    production_task_id: str
    shot_id: str = Field(min_length=1, max_length=120)
    order: int = Field(ge=1, le=200)
    render_intent: str = Field(min_length=1, max_length=80)
    execution_disposition: ProductionExecutionDisposition
    execution_backend: ProductionExecutionBackend | None = None
    execution_profile_id: ProductionExecutionProfile | None = None
    workflow_id: str | None = Field(default=None, max_length=120)
    local_media: ProductionLocalMediaPayload | None = None
    positive_prompt: str = Field(min_length=1, max_length=5000)
    negative_prompt_policy_id: str = Field(min_length=1, max_length=120)
    seed: int = Field(ge=0, lt=2**63)
    width: int = Field(ge=256, le=1280)
    height: int = Field(ge=256, le=1280)
    fps: int = Field(ge=1, le=30)
    frame_count: int = Field(ge=1, le=121)
    target_duration_ms: int = Field(gt=0, le=120_000)
    trusted_input_asset_ref: str | None = Field(default=None, max_length=300)

    @model_validator(mode="before")
    @classmethod
    def _legacy_execution_contract(cls, value: object) -> object:
        if not isinstance(value, dict) or "execution_backend" in value:
            return value
        workflow_id = value.get("workflow_id")
        if workflow_id not in {
            ProductionExecutionProfile.COMFY_T2V.value,
            ProductionExecutionProfile.COMFY_I2V.value,
        }:
            return value
        updated = dict(value)
        updated["execution_backend"] = ProductionExecutionBackend.COMFY.value
        updated["execution_profile_id"] = workflow_id
        return updated

    @model_validator(mode="before")
    @classmethod
    def _legacy_target_duration(cls, value: object) -> object:
        if not isinstance(value, dict) or "target_duration_ms" in value:
            return value
        fps = value.get("fps")
        frame_count = value.get("frame_count")
        if isinstance(fps, int) and fps > 0 and isinstance(frame_count, int):
            updated = dict(value)
            updated["target_duration_ms"] = int(
                (Decimal(frame_count * 1000) / fps).quantize(
                    Decimal("1"),
                    rounding=ROUND_HALF_UP,
                )
            )
            return updated
        return value

    @field_validator("production_task_id")
    @classmethod
    def _valid_task_id(cls, value: str) -> str:
        return str(UUID(value))

    @model_validator(mode="after")
    def _workflow_matches_disposition(self) -> ProductionTaskPlan:
        if self.frame_count % 4 != 1:
            raise ValueError("production frame count must use the Wan 4n+1 family")
        if self.execution_disposition is ProductionExecutionDisposition.NEEDS_HUMAN:
            if any(
                item is not None
                for item in (
                    self.execution_backend,
                    self.execution_profile_id,
                    self.workflow_id,
                    self.local_media,
                )
            ):
                raise ValueError("needs-human task cannot carry executable authority")
            return self
        if self.execution_backend is None or self.execution_profile_id is None:
            raise ValueError("executable production task requires backend and profile")
        if self.execution_backend is ProductionExecutionBackend.COMFY:
            if self.workflow_id is None or self.local_media is not None:
                raise ValueError("comfy task requires only a workflow id")
            if self.execution_profile_id.value != self.workflow_id:
                raise ValueError("comfy execution profile must match workflow")
            return self
        if (
            self.execution_backend is not ProductionExecutionBackend.LOCAL_MEDIA
            or self.execution_profile_id is not ProductionExecutionProfile.TEXT_CARD_V1
            or self.render_intent != "TEXT_CARD"
            or self.workflow_id is not None
            or self.local_media is None
            or self.local_media.text_profile_id != self.execution_profile_id.value
        ):
            raise ValueError("local-media task contract is invalid")
        return self


class ProductionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    production_profile: Literal["production.comfyui.v1"]
    production_job_id: str
    creative_package_id: str
    creative_package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_key: str = Field(min_length=1, max_length=200)
    output_profile_id: VideoOutputProfile = VideoOutputProfile.LANDSCAPE_V1
    target_runtime_ms: int = Field(gt=0, le=600_000)
    tasks: list[ProductionTaskPlan] = Field(min_length=1, max_length=120)

    @model_validator(mode="before")
    @classmethod
    def _legacy_target_runtime(cls, value: object) -> object:
        if not isinstance(value, dict) or "target_runtime_ms" in value:
            return value
        durations = []
        for task in value.get("tasks", []):
            if isinstance(task, ProductionTaskPlan):
                durations.append(task.target_duration_ms)
            elif isinstance(task, dict):
                duration = task.get("target_duration_ms")
                fps = task.get("fps")
                frame_count = task.get("frame_count")
                if isinstance(duration, int):
                    durations.append(duration)
                elif isinstance(fps, int) and fps > 0 and isinstance(frame_count, int):
                    durations.append(
                        int(
                            (Decimal(frame_count * 1000) / fps).quantize(
                                Decimal("1"),
                                rounding=ROUND_HALF_UP,
                            )
                        )
                    )
        if durations:
            updated = dict(value)
            updated["target_runtime_ms"] = sum(durations)
            return updated
        return value

    @model_validator(mode="after")
    def _task_order_is_deterministic(self) -> ProductionPlan:
        orders = [item.order for item in self.tasks]
        shots = [item.shot_id for item in self.tasks]
        if orders != list(range(1, len(self.tasks) + 1)) or len(shots) != len(set(shots)):
            raise ValueError("production task order/shot identity is invalid")
        profile = VIDEO_OUTPUT_PROFILES[self.output_profile_id]
        if any(
            (item.width, item.height, item.fps)
            != (profile.width, profile.height, profile.fps)
            for item in self.tasks
        ):
            raise ValueError("production task output profile is inconsistent")
        if self.target_runtime_ms != sum(item.target_duration_ms for item in self.tasks):
            raise ValueError("production plan runtime is inconsistent")
        return self


class ProductionTaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    production_task_id: str
    production_job_id: str
    shot_id: str
    order: int
    render_intent: str
    execution_disposition: ProductionExecutionDisposition
    workflow_id: str | None = None
    task_plan: ProductionTaskPlan
    status: ProductionTaskStatus
    attempt_count: int
    comfy_prompt_id: str | None = None
    output_relpath: str | None = None
    output_sha256: str | None = None
    output_bytes: int | None = None
    output_mime_type: str | None = None
    output_width: int | None = None
    output_height: int | None = None
    output_frame_count: int | None = None
    output_fps: int | None = None
    failure_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class ProductionJobRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    production_job_id: str
    creative_package_id: str
    creative_package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_key: str
    production_profile: ProductionProfile
    plan_digest: str | None = None
    status: ProductionJobStatus
    lease_executor_id: str | None = None
    lease_expires_at: datetime | None = None
    failure_code: str | None = None
    error_message: str | None = None
    idempotency_key: str
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None = None


class ProductionClaimRecord(BaseModel):
    """Active lease plus the durable task snapshot required for restart-safe resume."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    production_job_id: str
    executor_id: str
    lease_token: str
    lease_expires_at: datetime
    plan: ProductionPlan
    tasks: list[ProductionTaskRecord]


class ProductionEligibleCreativeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    creative_package_id: str
    creative_job_id: str
    project_key: str
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime


class ProductionPackageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    production_package_id: str
    production_job_id: str
    creative_package_id: str
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_relpath: str
    manifest: dict[str, object]
    quality_outcome: Literal["PASS"]
    created_at: datetime
