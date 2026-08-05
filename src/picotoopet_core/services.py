"""Mac Core 依赖容器。"""

from __future__ import annotations

from dataclasses import dataclass

from picotoopet_core.approvals.service import ApprovalService
from picotoopet_core.audit.writer import AuditWriter
from picotoopet_core.config.models import AppSettings
from picotoopet_core.db.database import Database
from picotoopet_core.events.broker import EventBroker
from picotoopet_core.events.dispatcher import OutboxDispatcher
from picotoopet_core.events.outbox import EventOutbox
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.handoffs.service import HandoffService
from picotoopet_core.ollama.client import OllamaClient
from picotoopet_core.ollama.resident_manager import ResidentManager
from picotoopet_core.projects.repository import ProjectRepository
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.queue.repository import QueueRepository
from picotoopet_core.results.repository import ResultRepository
from picotoopet_core.results.store import ResultStore
from picotoopet_core.worker.state import WorkerStateStore


@dataclass(slots=True)
class Services:
    """应用内共享服务集合。"""

    settings: AppSettings
    database: Database
    projects: ProjectRepository
    queue: QueueRepository
    approvals: ApprovalService
    handoffs: HandoffService
    audit: AuditWriter
    results: ResultStore
    result_records: ResultRepository
    outbox: EventOutbox
    broker: EventBroker
    dispatcher: OutboxDispatcher
    ollama: OllamaClient
    resident: ResidentManager
    worker_state: WorkerStateStore

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
    outbox = EventOutbox(database)
    broker = EventBroker()
    dispatcher = OutboxDispatcher(outbox, broker)
    queue = DiagnosticQueueRepository(database, outbox=outbox)
    approvals = HandoffApprovalService(database, queue)
    handoffs = HandoffService(database, approvals)
    result_store = ResultStore(settings.paths.results_dir)
    ollama = OllamaClient(settings.ollama_base_url, timeout_seconds=2.0)
    worker_state = WorkerStateStore(
        settings.paths.state_dir / "worker-status.json",
        stale_after_seconds=settings.worker_status_stale_seconds,
    )
    return Services(
        settings=settings,
        database=database,
        projects=ProjectRepository(database),
        queue=queue,
        approvals=approvals,
        handoffs=handoffs,
        audit=AuditWriter(database),
        results=result_store,
        result_records=ResultRepository(database),
        outbox=outbox,
        broker=broker,
        dispatcher=dispatcher,
        ollama=ollama,
        resident=ResidentManager(ollama, settings.ollama_model),
        worker_state=worker_state,
    )
