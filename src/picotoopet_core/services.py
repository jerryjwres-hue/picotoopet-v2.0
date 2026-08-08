"""Mac Core 依赖容器。"""

from __future__ import annotations

from dataclasses import dataclass

from picotoopet_core.approvals.service import ApprovalService
from picotoopet_core.audit.writer import AuditWriter
from picotoopet_core.automation.capabilities import CapabilityRouter
from picotoopet_core.automation.quality import QualityGate
from picotoopet_core.automation.repository import AutomationRepository
from picotoopet_core.automation.service import WorkflowService
from picotoopet_core.broker.service import BrokerSessionService
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
from picotoopet_core.providers.artifact_store import ProviderReturnArtifactStore
from picotoopet_core.providers.commit_service import ProviderCommitService
from picotoopet_core.providers.readiness import CodexReadinessProbe
from picotoopet_core.providers.review_service import ProviderReviewService
from picotoopet_core.providers.service import ProviderSessionService
from picotoopet_core.queue.diagnostic_repository import DiagnosticQueueRepository
from picotoopet_core.queue.repository import QueueRepository
from picotoopet_core.results.repository import ResultRepository
from picotoopet_core.results.store import ResultStore
from picotoopet_core.returns.service import ReturnValidationService
from picotoopet_core.worker.state import WorkerStateStore


@dataclass(slots=True)
class Services:
    settings: AppSettings
    database: Database
    projects: ProjectRepository
    queue: QueueRepository
    workflows: WorkflowService
    automation_repository: AutomationRepository
    capability_router: CapabilityRouter
    quality_gate: QualityGate
    approvals: ApprovalService
    handoffs: HandoffService
    returns: ReturnValidationService
    broker_sessions: BrokerSessionService
    provider_sessions: ProviderSessionService
    provider_artifacts: ProviderReturnArtifactStore
    provider_reviews: ProviderReviewService
    provider_commits: ProviderCommitService
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
        self.ollama.close()
        self.database.close()


def build_services(settings: AppSettings) -> Services:
    settings.paths.ensure()
    database = Database(settings.paths.database_file)
    database.open()
    database.apply_migrations()
    outbox = EventOutbox(database)
    broker = EventBroker()
    dispatcher = OutboxDispatcher(outbox, broker)
    queue = DiagnosticQueueRepository(database, outbox=outbox)
    automation_repository = AutomationRepository(database)
    workflows = WorkflowService(
        database,
        queue=queue,
        repository=automation_repository,
    )
    capability_router = workflows.capabilities
    quality_gate = QualityGate(automation_repository)
    approvals = HandoffApprovalService(database, queue)
    handoffs = HandoffService(database, approvals)
    returns = ReturnValidationService(database, handoffs)
    broker_sessions = BrokerSessionService(
        database,
        handoffs,
        returns,
        api_token=settings.api_token,
    )
    readiness = CodexReadinessProbe(settings.codex_executable)
    provider_sessions = ProviderSessionService(
        database,
        handoffs,
        readiness=readiness.status,
    )
    provider_artifacts = ProviderReturnArtifactStore(settings.paths.provider_returns_dir)
    provider_reviews = ProviderReviewService(database, provider_artifacts)
    provider_commits = ProviderCommitService(database, approvals)
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
        workflows=workflows,
        automation_repository=automation_repository,
        capability_router=capability_router,
        quality_gate=quality_gate,
        approvals=approvals,
        handoffs=handoffs,
        returns=returns,
        broker_sessions=broker_sessions,
        provider_sessions=provider_sessions,
        provider_artifacts=provider_artifacts,
        provider_reviews=provider_reviews,
        provider_commits=provider_commits,
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
