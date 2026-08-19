"""Mac Core 命令行入口；由 launchd 和双击脚本调用。"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import time
from collections.abc import Sequence
from threading import Event

from picotoopet_core.api.app import create_app
from picotoopet_core.automation.models import CapabilityRegistration
from picotoopet_core.autonomous.background import AutonomousBackgroundCoordinator
from picotoopet_core.autonomous.local_intelligence import (
    LocalIntelligenceCoordinator,
    build_ollama_local_intelligence_adapter,
)
from picotoopet_core.business.execution import BusinessLocalIntelligenceCoordinator
from picotoopet_core.business.local_intelligence import (
    LocalIntelligenceConfig,
    OpenAiCompatibleLocalIntelligenceAdapter,
)
from picotoopet_core.config.loader import load_settings
from picotoopet_core.config.models import AppSettings
from picotoopet_core.creative.execution import CreativeIntelligenceCoordinator
from picotoopet_core.deep_ai.execution import DeepAiWorkerExecutionLoop
from picotoopet_core.deep_ai.policy import DeepAiEscalationPolicy
from picotoopet_core.deep_ai.provider import (
    DeepAiProviderRequestReader,
    DeepAiProviderResultStore,
    DeepAiWorkerProviderConfig,
    OpenAiResponsesPaidAiAdapter,
)
from picotoopet_core.health.supervisor import HealthSupervisor
from picotoopet_core.ollama.client import OllamaClient
from picotoopet_core.ollama.resident_manager import (
    ResidentManager,
    ResidentResult,
    ResidentStatus,
)
from picotoopet_core.providers.adoption_execution import AdoptionExecutionCoordinator
from picotoopet_core.providers.commit_execution import ProviderCommitExecutionCoordinator
from picotoopet_core.providers.execution import ProviderExecutionCoordinator
from picotoopet_core.providers.publication_execution import (
    ProviderPublicationExecutionCoordinator,
)
from picotoopet_core.providers.readiness import ProviderReadinessProjection
from picotoopet_core.providers.readiness_worker import ProviderReadinessPublisher
from picotoopet_core.services import build_services
from picotoopet_core.worker.runtime import WorkerRuntime


class _HealthyResident:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def ensure_resident(self) -> ResidentResult:
        return ResidentResult(
            status=ResidentStatus.RESIDENT,
            model_name=self.model_name,
            detail="本次健康检查按参数跳过 Ollama。",
        )


def _build_resident_manager(settings: AppSettings) -> ResidentManager:
    client = OllamaClient(settings.ollama_base_url, timeout_seconds=10.0)
    return ResidentManager(client, settings.ollama_model)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="picotoopet-core")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="启动 REST、WebSocket 和 OpenAPI 服务")
    worker = commands.add_parser("worker", help="启动独立本地任务执行器")
    worker_mode = worker.add_mutually_exclusive_group(required=True)
    worker_mode.add_argument("--once", action="store_true", help="最多处理一个任务后退出")
    worker_mode.add_argument("--loop", action="store_true", help="持续轮询任务队列")
    worker.add_argument("--worker-id", default="", help="可选稳定 Worker 标识")
    health = commands.add_parser("health", help="执行一次本地健康检查")
    health.add_argument("--skip-ollama", action="store_true")
    resident = commands.add_parser("resident-check", help="检查并恢复 gpt-oss:20b 常驻")
    resident.add_argument("--json", action="store_true", default=True)
    supervise = commands.add_parser("supervise", help="持续执行健康监督")
    supervise.add_argument("--loop", action="store_true")
    return parser


def _run_health(settings: AppSettings, *, skip_ollama: bool) -> int:
    services = build_services(settings)
    try:
        resident = _HealthyResident(settings.ollama_model) if skip_ollama else services.resident
        report = HealthSupervisor(
            database=services.database,
            paths=settings.paths,
            resident=resident,
        ).run_once()
        print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        services.close()


def _run_resident_check(settings: AppSettings) -> int:
    manager = _build_resident_manager(settings)
    try:
        result = manager.ensure_resident()
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
        return 0 if result.status is ResidentStatus.RESIDENT else 3
    finally:
        client = getattr(manager, "client", None)
        if client is not None and hasattr(client, "close"):
            client.close()


def _run_supervisor(settings: AppSettings, *, loop: bool) -> int:
    while True:
        _run_health(settings, skip_ollama=False)
        if not loop:
            return 0
        time.sleep(settings.resident_check_seconds)


def _run_worker(
    settings: AppSettings,
    *,
    once: bool,
    loop: bool,
    worker_id: str,
) -> int:
    """运行独立 Worker；只注册当前健康、封闭且受信配置的执行能力。"""

    services = build_services(settings)
    resolved_worker_id = worker_id.strip() or f"{socket.gethostname()}-{os.getpid()}"
    runtime = WorkerRuntime(
        queue=services.queue,
        state_store=services.worker_state,
        worker_id=resolved_worker_id,
        database=services.database,
        result_store=services.results,
        lease_seconds=settings.worker_lease_seconds,
        heartbeat_seconds=settings.worker_heartbeat_seconds,
        poll_seconds=settings.worker_poll_seconds,
    )
    provider_coordinator: ProviderExecutionCoordinator | None = None
    provider_readiness: ProviderReadinessPublisher | None = None
    adoption_coordinator: AdoptionExecutionCoordinator | None = None
    commit_coordinator: ProviderCommitExecutionCoordinator | None = None
    publication_coordinator: ProviderPublicationExecutionCoordinator | None = None
    business_adapter: OpenAiCompatibleLocalIntelligenceAdapter | None = None
    business_coordinator: BusinessLocalIntelligenceCoordinator | None = None
    creative_coordinator: CreativeIntelligenceCoordinator | None = None
    deep_ai_provider_config = DeepAiWorkerProviderConfig.from_environment(os.environ)
    deep_ai_provider_adapter: OpenAiResponsesPaidAiAdapter | None = None
    deep_ai_execution_loop: DeepAiWorkerExecutionLoop | None = None
    business_healthy = False
    last_business_probe = 0.0

    if settings.provider_execution_configured:
        assert settings.provider_repository is not None
        assert settings.provider_worktree_root is not None
        provider_readiness = ProviderReadinessPublisher(
            projection=ProviderReadinessProjection(services.capability_router),
            worker_id=resolved_worker_id,
            repository=settings.provider_repository,
            codex_executable=settings.codex_executable,
            claude_code_executable=settings.claude_code_executable,
        )
        provider_coordinator = ProviderExecutionCoordinator(
            queue=services.queue,
            sessions=services.provider_sessions,
            repository=settings.provider_repository,
            worktree_root=settings.provider_worktree_root,
            codex_executable=settings.codex_executable,
            claude_code_executable=settings.claude_code_executable,
            worker_id=resolved_worker_id,
            artifact_store=services.provider_artifacts,
            readiness_by_provider=provider_readiness.status,
        )
        adoption_coordinator = AdoptionExecutionCoordinator(
            database=services.database,
            queue=services.queue,
            repository=settings.provider_repository,
            worktree_root=settings.paths.runtime_dir / "adoption-worktrees",
            artifact_store=services.provider_artifacts,
        )
        commit_coordinator = ProviderCommitExecutionCoordinator(
            database=services.database,
            queue=services.queue,
            repository=settings.provider_repository,
            worktree_root=settings.paths.runtime_dir / "commit-worktrees",
            artifact_store=services.provider_artifacts,
        )
        for task_type in provider_coordinator.configured_task_types:
            runtime.handlers[task_type] = provider_coordinator.handler
        runtime.handlers[AdoptionExecutionCoordinator.TASK_TYPE] = adoption_coordinator.handler
        runtime.handlers[ProviderCommitExecutionCoordinator.TASK_TYPE] = commit_coordinator.handler
    if settings.provider_publication_configured:
        assert settings.provider_repository is not None
        assert settings.github_cli_executable is not None
        publication_coordinator = ProviderPublicationExecutionCoordinator(
            database=services.database,
            queue=services.queue,
            repository=settings.provider_repository,
            github_cli_executable=settings.github_cli_executable,
        )
        runtime.handlers[ProviderPublicationExecutionCoordinator.TASK_TYPE] = (
            publication_coordinator.handler
        )

    try:
        local_config = LocalIntelligenceConfig(
            base_url=settings.local_intelligence_base_url,
            model_id=settings.local_intelligence_model,
            timeout_seconds=settings.local_intelligence_timeout_seconds,
            max_context_chars=settings.local_intelligence_max_context_chars,
        )
        business_adapter = OpenAiCompatibleLocalIntelligenceAdapter(local_config)
        business_coordinator = BusinessLocalIntelligenceCoordinator(
            database=services.database,
            queue=services.queue,
            repository=services.business_repository,
            store=services.business_store,
            adapter=business_adapter,
            configured_model_id=local_config.model_id,
        )
        creative_coordinator = CreativeIntelligenceCoordinator(
            database=services.database,
            queue=services.queue,
            repository=services.creative_repository,
            source_normalizer=services.creative_source,
            store=services.creative_store,
            adapter=business_adapter,
            configured_model_id=local_config.model_id,
        )
    except ValueError:
        business_adapter = None
        business_coordinator = None
        creative_coordinator = None

    autonomous_local_coordinator = LocalIntelligenceCoordinator(
        build_ollama_local_intelligence_adapter(
            model_name=settings.local_intelligence_model,
            base_url=settings.local_intelligence_base_url.rstrip("/"),
        )
    )
    autonomous_background = AutonomousBackgroundCoordinator(
        manager=services.autonomous_manager,
        capability_router=services.capability_router,
        runtime=runtime,
        worker_id=resolved_worker_id,
        local_intelligence_handler=autonomous_local_coordinator.handler,
        model_id=settings.local_intelligence_model,
    )

    if deep_ai_provider_config.execution_enabled:
        deep_ai_provider_adapter = OpenAiResponsesPaidAiAdapter(deep_ai_provider_config)
        deep_ai_execution_loop = DeepAiWorkerExecutionLoop(
            repository=services.deep_ai_repository,
            approvals=services.deep_ai.approvals,
            policy=DeepAiEscalationPolicy.default(),
            config=deep_ai_provider_config,
            provider=deep_ai_provider_adapter,
            request_reader=DeepAiProviderRequestReader(settings.paths),
            result_store=DeepAiProviderResultStore(settings.paths),
        )

    def enqueue_controlled_work() -> None:
        if provider_coordinator is not None:
            provider_coordinator.enqueue_pending()
        if adoption_coordinator is not None:
            adoption_coordinator.enqueue_pending()
        if commit_coordinator is not None:
            commit_coordinator.enqueue_pending()
        if publication_coordinator is not None:
            publication_coordinator.enqueue_pending()

    def refresh_business_capability(*, force: bool = False) -> bool:
        """Probe one loopback model and atomically expose both closed intelligence capabilities."""

        nonlocal business_healthy, last_business_probe
        now = time.monotonic()
        if force or now - last_business_probe >= 15.0:
            business_healthy = bool(business_adapter is not None and business_adapter.health())
            last_business_probe = now
            if business_healthy and business_coordinator is not None:
                runtime.handlers[BusinessLocalIntelligenceCoordinator.TASK_TYPE] = (
                    business_coordinator.handler
                )
            else:
                runtime.handlers.pop(BusinessLocalIntelligenceCoordinator.TASK_TYPE, None)
            if business_healthy and creative_coordinator is not None:
                runtime.handlers[CreativeIntelligenceCoordinator.TASK_TYPE] = (
                    creative_coordinator.handler
                )
            else:
                runtime.handlers.pop(CreativeIntelligenceCoordinator.TASK_TYPE, None)
        services.capability_router.register(
            CapabilityRegistration(
                worker_id=resolved_worker_id,
                capability=BusinessLocalIntelligenceCoordinator.CAPABILITY,
                task_types=(
                    [BusinessLocalIntelligenceCoordinator.TASK_TYPE] if business_healthy else []
                ),
                healthy=business_healthy,
                metadata={
                    "runtime": "mac-worker",
                    "transport": "loopback-openai-compatible",
                    "model": settings.local_intelligence_model,
                },
            )
        )
        services.capability_router.register(
            CapabilityRegistration(
                worker_id=resolved_worker_id,
                capability=CreativeIntelligenceCoordinator.CAPABILITY,
                task_types=[CreativeIntelligenceCoordinator.TASK_TYPE] if business_healthy else [],
                healthy=business_healthy,
                metadata={
                    "runtime": "mac-worker",
                    "transport": "loopback-openai-compatible",
                    "model": settings.local_intelligence_model,
                },
            )
        )
        return business_healthy

    def publish_paid_ai_capability(*, healthy: bool) -> None:
        services.capability_router.register(
            CapabilityRegistration(
                worker_id=resolved_worker_id,
                capability=DeepAiWorkerExecutionLoop.CAPABILITY,
                task_types=[],
                healthy=healthy,
                metadata={
                    "runtime": "mac-worker",
                    "provider": deep_ai_provider_config.redacted_dict(),
                },
            )
        )

    def publish_execution_capability(*, healthy: bool) -> None:
        """只声明当前封闭 handler 注册表能够真实执行的任务类型。"""

        services.capability_router.register(
            CapabilityRegistration(
                worker_id=resolved_worker_id,
                capability="local.system.execution",
                task_types=list(runtime.supported_task_types),
                healthy=healthy,
                metadata={"runtime": "mac-worker"},
            )
        )

    try:
        if once:
            local_healthy = refresh_business_capability(force=True)
            if provider_readiness is not None:
                provider_readiness.refresh(force=True)
            autonomous_background.refresh_local_intelligence(healthy=local_healthy)
            publish_paid_ai_capability(healthy=deep_ai_execution_loop is not None)
            publish_execution_capability(healthy=True)
            enqueue_controlled_work()
            paid_processed = (
                deep_ai_execution_loop.run_once() if deep_ai_execution_loop is not None else 0
            )
            result = runtime.run_once()
            print(
                json.dumps(
                    {
                        "processed": bool(paid_processed or result.processed),
                        "succeeded": bool(paid_processed or result.succeeded),
                        "task_id": result.task_id,
                        "worker_id": resolved_worker_id,
                        "paid_ai_processed": paid_processed,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0 if (paid_processed or result.succeeded) else 5
        if not loop:
            raise AssertionError("Worker 必须选择 --once 或 --loop。")
        stop_event = Event()

        def request_stop(_signum: int, _frame: object) -> None:
            stop_event.set()

        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
        while not stop_event.is_set():
            local_healthy = refresh_business_capability()
            if provider_readiness is not None:
                provider_readiness.refresh()
            autonomous_background.refresh_local_intelligence(healthy=local_healthy)
            publish_paid_ai_capability(healthy=deep_ai_execution_loop is not None)
            publish_execution_capability(healthy=True)
            enqueue_controlled_work()
            if deep_ai_execution_loop is not None:
                deep_ai_execution_loop.run_once()
            autonomous_background.tick_safely()
            runtime.run_once()
            stop_event.wait(settings.worker_poll_seconds)
        return 0
    finally:
        try:
            autonomous_background.refresh_local_intelligence(healthy=False)
            if provider_readiness is not None:
                provider_readiness.publish_unavailable()
            services.capability_router.register(
                CapabilityRegistration(
                    worker_id=resolved_worker_id,
                    capability=BusinessLocalIntelligenceCoordinator.CAPABILITY,
                    task_types=[],
                    healthy=False,
                    metadata={"runtime": "mac-worker"},
                )
            )
            services.capability_router.register(
                CapabilityRegistration(
                    worker_id=resolved_worker_id,
                    capability=CreativeIntelligenceCoordinator.CAPABILITY,
                    task_types=[],
                    healthy=False,
                    metadata={"runtime": "mac-worker"},
                )
            )
            publish_paid_ai_capability(healthy=False)
            runtime.handlers.pop(BusinessLocalIntelligenceCoordinator.TASK_TYPE, None)
            runtime.handlers.pop(CreativeIntelligenceCoordinator.TASK_TYPE, None)
            runtime.handlers.pop(LocalIntelligenceCoordinator.TASK_TYPE, None)
            publish_execution_capability(healthy=False)
        finally:
            if deep_ai_provider_adapter is not None:
                deep_ai_provider_adapter.close()
            if business_adapter is not None:
                business_adapter.close()
            services.close()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    settings = load_settings()
    if arguments.command == "serve":
        import uvicorn

        uvicorn.run(
            create_app(settings),
            host=settings.api_host,
            port=settings.api_port,
            log_level="info",
        )
        return 0
    if arguments.command == "worker":
        return _run_worker(
            settings,
            once=arguments.once,
            loop=arguments.loop,
            worker_id=arguments.worker_id,
        )
    if arguments.command == "health":
        return _run_health(settings, skip_ollama=arguments.skip_ollama)
    if arguments.command == "resident-check":
        return _run_resident_check(settings)
    if arguments.command == "supervise":
        return _run_supervisor(settings, loop=arguments.loop)
    raise AssertionError(f"未处理命令：{arguments.command}")


if __name__ == "__main__":
    raise SystemExit(main())