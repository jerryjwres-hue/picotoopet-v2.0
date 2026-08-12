"""Mac Core 依赖容器。"""

from __future__ import annotations

from dataclasses import dataclass

from picotoopet_core.approvals.service import ApprovalService
from picotoopet_core.audit.writer import AuditWriter
from picotoopet_core.automation.capabilities import CapabilityRouter
from picotoopet_core.automation.quality import QualityGate
from picotoopet_core.automation.repository import AutomationRepository
from picotoopet_core.automation.scheduler import WorkflowScheduler
from picotoopet_core.automation.service import WorkflowService
from picotoopet_core.broker.service import BrokerSessionService
from picotoopet_core.business.repository import BusinessRepository
from picotoopet_core.business.service import BusinessAutomationService
from picotoopet_core.business.store import BusinessArtifactStore
from picotoopet_core.business_pipeline.repository import BusinessPipelineRepository
from picotoopet_core.business_pipeline.scheduler import BusinessPipelineScheduler
from picotoopet_core.business_pipeline.service import BusinessPipelineService
from picotoopet_core.business_pipeline.store import BusinessReturnPackageStore
from picotoopet_core.config.models import AppSettings
from picotoopet_core.creative.repository import CreativeRepository
from picotoopet_core.creative.service import CreativeIntelligenceService
from picotoopet_core.creative.source import CreativeSourceNormalizer
from picotoopet_core.creative.store import CreativeArtifactStore
from picotoopet_core.db.database import Database
from picotoopet_core.deep_ai.continuation import DeepAiSourceContinuation
from picotoopet_core.deep_ai.evaluation import (
    QualityEvaluationRepository,
    QualityEvaluationService,
)
from picotoopet_core.deep_ai.learning import DeepAiLearningLedger
from picotoopet_core.deep_ai.policy import DeepAiEscalationPolicy
from picotoopet_core.deep_ai.provider import DeepAiProviderResultStore
from picotoopet_core.deep_ai.repository import DeepAiRepository
from picotoopet_core.deep_ai.result_processing import DeepAiResultProcessor
from picotoopet_core.deep_ai.service import CoreDeepAiSourceResolver, DeepAiEscalationService
from picotoopet_core.deep_ai.shadow import QualityShadowRepository, QualityShadowService
from picotoopet_core.deep_ai.store import DeepAiSanitizedPackageStore
from picotoopet_core.deep_ai.validation import DeepAiResultValidator
from picotoopet_core.events.broker import EventBroker
from picotoopet_core.events.dispatcher import OutboxDispatcher
from picotoopet_core.events.outbox import EventOutbox
from picotoopet_core.handoffs.approvals import HandoffApprovalService
from picotoopet_core.handoffs.service import HandoffService
from picotoopet_core.ollama.client import OllamaClient
from picotoopet_core.ollama.resident_manager import ResidentManager
from picotoopet_core.production.repository import ProductionRepository
from picotoopet_core.production.service import ProductionService
from picotoopet_core.production.store import ProductionArtifactStore
from picotoopet_core.projects.repository import ProjectRepository
from picotoopet_core.providers.artifact_store import ProviderReturnArtifactStore
from picotoopet_core.providers.commit_service import ProviderCommitService
from picotoopet_core.providers.publication_service import ProviderPublicationService
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
    workflow_scheduler: WorkflowScheduler
    automation_repository: AutomationRepository
    capability_router: CapabilityRouter
    quality_gate: QualityGate
    business_repository: BusinessRepository
    business_store: BusinessArtifactStore
    business: BusinessAutomationService
    creative_repository: CreativeRepository
    creative_source: CreativeSourceNormalizer
    creative_store: CreativeArtifactStore
    creative: CreativeIntelligenceService
    production_repository: ProductionRepository
    production_store: ProductionArtifactStore
    production: ProductionService
    business_pipeline_repository: BusinessPipelineRepository
    business_return_store: BusinessReturnPackageStore
    business_pipeline: BusinessPipelineService
    business_pipeline_scheduler: BusinessPipelineScheduler
    deep_ai_repository: DeepAiRepository
    deep_ai_store: DeepAiSanitizedPackageStore
    deep_ai: DeepAiEscalationService
    deep_ai_result_processor: DeepAiResultProcessor
    quality_evaluation_repository: QualityEvaluationRepository
    quality_evaluation: QualityEvaluationService
    quality_shadow_repository: QualityShadowRepository
    quality_shadow: QualityShadowService
    approvals: ApprovalService
    handoffs: HandoffService
    returns: ReturnValidationService
    broker_sessions: BrokerSessionService
    provider_sessions: ProviderSessionService
    provider_artifacts: ProviderReturnArtifactStore
    provider_reviews: ProviderReviewService
    provider_commits: ProviderCommitService
    provider_publications: ProviderPublicationService
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
    workflows = WorkflowService(database, queue=queue, repository=automation_repository)
    workflow_scheduler = WorkflowScheduler(workflows)
    capability_router = workflows.capabilities
    quality_gate = QualityGate(automation_repository)
    business_repository = BusinessRepository(database)
    business_store = BusinessArtifactStore(settings.paths)
    business = BusinessAutomationService(business_repository, business_store, queue)
    creative_repository = CreativeRepository(database)
    creative_source = CreativeSourceNormalizer(database)
    creative_store = CreativeArtifactStore(settings.paths)
    creative = CreativeIntelligenceService(
        repository=creative_repository,
        source_normalizer=creative_source,
        store=creative_store,
        queue=queue,
    )
    production_repository = ProductionRepository(database)
    production_store = ProductionArtifactStore(settings.paths)
    production = ProductionService(
        repository=production_repository,
        creative_repository=creative_repository,
        store=production_store,
    )
    business_pipeline_repository = BusinessPipelineRepository(database)
    business_return_store = BusinessReturnPackageStore(settings.paths)
    business_pipeline = BusinessPipelineService(
        repository=business_pipeline_repository,
        business=business,
        creative=creative,
        production=production,
        return_store=business_return_store,
    )
    business_pipeline_scheduler = BusinessPipelineScheduler(business_pipeline)
    approvals = HandoffApprovalService(database, queue)
    deep_ai_repository = DeepAiRepository(database)
    deep_ai_store = DeepAiSanitizedPackageStore(settings.paths)
    deep_ai_source_resolver = CoreDeepAiSourceResolver(
        business_repository,
        creative_repository,
    )
    deep_ai = DeepAiEscalationService(
        repository=deep_ai_repository,
        store=deep_ai_store,
        approvals=approvals,
        source_resolver=deep_ai_source_resolver,
        policy=DeepAiEscalationPolicy.default(),
    )
    deep_ai_result_processor = DeepAiResultProcessor(
        repository=deep_ai_repository,
        result_store=DeepAiProviderResultStore(settings.paths),
        source_resolver=deep_ai_source_resolver,
        validator=DeepAiResultValidator(),
        continuation=DeepAiSourceContinuation(
            business_repository=business_repository,
            business_store=business_store,
            creative_repository=creative_repository,
            queue=queue,
            pipeline_repository=business_pipeline_repository,
        ),
        learning=DeepAiLearningLedger(deep_ai_repository),
    )
    quality_evaluation_repository = QualityEvaluationRepository(database)
    quality_evaluation = QualityEvaluationService(
        repository=quality_evaluation_repository,
        deep_ai_repository=deep_ai_repository,
    )
    quality_shadow_repository = QualityShadowRepository(database)
    quality_shadow = QualityShadowService(
        repository=quality_shadow_repository,
        evaluation_repository=quality_evaluation_repository,
    )
    handoffs = HandoffService(database, approvals)
    returns = ReturnValidationService(database, handoffs)
    broker_sessions = BrokerSessionService(database, handoffs, returns, api_token=settings.api_token)
    readiness = CodexReadinessProbe(settings.codex_executable)
    provider_sessions = ProviderSessionService(database, handoffs, readiness=readiness.status)
    provider_artifacts = ProviderReturnArtifactStore(settings.paths.provider_returns_dir)
    provider_reviews = ProviderReviewService(database, provider_artifacts)
    provider_commits = ProviderCommitService(database, approvals)
    provider_publications = ProviderPublicationService(database, approvals)
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
        workflow_scheduler=workflow_scheduler,
        automation_repository=automation_repository,
        capability_router=capability_router,
        quality_gate=quality_gate,
        business_repository=business_repository,
        business_store=business_store,
        business=business,
        creative_repository=creative_repository,
        creative_source=creative_source,
        creative_store=creative_store,
        creative=creative,
        production_repository=production_repository,
        production_store=production_store,
        production=production,
        business_pipeline_repository=business_pipeline_repository,
        business_return_store=business_return_store,
        business_pipeline=business_pipeline,
        business_pipeline_scheduler=business_pipeline_scheduler,
        deep_ai_repository=deep_ai_repository,
        deep_ai_store=deep_ai_store,
        deep_ai=deep_ai,
        deep_ai_result_processor=deep_ai_result_processor,
        quality_evaluation_repository=quality_evaluation_repository,
        quality_evaluation=quality_evaluation,
        quality_shadow_repository=quality_shadow_repository,
        quality_shadow=quality_shadow,
        approvals=approvals,
        handoffs=handoffs,
        returns=returns,
        broker_sessions=broker_sessions,
        provider_sessions=provider_sessions,
        provider_artifacts=provider_artifacts,
        provider_reviews=provider_reviews,
        provider_commits=provider_commits,
        provider_publications=provider_publications,
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
