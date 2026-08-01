"""FastAPI 应用工厂。"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from picotoopet_core import __version__
from picotoopet_core.api.middleware import TraceTimingMiddleware

from picotoopet_core.config.models import AppSettings
from picotoopet_core.services import build_services

from .errors import install_error_handlers
from .routes import approvals, events, health, projects, results, status, tasks


def create_app(settings: AppSettings) -> FastAPI:
    """创建已迁移数据库和统一路由的 Mac Core 应用。"""

    services = build_services(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = services
        stop_event         = asyncio.Event()
        dispatcher_task    = asyncio.create_task(
            services.dispatcher.run(stop_event),
            name="picotoo-outbox-dispatcher",
        )
        try:
            yield
        finally:
            stop_event.set()
            await dispatcher_task
            services.close()

    app = FastAPI(
        title="Picotoo Pet Mac Core",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.services = services
    app.add_middleware(TraceTimingMiddleware)
    install_error_handlers(app)
    prefix = "/api/v1"
    app.include_router(health.router, prefix=prefix, tags=["health"])
    app.include_router(projects.router, prefix=prefix, tags=["projects"])
    app.include_router(tasks.router, prefix=prefix, tags=["tasks"])
    app.include_router(approvals.router, prefix=prefix, tags=["approvals"])
    app.include_router(results.router, prefix=prefix, tags=["results"])
    app.include_router(events.router, prefix=prefix, tags=["events"])
    app.include_router(status.router, prefix=prefix, tags=["status", "audit"])
    return app
