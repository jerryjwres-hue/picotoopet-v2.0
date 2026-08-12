"""FastAPI 应用工厂。"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from picotoopet_core import __version__
from picotoopet_core.api.middleware import BrokerReturnBodyLimitMiddleware, TraceTimingMiddleware
from picotoopet_core.config.models import AppSettings
from picotoopet_core.deep_ai.models import DeepAiEscalationStatus
from picotoopet_core.services import build_services

from .errors import install_error_handlers
from .routes import (
    approvals,
    automation,
    broker_sessions,
    business_automation,
    business_pipeline,
    creative_intelligence,
    deep_ai,
    events,
    handoffs,
    health,
    production,
    projects,
    provider_commits,
    provider_publications,
    provider_reviews,
    provider_sessions,
    results,
    returns,
    status,
    tasks,
    workers,
)

logger = logging.getLogger(__name__)


def create_app(settings: AppSettings) -> FastAPI:
    """创建已迁移数据库、后台工作流推进和统一路由的 Mac Core 应用。"""

    services = build_services(settings)

    async def run_workflow_scheduler(stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                services.workflow_scheduler.reconcile_all()
            except Exception:
                logger.exception("workflow scheduler reconciliation failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.workflow_reconcile_seconds)
            except TimeoutError:
                continue

    async def run_business_pipeline_scheduler(stop_event: asyncio.Event) -> None:
        # ── Reuse the bounded workflow cadence; do not add a producer-controlled interval ──
        while not stop_event.is_set():
            try:
                services.business_pipeline_scheduler.reconcile_all()
            except Exception:
                logger.exception("business pipeline scheduler reconciliation failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.workflow_reconcile_seconds)
            except TimeoutError:
                continue

    async def run_deep_ai_result_scheduler(stop_event: asyncio.Event) -> None:
        # This scheduler has no provider execution authority. It only finalizes already-paid,
        # durably committed results that are waiting in the deterministic Validating state.
        while not stop_event.is_set():
            try:
                for job in services.deep_ai_repository.list_jobs(limit=100):
                    if job.status is DeepAiEscalationStatus.VALIDATING:
                        services.deep_ai_result_processor.process(job.escalation_job_id)
            except Exception:
                logger.exception("deep-ai result reconciliation failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.workflow_reconcile_seconds)
            except TimeoutError:
                continue

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = services
        stop_event = asyncio.Event()
        dispatcher_task = asyncio.create_task(
            services.dispatcher.run(stop_event),
            name="picotoo-outbox-dispatcher",
        )
        workflow_scheduler_task = asyncio.create_task(
            run_workflow_scheduler(stop_event),
            name="picotoo-workflow-scheduler",
        )
        business_pipeline_scheduler_task = asyncio.create_task(
            run_business_pipeline_scheduler(stop_event),
            name="picotoo-business-pipeline-scheduler",
        )
        deep_ai_result_scheduler_task = asyncio.create_task(
            run_deep_ai_result_scheduler(stop_event),
            name="picotoo-deep-ai-result-scheduler",
        )
        try:
            yield
        finally:
            stop_event.set()
            await asyncio.gather(
                dispatcher_task,
                workflow_scheduler_task,
                business_pipeline_scheduler_task,
                deep_ai_result_scheduler_task,
            )
            services.close()

    app = FastAPI(title="Picotoo Pet Mac Core", version=__version__, lifespan=lifespan)
    app.state.services = services
    app.add_middleware(BrokerReturnBodyLimitMiddleware)
    app.add_middleware(TraceTimingMiddleware)
    install_error_handlers(app)
    prefix = "/api/v1"
    app.include_router(health.router, prefix=prefix, tags=["health"])
    app.include_router(projects.router, prefix=prefix, tags=["projects"])
    app.include_router(automation.router, prefix=prefix, tags=["automation"])
    app.include_router(business_automation.router, prefix=prefix, tags=["business-automation"])
    app.include_router(business_pipeline.router, prefix=prefix, tags=["business-pipeline"])
    app.include_router(creative_intelligence.router, prefix=prefix, tags=["creative-intelligence"])
    app.include_router(production.router, prefix=prefix, tags=["production"])
    app.include_router(deep_ai.router, prefix=prefix, tags=["deep-ai"])
    app.include_router(tasks.router, prefix=prefix, tags=["tasks"])
    app.include_router(workers.router, prefix=prefix, tags=["workers"])
    app.include_router(approvals.router, prefix=prefix, tags=["approvals"])
    app.include_router(handoffs.router, prefix=prefix, tags=["handoffs"])
    app.include_router(returns.router, prefix=prefix, tags=["returns"])
    app.include_router(broker_sessions.router, prefix=prefix, tags=["broker-sessions"])
    app.include_router(provider_sessions.router, prefix=prefix, tags=["provider-sessions"])
    app.include_router(provider_reviews.router, prefix=prefix, tags=["provider-reviews"])
    app.include_router(provider_commits.router, prefix=prefix, tags=["provider-commits"])
    app.include_router(provider_publications.router, prefix=prefix, tags=["provider-publications"])
    app.include_router(results.router, prefix=prefix, tags=["results"])
    app.include_router(events.router, prefix=prefix, tags=["events"])
    app.include_router(status.router, prefix=prefix, tags=["status", "audit"])
    return app
