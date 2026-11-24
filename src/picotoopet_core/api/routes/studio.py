"""V3.1 Studio read-only StoryPack preview on the canonical Mac Core 2.3 APIs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from picotoopet_core.api.errors import ApiError
from picotoopet_core.autonomous.goal_service import HumanGoalRequest, HumanGoalService
from picotoopet_core.autonomous.models import GoalRecord
from picotoopet_core.domain.storypack_scoped_goal import (
    ScopedStoryGoalRequest, list_scoped_reviewed_packets, prepare_scoped_story_goal,
)
from picotoopet_core.domain.storypack import StoryPackError, parse_storypack, storypack_preview
from picotoopet_core.domain.storypack_assets import inspect_recorded_asset_refs
from picotoopet_core.domain.storypack_asset_intake import MAX_ASSET_BYTES, import_local_asset
from picotoopet_core.domain.storypack_asset_registry import (
    OwnerApprovalRequestV1, WindowsClaimRequestV1, find_by_sha256, production_eligibility,
    register_windows_claim, request_owner_approval, storypack_expected_kinds,
)
from picotoopet_core.domain.storypack_fingerprints import build_shot_fingerprints
from picotoopet_core.domain.storypack_plan_bridge import build_storypack_bridge_proposal
from picotoopet_core.domain.storypack_goal_intake import build_storypack_goal_intake
from picotoopet_core.domain.storypack_owner_subject import build_owner_review_subject
from picotoopet_core.security.auth import require_auth

# 只使用原 2.3 设备 Bearer；这不是 Owner / MASTER 身份或 GPU 授权。
router = APIRouter(dependencies=[Depends(require_auth)])
STORYPACK_LIMIT = 128 * 1024


@router.post("/studio/storypacks/preview")
async def preview_storypack(request: Request, response: Response) -> dict:
    """只校验 StoryPack 与已登记资产的字节证据，不创建生产任务。"""

    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"

    # 当前 2.3 适配层先明确支持 JSON；不悄悄引入 PyYAML 或旧 Episode 执行器。
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise ApiError(
            status_code=415,
            code="STORYPACK_JSON_ONLY",
            message="2.3 兼容预览目前仅接受 application/json。",
            retryable=False,
        )

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > STORYPACK_LIMIT:
            raise ApiError(
                status_code=413,
                code="STORYPACK_TOO_LARGE",
                message="StoryPack 输入不能超过 128 KiB。",
                retryable=False,
            )
        body.extend(chunk)

    try:
        pack = parse_storypack(bytes(body))
    except StoryPackError as exc:
        raise ApiError(
            status_code=422,
            code="STORYPACK_VALIDATION_FAILED",
            message=str(exc)[:1200],
            retryable=False,
        ) from exc

    preview = storypack_preview(pack)
    preview["asset_record_checks"] = inspect_recorded_asset_refs(
        request.app.state.services.database,
        preview["unresolved_asset_refs"],
        # 只能验证 Core 托管的 SHA 命名对象，绝不访问用户提交的 source_path。
        managed_objects_dir=request.app.state.services.settings.paths.objects_dir,
        # Slot kinds only explain mismatches; they never register or approve anything.
        expected_kinds=storypack_expected_kinds(pack),
    )
    preview["fingerprint_plan"] = build_shot_fingerprints(
        pack, preview["storypack_sha256"], preview["asset_record_checks"]
    )
    # P0-2: deterministic, SHA-pinned bridge candidate. Never claim this is
    # an executable canonical ProductionPlan or release the Worker GPU HOLD.
    preview["production_bridge_proposal"] = build_storypack_bridge_proposal(
        pack, preview["storypack_sha256"], preview["asset_record_checks"]
    )
    preview["owner_review_subject"] = build_owner_review_subject(
        pack, preview["storypack_sha256"], preview["asset_record_checks"]
    )

    # 仅构造现有 HumanGoalService 的可审阅输入；不创建 Goal、Workflow 或 Task。
    # 草稿到正式 Creative Package 的来源验证和 Production 门禁仍由原 2.3 服务完成。
    preview["canonical_goal_intake"] = build_storypack_goal_intake(
        pack, preview["storypack_sha256"]
    )

    # 预览成功≠合法 ProductionPlan；旧 V3.1 Episode 无法代替 2.3 的审批与 Claim。
    preview["core23_compatibility"] = {
        "contract": "picotoo.studio-2.3.storypack-preview.v1",
        "mode": "READ_ONLY",
        "executable_plan": False,
        "owner_authorized": False,
        "worker_admitted": False,
        "gpu_post_authorized": False,
        "can_queue": False,
    }
    return preview


@router.post("/studio/assets/import", status_code=201)
async def import_storypack_asset(
    request: Request,
    response: Response,
    project_id: str = Header(min_length=1, max_length=100, alias="X-Picotoo-Project-Id"),
    role: str = Header(pattern=r"^(character|scene|style)$", alias="X-Picotoo-Asset-Role"),
    sha256: str = Header(pattern=r"^[a-f0-9]{64}$", alias="X-Picotoo-Asset-SHA256"),
    confirmed: str = Header(alias="X-Picotoo-Import-Confirmed"),
) -> dict:
    """Explicit local copy intake; device Bearer does not constitute Owner approval."""
    response.headers["Cache-Control"] = "no-store, private"
    if confirmed != "yes":
        raise ApiError(status_code=409, code="ASSET_IMPORT_CONFIRMATION_REQUIRED",
                       message="Confirm the local asset copy before import.", retryable=False)

    # Bound the actual streamed body, independently of the Content-Length header.
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_ASSET_BYTES:
            raise ApiError(status_code=413, code="ASSET_TOO_LARGE",
                           message="Asset exceeds local intake limit.", retryable=False)
        data.extend(chunk)

    services = request.app.state.services
    try:
        return await run_in_threadpool(
            import_local_asset, services.database, services.results,
            project_id=project_id, role=role, media_type=media_type,
            declared_sha256=sha256, data=bytes(data),
        )
    except ValueError as exc:
        # Do not echo private filesystem paths or arbitrary exception details.
        code = str(exc)
        if not code.startswith("ASSET_"):
            code = "ASSET_IMPORT_REJECTED"
        raise ApiError(status_code=409, code=code,
                       message="Local asset intake rejected.", retryable=False) from exc
    except OSError as exc:
        raise ApiError(status_code=409, code="ASSET_STORE_UNAVAILABLE",
                       message="Managed store unavailable.", retryable=False) from exc


def _asset_error(exc: Exception) -> ApiError:
    """Map registry denials to stable codes without echoing paths or internals."""
    code = str(exc)
    if isinstance(exc, LookupError):
        return ApiError(status_code=404, code="ASSET_NOT_FOUND",
                        message="Asset is not registered in Core.", retryable=False)
    if not code.startswith(("ASSET_", "ARTIFACT_")):
        code = "ASSET_REQUEST_REJECTED"
    return ApiError(status_code=409, code=code,
                    message="Asset registry request rejected.", retryable=False)


@router.post("/studio/assets/windows-evidence", status_code=201)
def register_windows_asset_claim(
    payload: WindowsClaimRequestV1, request: Request, response: Response
) -> dict:
    """Record a Windows-verified digest for a file Core cannot read (LoRA, workflow).

    Core stores no bytes and claims no byte verification; this grants nothing.
    """
    response.headers["Cache-Control"] = "no-store, private"
    try:
        return register_windows_claim(request.app.state.services.database, payload)
    except ValueError as exc:
        raise _asset_error(exc) from exc


@router.get("/studio/assets/by-sha256")
def lookup_assets_by_sha256(
    request: Request,
    response: Response,
    sha256: str = Query(pattern=r"^[0-9a-fA-F]{64}$"),
    project_id: str | None = Query(default=None, min_length=1, max_length=100),
) -> dict:
    """Full-SHA-256 lookup of real StoryPack artifact IDs. Prefixes are rejected."""
    response.headers["Cache-Control"] = "no-store, private"
    services = request.app.state.services
    return find_by_sha256(services.database, sha256, project_id=project_id,
                          objects_dir=services.results.objects_dir)


@router.post("/studio/assets/{artifact_id}/owner-approval-request", status_code=201)
def request_asset_owner_approval(
    artifact_id: str, payload: OwnerApprovalRequestV1, request: Request, response: Response
) -> dict:
    """Open one pending approval in the existing approvals table; never approve it."""
    response.headers["Cache-Control"] = "no-store, private"
    services = request.app.state.services
    try:
        return request_owner_approval(services.database, services.approvals, artifact_id,
                                      payload, objects_dir=services.results.objects_dir)
    except (LookupError, ValueError) as exc:
        raise _asset_error(exc) from exc


@router.get("/studio/assets/{artifact_id}/production-eligibility")
def asset_production_eligibility(artifact_id: str, request: Request, response: Response) -> dict:
    """Read-only reference eligibility. Eligible is never a GPU authorization."""
    response.headers["Cache-Control"] = "no-store, private"
    services = request.app.state.services
    return production_eligibility(services.database, artifact_id,
                                  objects_dir=services.results.objects_dir)


@router.get("/studio/owner-subject-packets")
def list_owner_subject_packets(
    request: Request,
    response: Response,
    project_id: str = Query(min_length=1, max_length=100),
    character_ref: str = Query(pattern=r"^asset-[a-f0-9]{64}$"),
    subject_key: str = Query(pattern=r"^pet:[a-z0-9][a-z0-9-]{1,63}$"),
) -> dict:
    """Read existing exact packet candidates from the canonical local evidence ledger."""
    response.headers["Cache-Control"] = "no-store, private"
    try:
        return list_scoped_reviewed_packets(
            request.app.state.services, project_id, character_ref, subject_key,
        )
    except ValueError as exc:
        raise ApiError(status_code=409, code="STORY_GOAL_PACKET_LOOKUP_REJECTED",
                       message="Scoped evidence could not be verified.", retryable=False) from exc


@router.post("/studio/storypacks/scoped-goal", response_model=GoalRecord, status_code=201)
async def submit_scoped_storypack_goal(
    request: Request,
    response: Response,
    confirmed: str = Header(alias="X-Picotoo-Goal-Confirmed"),
) -> GoalRecord:
    """Explicitly create the existing local Goal, not a Creative or GPU approval."""
    response.headers["Cache-Control"] = "no-store, private"
    if confirmed != "yes":
        raise ApiError(status_code=409, code="STORY_GOAL_CONFIRMATION_REQUIRED",
                       message="Explicit Goal confirmation required.", retryable=False)
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise ApiError(status_code=415, code="STORYPACK_JSON_ONLY",
                       message="JSON required.", retryable=False)

    # Read bounded bytes rather than accepting an unbounded automatic Pydantic body.
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > STORYPACK_LIMIT:
            raise ApiError(status_code=413, code="STORYPACK_TOO_LARGE",
                           message="StoryPack input too large.", retryable=False)
        body.extend(chunk)

    # Reject duplicate keys and nonfinite JSON in the wrapper as well as in the pack.
    import json
    from picotoopet_core.domain.storypack import _unique_json_pairs

    def reject_nonfinite(value: str) -> None:
        raise ValueError("STORY_GOAL_NONFINITE")

    try:
        decoded = json.loads(
            bytes(body).decode("utf-8-sig"),
            object_pairs_hook=_unique_json_pairs,
            parse_constant=reject_nonfinite,
        )
        payload = ScopedStoryGoalRequest.model_validate(decoded)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ApiError(status_code=422, code="STORY_GOAL_INVALID",
                       message="Invalid scoped StoryPack request.", retryable=False) from exc

    services = request.app.state.services

    def create() -> GoalRecord:
        proposal, binding = prepare_scoped_story_goal(payload, services)
        goal_request = HumanGoalRequest(
            goal_type="video.creative", objective=proposal["objective"],
            depth="standard", local_video_preferred=True,
            owner_subject_key=payload.owner_subject_key,
        )
        # One reviewed scope, one idempotent existing Goal; caller cannot set constraints.
        import hashlib
        digest = hashlib.sha256(json.dumps(
            binding, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")).hexdigest()
        return HumanGoalService(services.autonomous_goals, services.workflows).create(
            goal_request, idempotency_key="studio-scoped-story-v1-" + digest,
            scoped_story_binding=binding,
        )

    try:
        return await run_in_threadpool(create)
    except ValueError as exc:
        code = str(exc)
        if not code.startswith("STORY_GOAL_"):
            code = "STORY_GOAL_REJECTED"
        raise ApiError(status_code=409, code=code,
                       message="Scoped Goal evidence did not verify.", retryable=False) from exc
