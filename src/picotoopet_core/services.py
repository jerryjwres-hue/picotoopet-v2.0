"""Mac Core 依赖容器。"""

from __future__ import annotations

from dataclasses import dataclass

from picotoopet_core.approvals.service import ApprovalService
from picotoopet_core.audit.writer import AuditWriter
from picotoopet_core.config.models import AppSettings
from picotoopet_core.domain.episode_budget import EpisodeBudgetPolicy
from picotoopet_core.db.database import Database
from picotoopet_core.events.broker import EventBroker
from picotoopet_core.events.dispatcher import OutboxDispatcher
from picotoopet_core.events.outbox import EventOutbox
from picotoopet_core.ollama.client import OllamaClient
from picotoopet_core.ollama.resident_manager import ResidentManager
from picotoopet_core.projects.repository import ProjectRepository
from picotoopet_core.queue.executor import ExecutorService
from picotoopet_core.queue.production import ProductionService
from picotoopet_core.queue.repository import QueueRepository
from picotoopet_core.results.store import ResultStore


@dataclass(slots=True)
class Services:
    """应用内共享服务集合。"""

    settings: AppSettings
    # 数据库中一次启用后持续存在；凭据配置删除不会重新开放旧 GPU 路径。
    owner_mode_gpu_hold: bool
    database: Database
    projects: ProjectRepository
    queue: QueueRepository
    executor: ExecutorService
    production: ProductionService
    approvals: ApprovalService
    audit: AuditWriter
    results: ResultStore
    outbox: EventOutbox
    broker: EventBroker
    dispatcher: OutboxDispatcher
    ollama: OllamaClient
    resident: ResidentManager

    def close(self) -> None:
        """按依赖顺序关闭外部资源。"""

        self.ollama.close()
        self.database.close()


def build_services(settings: AppSettings) -> Services:
    """创建目录、迁移数据库并装配全部服务。"""

    settings.paths.ensure()
    database = Database(settings.paths.database_file)
    database.open()
    database.apply_migrations()
    # 先持久化生产保护，再向 FastAPI/Worker 暴露任何 HTTP 入口。
    owner_mode_gpu_hold = database.owner_gpu_hold(
        owner_credentials_configured=bool(settings.owner_review_registry.credentials),
    )
    outbox    = EventOutbox(database)
    broker    = EventBroker()
    dispatcher = OutboxDispatcher(outbox, broker)
    queue     = QueueRepository(database, outbox=outbox)
    audit     = AuditWriter(database)
    executor  = ExecutorService(queue, audit)
    ollama = OllamaClient(settings.ollama_base_url, timeout_seconds=2.0)
    return Services(
        settings=settings,
        owner_mode_gpu_hold=owner_mode_gpu_hold,
        database=database,
        projects=ProjectRepository(database),
        queue=queue,
        approvals=ApprovalService(database, queue),
        audit=audit,
        executor=executor,
        production=ProductionService(
            executor,
            budget=EpisodeBudgetPolicy(
                max_takes_per_shot=settings.episode_max_takes_per_shot,
                max_takes_per_episode=settings.episode_max_takes_per_episode,
                max_reserved_video_seconds=settings.episode_max_reserved_video_seconds,
            ),
        ),
        results=ResultStore(settings.paths.results_dir),
        outbox=outbox,
        broker=broker,
        dispatcher=dispatcher,
        ollama=ollama,
        resident=ResidentManager(ollama, settings.ollama_model),
    )
