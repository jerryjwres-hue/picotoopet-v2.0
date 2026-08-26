"""Verified user-facing access to deterministic Web GPT handoff packages."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from picotoopet_core.config.paths import RuntimePaths

from .handoff import PROMPT_VERSION, WebGptHandoffBuilder
from .models import GoalOrigin, GoalRecord

_HANDOFF_STEP = "web-gpt-handoff"
_HANDOFF_RESULT_TYPE = "autonomous.goal_handoff.v1"
_VIDEO_GOAL_TYPES = frozenset({"video.creative", "product.research_to_video"})
_MAX_HANDOFF_RESULT_BYTES = 64 * 1024


class HandoffAccessError(RuntimeError):
    """The requested Goal handoff is absent, unsafe or failed integrity checks."""


class GoalHandoffMetadata(BaseModel):
    """Safe handoff projection for Windows; local filesystem paths are never returned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = "1.0"
    goal_id: str = Field(min_length=1, max_length=128)
    handoff_ready: bool
    package_name: str = Field(min_length=1, max_length=200)
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_size_bytes: int = Field(gt=0, le=128 * 1024 * 1024)
    prompt_version: str = Field(min_length=1, max_length=100)
    manual_web_gpt_upload_required: bool


class _Goals(Protocol):
    def get(self, goal_id: str) -> GoalRecord: ...


class _Workflows(Protocol):
    def get_workflow(self, workflow_id: str): ...  # type: ignore[no-untyped-def]


class _ResultRecords(Protocol):
    def get_for_task(self, task_id: str): ...  # type: ignore[no-untyped-def]


class _ResultStore(Protocol):
    def read_json(self, object_hash: str, *, max_bytes: int) -> dict[str, Any]: ...


class GoalHandoffAccess:
    """Resolve handoffs through canonical Goal → Workflow → Result facts only."""

    def __init__(
        self,
        *,
        paths: RuntimePaths,
        goals: _Goals,
        workflows: _Workflows,
        result_records: _ResultRecords,
        result_store: _ResultStore,
    ) -> None:
        self.paths = paths
        self.goals = goals
        self.workflows = workflows
        self.result_records = result_records
        self.result_store = result_store

    def metadata(self, goal_id: str) -> GoalHandoffMetadata:
        """Return only verified handoff metadata; never infer readiness from a file alone."""

        try:
            goal = self.goals.get(goal_id)
        except KeyError as error:
            raise HandoffAccessError("goal not found") from error
        if goal.origin is not GoalOrigin.HUMAN or goal.intent_type not in _VIDEO_GOAL_TYPES:
            raise HandoffAccessError("goal does not produce a Web GPT handoff")
        if goal.workflow_id is None:
            raise HandoffAccessError("handoff is not ready")

        workflow = self.workflows.get_workflow(goal.workflow_id)
        step = next(
            (item for item in workflow.steps if item.step_key == _HANDOFF_STEP),
            None,
        )
        if step is None or not step.task_id:
            raise HandoffAccessError("handoff is not ready")
        try:
            record = self.result_records.get_for_task(step.task_id)
        except KeyError as error:
            raise HandoffAccessError("handoff is not ready") from error
        if record.result_type != _HANDOFF_RESULT_TYPE:
            raise HandoffAccessError("handoff result type mismatch")
        try:
            document = self.result_store.read_json(
                record.object_hash,
                max_bytes=_MAX_HANDOFF_RESULT_BYTES,
            )
            metadata = GoalHandoffMetadata.model_validate(document)
        except (KeyError, ValueError, ValidationError) as error:
            raise HandoffAccessError("handoff metadata is invalid") from error
        if metadata.goal_id != goal.goal_id or not metadata.handoff_ready:
            raise HandoffAccessError("handoff is not ready")
        if metadata.prompt_version != PROMPT_VERSION:
            raise HandoffAccessError("handoff prompt version mismatch")
        self._validate_package_name(metadata.package_name)
        return metadata

    def verified_package(self, goal_id: str) -> Path:
        """Resolve one managed ZIP only after size and SHA-256 verification."""

        metadata = self.metadata(goal_id)
        root = self.paths.autonomous_handoffs_dir.resolve()
        candidate = root / metadata.package_name
        if candidate.is_symlink():
            raise HandoffAccessError("handoff package integrity check failed")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as error:
            raise HandoffAccessError("handoff package is missing") from error
        if resolved.parent != root or not resolved.is_file():
            raise HandoffAccessError("handoff package escaped managed root")
        try:
            size = resolved.stat().st_size
            digest = self._sha256(resolved)
        except OSError as error:
            raise HandoffAccessError("handoff package integrity check failed") from error
        if size != metadata.package_size_bytes or digest != metadata.package_sha256:
            raise HandoffAccessError("handoff package integrity check failed")
        return resolved

    def fixed_prompt(self, goal_id: str) -> str:
        """Return the exact versioned prompt only for a Goal with a valid handoff result."""

        self.metadata(goal_id)
        return WebGptHandoffBuilder._load_fixed_prompt()

    @staticmethod
    def _validate_package_name(package_name: str) -> None:
        candidate = Path(package_name)
        if (
            candidate.name != package_name
            or candidate.is_absolute()
            or package_name in {".", ".."}
            or not package_name.endswith(".zip")
        ):
            raise HandoffAccessError("invalid handoff package name")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
