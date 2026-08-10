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
from picotoopet_core.config.loader import load_settings
from picotoopet_core.config.models import AppSettings
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
    """运行独立 Worker；受控 Provider 能力只在对应固定配置完整时注册。"""

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
    adoption_coordinator: AdoptionExecutionCoordinator | None = None
    commit_coordinator: ProviderCommitExecutionCoordinator | None = None
    publication_coordinator: ProviderPublicationExecutionCoordinator | None = None
    if settings.provider_execution_configured:
        assert settings.provider_repository is not None
        assert settings.provider_worktree_root is not None
        assert settings.codex_executable is not None
        provider_coordinator = ProviderExecutionCoordinator(
            queue=services.queue,
            sessions=services.provider_sessions,
            repository=settings.provider_repository,
            worktree_root=settings.provider_worktree_root,
            codex_executable=settings.codex_executable,
            worker_id=resolved_worker_id,
            artifact_store=services.provider_artifacts,
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
        runtime.handlers[ProviderExecutionCoordinator.TASK_TYPE] = provider_coordinator.handler
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

    def enqueue_controlled_work() -> None:
        if provider_coordinator is not None:
            provider_coordinator.enqueue_pending()
        if adoption_coordinator is not None:
            adoption_coordinator.enqueue_pending()
        if commit_coordinator is not None:
            commit_coordinator.enqueue_pending()
        if publication_coordinator is not None:
            publication_coordinator.enqueue_pending()

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
            publish_execution_capability(healthy=True)
            enqueue_controlled_work()
            result = runtime.run_once()
            print(
                json.dumps(
                    {
                        "processed": result.processed,
                        "succeeded": result.succeeded,
                        "task_id": result.task_id,
                        "worker_id": resolved_worker_id,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0 if result.succeeded else 5
        if not loop:
            raise AssertionError("Worker 必须选择 --once 或 --loop。")
        stop_event = Event()

        def request_stop(_signum: int, _frame: object) -> None:
            stop_event.set()

        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
        while not stop_event.is_set():
            publish_execution_capability(healthy=True)
            enqueue_controlled_work()
            runtime.run_once()
            stop_event.wait(settings.worker_poll_seconds)
        return 0
    finally:
        try:
            publish_execution_capability(healthy=False)
        finally:
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
