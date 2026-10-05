"""Verified user-facing access to deterministic Web GPT handoff packages."""

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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


class GoalHandoffPackageManifest(BaseModel):
    """Exact bounded manifest read from a verified Core-built handoff ZIP."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    handoff_type: Literal["web-gpt-production"]
    prompt_version: str = Field(min_length=1, max_length=100)
    goal_id: str = Field(min_length=1, max_length=128)
    created_at: datetime
    evidence_ids: list[str] = Field(min_length=1, max_length=128)
    source_ids: list[str] = Field(min_length=1, max_length=128)
    file_sha256: dict[str, str] = Field(min_length=1, max_length=32)

    @field_validator("evidence_ids", "source_ids")
    @classmethod
    def _unique_bounded_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(not item or len(item) > 128 for item in value):
            raise ValueError("manifest identifiers must be unique bounded strings")
        return value

    @field_validator("file_sha256")
    @classmethod
    def _valid_file_digests(cls, value: dict[str, str]) -> dict[str, str]:
        for name, digest in value.items():
            if (
                not name
                or len(name) > 200
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError("manifest file digest is invalid")
        return value


class GoalHandoffContext(BaseModel):
    """Verified immutable identity and provenance available to return intake."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_id: str
    workflow_id: str
    handoff_task_id: str
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt_version: str
    handoff_created_at: datetime
    evidence_ids: list[str]
    source_ids: list[str]
    source_finding_refs: dict[str, str]


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
        """Return the exact versioned master prompt for a Goal with a valid handoff result."""

        self.metadata(goal_id)
        return WebGptHandoffBuilder._load_fixed_prompt()

    def return_prompt(self, goal_id: str) -> str:
        """Return the master prompt plus the exact machine-return binding and schema."""

        context = self.context(goal_id)
        # Lazy import avoids coupling handoff package construction to the return module.          #
        from .video_return import GoalVideoReturnV1

        binding = {
            "goal_id": context.goal_id,
            "handoff_sha256": context.package_sha256,
            "prompt_version": context.prompt_version,
            "source_finding_refs": context.source_finding_refs,
        }
        compact_binding = json.dumps(
            binding, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        compact_schema = json.dumps(
            GoalVideoReturnV1.model_json_schema(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return (
            self.fixed_prompt(goal_id)
            + "\n\n【PicotooPet 严格回导合同】\n"
            + "这是当前交接包的 Core 绑定信息；不要修改这些绑定值：\n"
            + compact_binding
            + "\n\n最终可读回答之后，必须再输出且只输出一个标记为 PICOTOO_RETURN_JSON 的 JSON 对象。"
            + "该对象必须严格符合下面的 JSON Schema，不得增加 provider/model/renderer/workflow/"
            + "endpoint/path/command 等字段。所有 source_finding_refs 只能使用上方映射中的值；"
            + "所有 evidence 引用只能使用映射中的 key。\n"
            + compact_schema
            + "\n"
        )

    def context(self, goal_id: str) -> GoalHandoffContext:
        """Read the exact completed handoff identity and its evidence allowlist."""

        metadata = self.metadata(goal_id)
        goal = self.goals.get(goal_id)
        if goal.workflow_id is None:
            raise HandoffAccessError("handoff is not ready")
        workflow = self.workflows.get_workflow(goal.workflow_id)
        step = next(
            (item for item in workflow.steps if item.step_key == _HANDOFF_STEP),
            None,
        )
        if (
            step is None
            or not step.task_id
            or getattr(step.status, "value", step.status) != "Succeeded"
        ):
            raise HandoffAccessError("handoff is not completed")

        package = self.verified_package(goal_id)
        try:
            with zipfile.ZipFile(package) as archive:
                matches = [
                    item for item in archive.infolist() if item.filename == "HANDOFF_MANIFEST.json"
                ]
                if len(matches) != 1 or matches[0].file_size > _MAX_HANDOFF_RESULT_BYTES:
                    raise HandoffAccessError("handoff manifest is invalid")
                raw = archive.read(matches[0])
            document = json.loads(raw.decode("utf-8"))
            manifest = GoalHandoffPackageManifest.model_validate(document)
        except HandoffAccessError:
            raise
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            zipfile.BadZipFile,
            ValidationError,
        ) as error:
            raise HandoffAccessError("handoff manifest is invalid") from error
        if (
            manifest.goal_id != goal_id
            or manifest.prompt_version != metadata.prompt_version
            or manifest.prompt_version != PROMPT_VERSION
        ):
            raise HandoffAccessError("handoff manifest binding mismatch")

        source_package_id = str(
            uuid5(
                NAMESPACE_URL,
                f"picotoopet:goal-video-source:{goal_id}:{metadata.package_sha256}",
            )
        )
        finding_refs = {
            evidence_id: f"{source_package_id}:finding:{index}"
            for index, evidence_id in enumerate(manifest.evidence_ids, start=1)
        }
        return GoalHandoffContext(
            goal_id=goal_id,
            workflow_id=goal.workflow_id,
            handoff_task_id=step.task_id,
            package_sha256=metadata.package_sha256,
            prompt_version=metadata.prompt_version,
            handoff_created_at=manifest.created_at,
            evidence_ids=manifest.evidence_ids,
            source_ids=manifest.source_ids,
            source_finding_refs=finding_refs,
        )

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
